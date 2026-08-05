"""Career Match Agent — API FastAPI.

Endpoints :
  POST /extract-cv    (multipart) → texte du CV
  POST /analyze       → fit CV↔offre + mots-clés ATS + projets + suggestions + reco go/no-go
  POST /cover-letter  → lettre de motivation adaptée (fr/en, ATS)
  POST /tailored-cv   → CV réécrit pour l'offre (fr/en, ATS, Markdown)
  POST /prepare       → agent autonome (ReAct) : prépare toute la candidature
  GET  /memory        → profil agrégé + écarts récurrents (mémoire long terme)

Pipeline de stages (sourcing → dossier prêt → candidature revue puis envoyée par TOI) :
  GET  /sources                 → catalogue des sources que l'agent propose (cochables)
  POST /source                  → cherche + CLASSE les offres selon ta recherche et ton CV
  GET  /pipeline                → file d'offres (+ ?status=)
  POST /pipeline/{id}/analyze   → fit + ATS + go/no-go sur une offre du pipeline
  POST /pipeline/{id}/prepare   → dossier complet : CV adapté (md+HTML) + lettre + messages
  POST /pipeline/{id}/status    → marquer sent / skipped / …
  GET  /pipeline/{id}/letter.docx  → lettre en Word
  GET  /pipeline/{id}/cv.pdf       → CV adapté en PDF (2 colonnes)
  GET|PUT /templates            → templates de message + prompt de la lettre (éditables)

Tout est AGNOSTIQUE AU MÉTIER (les mots-clés ATS sont extraits de l'offre par le LLM).
L'agent ne soumet JAMAIS une candidature lui-même : il prépare, tu envoies.
Sert aussi le frontend statique à la racine.
"""
import os

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# TLS via le magasin de certificats du système (Windows/macOS) — indispensable
# derrière certains proxys/antivirus d'entreprise. Jamais de verify=False.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from core import (llm, ats, extract, agent, memory, orchestrator, render, sources, pipeline,
                  templates, export, atscheck)

app = FastAPI(title="Career Match Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "index.html")


@app.get("/", response_class=HTMLResponse)
def home():
    try:
        with open(_FRONTEND, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Career Match Agent</h1><p>API prête. Frontend introuvable.</p>"


@app.get("/health")
def health():
    return {"status": "ok", "llm_ready": llm.is_enabled()}


@app.post("/extract-cv")
async def extract_cv(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Fichier trop volumineux (max 10 Mo)")
    text, err = extract.extract_cv_text(file.filename, data)
    if err:
        raise HTTPException(400, err)
    # Certains PDF (exports Canva/Figma) ressortent lettre par lettre : sans cette
    # réparation, TOUT le reste de la chaîne raisonne sur du bruit.
    notes = []
    text, repaired = atscheck.repair_char_spacing(text or "")
    if repaired:
        notes.append("Ton PDF ressort lettre par lettre à l'extraction : je l'ai recollé pour "
                     "travailler dessus, mais un ATS, lui, ne le fera pas. Lance l'audit de "
                     "parsing pour voir les dégâts.")
    if len((text or "").strip()) < 30:
        raise HTTPException(422, "CV vide ou illisible (PDF scanné en image ?). Essaie un .txt/.md ou un PDF texte.")
    return {"filename": file.filename, "cv_text": text, "chars": len(text), "notes": notes}


class OfferBody(BaseModel):
    cv_text: str
    offer_text: Optional[str] = ""
    offer_url: Optional[str] = ""
    lang: str = "fr"
    tone: Optional[str] = "professionnel"
    letter_style: Optional[str] = ""   # consignes libres sur la FORME de la lettre
    email_style: Optional[str] = ""    # idem pour l'e-mail de candidature
    company: Optional[str] = ""        # contexte facultatif (sinon déduit de l'offre)
    role: Optional[str] = ""


def _resolve(body: OfferBody):
    """Retourne (cv_text, offer_text) ou lève une HTTPException."""
    cv = (body.cv_text or "").strip()
    if len(cv) < 30:
        raise HTTPException(422, "CV manquant — upload-le d'abord.")
    offer = (body.offer_text or "").strip()
    if not offer and (body.offer_url or "").strip():
        offer, err = extract.fetch_offer_url(body.offer_url)
        if err:
            raise HTTPException(400, f"Offre (URL) : {err}")
    if len(offer) < 30:
        raise HTTPException(422, "Offre manquante — colle le texte de l'offre (ou une URL).")
    return cv, offer


def _guard_llm():
    if not llm.is_enabled():
        raise HTTPException(503, "OPENAI_API_KEY manquante — ajoute ta clé dans backend/.env")


@app.post("/analyze")
def do_analyze(body: OfferBody):
    _guard_llm()
    cv, offer = _resolve(body)
    extra, _kw_err = agent.offer_keywords(offer, body.lang)     # mots-clés tous domaines (fail-open)
    keywords = ats.extract_keywords(offer, extra=extra)
    cov = ats.coverage(cv, keywords)
    data, err = agent.analyze(cv, offer, cov, body.lang)
    if err:
        raise HTTPException(502, f"Analyse indisponible : {err}")
    # #4 mémoire : offre déjà vue ? écarts récurrents ?
    prev = memory.recall(offer)
    prof = memory.profile_summary()
    note = ", ".join(g["keyword"] for g in prof.get("recurring_gaps", [])) or ""
    # #5 planification / décision go-no-go
    rec, _rerr = agent.recommend(data, cov, body.lang, memory_note=note)
    memory.record_application(offer, {
        "fit_score": data.get("fit_score"), "ats_pct": cov.get("pct"),
        "recommendation": (rec or {}).get("decision"), "missing_keywords": cov.get("missing"),
    })
    return {"ats": cov, "keywords": keywords, "analysis": data,
            "recommendation": rec, "memory": {"seen_before": bool(prev), "profile": prof}}


@app.get("/memory")
def do_memory():
    """Profil agrégé du candidat + écarts récurrents (mémoire long terme)."""
    return memory.profile_summary()


@app.post("/prepare")
def do_prepare(body: OfferBody):
    """Agent autonome (ReAct) : le LLM enchaîne lui-même les outils (ATS, analyse,
    mémoire, reco, lettre, CV) pour préparer toute la candidature."""
    _guard_llm()
    cv, offer = _resolve(body)
    result, err = orchestrator.prepare_application(cv, offer, "", body.lang)
    if err:
        raise HTTPException(502, f"Agent indisponible : {err}")
    return result


@app.post("/cover-letter")
def do_cover_letter(body: OfferBody):
    """Boucle agentique : rédige → mesure la qualité rédactionnelle (déterministe) →
    vérifie l'anti-invention → révise → relit. Renvoie la lettre + la trace."""
    _guard_llm()
    cv, offer = _resolve(body)
    style = (body.letter_style or "").strip() or templates.get_all().get("letter_prompt", "")
    res, err = agent.optimize_cover_letter(cv, offer, body.lang, body.tone or "professionnel",
                                           style_notes=style)
    if err:
        raise HTTPException(502, f"Génération indisponible : {err}")
    return {
        "cover_letter": res["cover_letter"],
        "quality_start": res["quality_start"],
        "quality_final": res["quality_final"],
        "quality_issues": res["quality_issues"],
        "iterations": res["iterations"],
        "unsupported_final": res["unsupported_final"],
    }


def _parse_report(structured, cv_markdown: str, lang: str, keywords, offer_text: str = "") -> dict:
    """Audit de parsing du PDF RÉELLEMENT téléchargeable (mise en page ATS).

    Le contrôle qui manquait : jusqu'ici on optimisait le Markdown, et personne ne
    vérifiait que le PDF déposé sur le portail restituait bien ce texte. Fail-open :
    si le rendu échoue, la génération n'échoue pas pour autant."""
    try:
        pdf = export.cv_pdf(structured, cv_markdown or "", lang, layout="ats")
        rep = atscheck.audit(pdf, keywords or None, cv_markdown or "", offer_text)
        rep.pop("text", None)
        return rep
    except Exception as e:                       # pragma: no cover - garde-fou
        return {"score": None, "error": str(e), "issues": []}


@app.post("/outreach-email")
def do_outreach_email(body: OfferBody):
    """E-mail de candidature RÉDIGÉ pour cette offre (objet + corps), prêt à envoyer.

    À ne pas confondre avec `templates.email`, qui substitue des variables dans un
    texte figé : ici le contenu change selon ce que l'offre demande et ce que le CV
    prouve. Le template de l'utilisateur, s'il en a un, sert de guide de style."""
    _guard_llm()
    cv, offer = _resolve(body)
    style = (body.email_style or "").strip() or templates.get_all().get("email", "")
    res, err = agent.outreach_email(cv, offer, body.lang, body.tone or "professionnel",
                                    company=body.company or "", role=body.role or "",
                                    link=(body.offer_url or ""), style_notes=style)
    if err:
        raise HTTPException(502, f"Génération indisponible : {err}")
    return res


@app.post("/tailored-cv")
def do_tailored_cv(body: OfferBody):
    """Boucle agentique : génère → mesure ATS → vérifie l'intégrité → révise,
    en gardant la meilleure version. Renvoie le CV + la trace d'optimisation."""
    _guard_llm()
    cv, offer = _resolve(body)
    result, err = agent.optimize_cv(cv, offer, body.lang)
    if err:
        raise HTTPException(502, f"Génération indisponible : {err}")
    md = result["cv_markdown"]
    structured, _serr = agent.cv_to_structured(md, body.lang)   # JSON pour la mise en page (fail-open)
    return {
        "tailored_cv_markdown": md,
        "tailored_cv_html": render.cv_html(md, structured, body.lang),
        "cv_structured": structured,               # pour l'export PDF sans rappel LLM
        "ats_parse": _parse_report(structured, md, body.lang, result.get("keywords"), offer),
        "ats_start": result["ats_start"],
        "ats_final": result["ats_final"],
        "ats_weighted_final": result.get("ats_weighted_final"),
        "critical_missing": result.get("critical_missing", []),
        "iterations": result["iterations"],
        "unsupported_final": result["unsupported_final"],
        "quality_start": result["quality_start"],
        "quality_final": result["quality_final"],
        "quality_issues": result["quality_issues"],
    }


# ── Exports directs (section 1 : analyse classique, sans passer par le pipeline) ──

class LetterExportBody(BaseModel):
    text: str


@app.post("/export/letter.docx")
def do_export_letter(body: LetterExportBody):
    """Lettre (texte) → fichier Word téléchargeable."""
    if len((body.text or "").strip()) < 10:
        raise HTTPException(422, "Lettre vide — génère-la d'abord.")
    return Response(
        content=export.letter_docx(body.text),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="Lettre_motivation.docx"'},
    )


class EmailExportBody(BaseModel):
    subject: str = ""
    body: str
    to: Optional[str] = ""


@app.post("/export/email.eml")
def do_export_email(body: EmailExportBody):
    """E-mail (objet + corps) → fichier .eml : double-clic, il s'ouvre dans le
    client de messagerie avec tout de pré-rempli."""
    if len((body.body or "").strip()) < 10:
        raise HTTPException(422, "E-mail vide — génère-le d'abord.")
    return Response(
        content=export.email_eml(body.subject, body.body, body.to or ""),
        media_type="message/rfc822",
        headers={"Content-Disposition": 'attachment; filename="Candidature.eml"'},
    )


class CvExportBody(BaseModel):
    cv_markdown: str
    cv_structured: Optional[dict] = None   # renvoyé par /tailored-cv ou /prepare
    lang: str = "fr"
    layout: str = "ats"                    # "ats" (1 colonne, à envoyer) | "designed" (2 colonnes)


@app.post("/export/cv.pdf")
def do_export_cv(body: CvExportBody):
    """CV adapté (Markdown + JSON structuré éventuel) → PDF téléchargeable.

    `layout="ats"` (défaut) = une colonne, la version qui traverse les robots ;
    `layout="designed"` = 2 colonnes, pour un envoi direct à un humain."""
    has_structured = isinstance(body.cv_structured, dict) and (body.cv_structured.get("name") or "").strip()
    if not has_structured and len((body.cv_markdown or "").strip()) < 10:
        raise HTTPException(422, "CV vide — génère-le d'abord.")
    designed = str(body.layout).lower() == "designed"
    return Response(
        content=export.cv_pdf(body.cv_structured, body.cv_markdown, body.lang, layout=body.layout),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="CV_adapte{"_design" if designed else "_ATS"}.pdf"'},
    )


# ── Audit de parsing ATS : ce que le robot lit vraiment dans le PDF ──────────

@app.post("/ats-check")
async def do_ats_check(file: UploadFile = File(...), offer_text: str = Form(""),
                       lang: str = Form("fr")):
    """Passe un PDF de CV (le TIEN, pas seulement ceux générés ici) dans les
    extracteurs qu'utilisent les ATS et renvoie ce qui survit : score de parsing,
    coordonnées retrouvées, sections identifiées, mots-clés matchables.

    Aucune clé LLM requise sans offre. Avec `offer_text` et une clé, les mots-clés
    de l'offre sont extraits puis mesurés sur le texte RÉ-EXTRAIT du PDF."""
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Fichier trop volumineux (max 10 Mo)")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Envoie un PDF — c'est le format déposé sur les portails.")

    keywords = []
    offer = (offer_text or "").strip()
    if len(offer) >= 30:
        extra = []
        if llm.is_enabled():
            extra, _ = agent.offer_keywords(offer, lang)     # fail-open
        keywords = ats.extract_keywords(offer, extra=extra)

    report = atscheck.audit(data, keywords or None, offer_text=offer)
    report.pop("text", None)                                  # réponse compacte
    return {"filename": file.filename, "report": report}


class AtsCheckTextBody(BaseModel):
    cv_markdown: str = ""
    cv_structured: Optional[dict] = None
    lang: str = "fr"
    offer_text: str = ""
    keywords: list[str] = []


@app.post("/ats-check/compare")
def do_ats_compare(body: AtsCheckTextBody):
    """Rend le CV adapté dans les DEUX mises en page et audite chacune : preuve
    chiffrée de ce que la version 2 colonnes coûte (ou non) sur CE CV-là."""
    if not (body.cv_markdown or "").strip() and not isinstance(body.cv_structured, dict):
        raise HTTPException(422, "CV vide — génère-le d'abord.")
    kws = list(body.keywords or [])
    if not kws and len((body.offer_text or "").strip()) >= 30:
        extra = []
        if llm.is_enabled():
            extra, _ = agent.offer_keywords(body.offer_text, body.lang)
        kws = ats.extract_keywords(body.offer_text, extra=extra)
    return atscheck.compare_layouts(body.cv_structured, body.cv_markdown, body.lang,
                                    kws or None, body.offer_text or "")


# ═══ Pipeline de stages : sourcing → analyse → dossier prêt → envoi (à toi) ═══

@app.get("/sources")
def do_sources():
    """Catalogue des sources dont l'agent dispose — l'UI les propose en cases à
    cocher (tout, une seule, plusieurs…) ; l'utilisateur peut aussi ajouter les siennes."""
    return {"catalog": sources.catalog()}


class SourceBody(BaseModel):
    keywords: list[str] = []
    location: list[str] = []
    target_description: str = ""    # description libre du stage recherché (matching)
    cv_text: str = ""               # CV (matching fit candidat, optionnel)
    internship_only: bool = True
    greenhouse: list[str] = []      # slugs de boards Greenhouse
    lever: list[str] = []           # slugs d'entreprises Lever
    ashby: list[str] = []           # slugs d'orgs Ashby
    remoteok: bool = False
    jobicy: str = ""                # géo Jobicy ("france", "emea"…) — vide = désactivé
    arbeitnow: bool = False
    rss: list[str] = []             # flux RSS personnalisés (Novojob, écoles…)
    lang: str = "fr"
    limit: int = 40


@app.post("/source")
def do_source(body: SourceBody):
    """Cherche des offres via les sources choisies, puis les CLASSE par pertinence
    (description du stage recherché + fit avec le CV) avant d'alimenter le pipeline."""
    if not (body.greenhouse or body.lever or body.ashby or body.remoteok
            or body.jobicy or body.arbeitnow or body.rss):
        raise HTTPException(422, "Choisis au moins une source (catalogue ou slugs/flux personnalisés).")
    offers, errors = sources.search(body.model_dump())
    # Classement : mots-clés de la recherche (description cible enrichie par le LLM
    # si dispo — fail-open) + part des mots-clés de chaque offre déjà dans le CV.
    target = " ".join([body.target_description or ""] + (body.keywords or [])).strip()
    extra = []
    if body.target_description.strip():
        extra, _ = agent.offer_keywords(body.target_description, body.lang)
    offers = sources.rank_offers(offers, target, body.cv_text, extra_keywords=extra)
    added = pipeline.add_offers(offers)
    return {"found": len(offers), "added": added, "errors": errors,
            "stats": pipeline.stats(), "items": pipeline.list_items()}


@app.get("/pipeline")
def do_pipeline(status: Optional[str] = None):
    return {"stats": pipeline.stats(), "items": pipeline.list_items(status)}


class StatusBody(BaseModel):
    status: str


@app.post("/pipeline/{item_id}/status")
def do_pipeline_status(item_id: str, body: StatusBody):
    try:
        item = pipeline.update(item_id, status=body.status)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not item:
        raise HTTPException(404, "Offre introuvable dans le pipeline")
    return {"ok": True, "id": item_id, "status": body.status}


def _pipeline_offer(item_id: str) -> tuple:
    """(item, offer_text) — récupère le texte de l'offre (description sourcée,
    sinon fetch de l'URL en repli)."""
    item = pipeline.get(item_id)
    if not item:
        raise HTTPException(404, "Offre introuvable dans le pipeline")
    offer = (item.get("offer_text") or "").strip()
    if len(offer) < 30 and item.get("url"):
        offer, err = extract.fetch_offer_url(item["url"])
        if not err and len(offer) >= 30:
            pipeline.update(item_id, offer_text=offer[:12000])
    if len(offer) < 30:
        raise HTTPException(422, "Texte de l'offre introuvable — ouvre l'offre et colle son texte dans l'onglet Offre.")
    return item, offer


class PipelineCvBody(BaseModel):
    cv_text: str
    lang: str = "fr"
    tone: Optional[str] = "professionnel"
    my_name: Optional[str] = ""
    first_name: Optional[str] = ""   # prénom du recruteur (messages)
    letter_style: Optional[str] = "" # consignes de style pour la lettre (sinon template 'letter_prompt')
    email_style: Optional[str] = ""  # idem pour l'e-mail de candidature (sinon template 'email')


@app.post("/pipeline/{item_id}/analyze")
def do_pipeline_analyze(item_id: str, body: PipelineCvBody):
    """Fit + ATS + go/no-go pour UNE offre du pipeline (mêmes briques que /analyze)."""
    _guard_llm()
    if len((body.cv_text or "").strip()) < 30:
        raise HTTPException(422, "CV manquant — upload-le d'abord.")
    item, offer = _pipeline_offer(item_id)
    extra, _ = agent.offer_keywords(offer, body.lang)
    cov = ats.coverage(body.cv_text, ats.extract_keywords(offer, extra=extra))
    data, err = agent.analyze(body.cv_text, offer, cov, body.lang)
    if err:
        raise HTTPException(502, f"Analyse indisponible : {err}")
    rec, _ = agent.recommend(data, cov, body.lang)
    memory.record_application(offer, {
        "fit_score": data.get("fit_score"), "ats_pct": cov.get("pct"),
        "recommendation": (rec or {}).get("decision"), "missing_keywords": cov.get("missing"),
    })
    pipeline.update(item_id, status="analyzed", fit_score=data.get("fit_score"),
                    ats_pct=cov.get("pct"), decision=(rec or {}).get("decision"))
    return {"id": item_id, "ats": cov, "analysis": data, "recommendation": rec}


@app.post("/pipeline/{item_id}/prepare")
def do_pipeline_prepare(item_id: str, body: PipelineCvBody):
    """Dossier de candidature complet pour une offre du pipeline :
    CV adapté (boucle agentique, md + HTML pro) + lettre + messages d'outreach
    rendus depuis TES templates. L'agent prépare — TOI tu envoies."""
    _guard_llm()
    if len((body.cv_text or "").strip()) < 30:
        raise HTTPException(422, "CV manquant — upload-le d'abord.")
    item, offer = _pipeline_offer(item_id)

    result, err = agent.optimize_cv(body.cv_text, offer, body.lang)
    if err:
        raise HTTPException(502, f"Génération du CV indisponible : {err}")
    md = result["cv_markdown"]
    structured, _ = agent.cv_to_structured(md, body.lang)
    # consignes de style de la lettre : requête > template 'letter_prompt' sauvegardé
    style = (body.letter_style or "").strip() or templates.get_all().get("letter_prompt", "")
    lres, lerr = agent.optimize_cover_letter(body.cv_text, offer, body.lang,
                                             body.tone or "professionnel", style_notes=style)
    letter = (lres or {}).get("cover_letter", "")

    # personnalisation des messages : meilleur projet à mettre en avant selon l'analyse
    analysis, _ = agent.analyze(body.cv_text, offer, {"pct": result["ats_final"], "matched": [], "missing": []}, body.lang)
    highlight = ""
    if analysis and analysis.get("projects_to_highlight"):
        highlight = str(analysis["projects_to_highlight"][0]).split("—")[0].split(":")[0].strip()[:80]
    tvars = {
        "company": item.get("company") or "", "role": item.get("title") or "",
        "my_name": body.my_name or "", "first_name": body.first_name or "",
        "highlight": highlight or "mes projets récents", "link": item.get("url") or "",
    }
    messages = {k: templates.render(k, tvars) for k in ("linkedin_invite", "linkedin_message", "email")}

    # E-mail RÉDIGÉ pour cette offre : le template ne sert plus que de guide de
    # style, et de repli si le LLM est indisponible (fail-open).
    mail, _merr = agent.outreach_email(
        body.cv_text, offer, body.lang, body.tone or "professionnel",
        company=item.get("company") or "", role=item.get("title") or "",
        link=item.get("url") or "",
        style_notes=(body.email_style or "").strip() or templates.get_all().get("email", ""))
    email_subject = ""
    if mail:
        messages["email"] = mail["body"]
        email_subject = mail["subject"]

    prepared = {
        "cv_markdown": md,
        "cv_html": render.cv_html(md, structured, body.lang),
        "cv_structured": structured,            # pour l'export PDF sans rappel LLM
        "lang": body.lang,
        "cover_letter": letter or "",
        "cover_letter_error": lerr or "",
        "messages": messages,
        "email_subject": email_subject,
        "ats_start": result["ats_start"], "ats_final": result["ats_final"],
        "ats_weighted_final": result.get("ats_weighted_final"),
        "critical_missing": result.get("critical_missing", []),
        "ats_parse": _parse_report(structured, md, body.lang, result.get("keywords"), offer),
        "unsupported_final": result["unsupported_final"],
        "quality_start": result["quality_start"], "quality_final": result["quality_final"],
        "letter_quality": (lres or {}).get("quality_final"),
    }
    pipeline.update(item_id, status="ready", prepared=prepared,
                    fit_score=(analysis or {}).get("fit_score", item.get("fit_score")),
                    ats_pct=result["ats_final"])
    return {"id": item_id, "prepared": prepared}


@app.get("/pipeline/{item_id}")
def do_pipeline_get(item_id: str):
    item = pipeline.get(item_id)
    if not item:
        raise HTTPException(404, "Offre introuvable dans le pipeline")
    return item


# ── Templates de message (éditables) ────────────────────────────────────────

@app.get("/templates")
def do_templates_get():
    return templates.get_all()


class TemplatesBody(BaseModel):
    templates: dict


@app.put("/templates")
def do_templates_put(body: TemplatesBody):
    return templates.save(body.templates or {})


# ── Exports bureautiques : lettre en Word, CV en PDF ────────────────────────

def _prepared_or_422(item_id: str) -> dict:
    item = pipeline.get(item_id)
    if not item:
        raise HTTPException(404, "Offre introuvable dans le pipeline")
    prepared = item.get("prepared") or {}
    if not prepared:
        raise HTTPException(422, "Prépare d'abord le dossier de cette offre (bouton Préparer).")
    return {"item": item, "prepared": prepared}


@app.get("/pipeline/{item_id}/letter.docx")
def do_letter_docx(item_id: str):
    d = _prepared_or_422(item_id)
    letter = d["prepared"].get("cover_letter") or ""
    if not letter.strip():
        raise HTTPException(422, "Pas de lettre dans ce dossier.")
    data = export.letter_docx(letter)
    name = f"Lettre_{(d['item'].get('company') or 'offre').replace(' ', '_')}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/pipeline/{item_id}/email.eml")
def do_email_eml(item_id: str):
    """E-mail de candidature de ce dossier, au format .eml (objet + corps pré-remplis)."""
    d = _prepared_or_422(item_id)
    p = d["prepared"]
    mail = (p.get("messages") or {}).get("email") or ""
    if not mail.strip():
        raise HTTPException(422, "Pas d'e-mail dans ce dossier.")
    subject = p.get("email_subject") or f"Candidature - {d['item'].get('title') or 'poste'}"
    name = f"Mail_{(d['item'].get('company') or 'offre').replace(' ', '_')}.eml"
    return Response(content=export.email_eml(subject, mail), media_type="message/rfc822",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/pipeline/{item_id}/cv.pdf")
def do_cv_pdf(item_id: str, layout: str = "ats"):
    """CV du dossier en PDF. `?layout=designed` pour la version 2 colonnes ;
    par défaut la version une colonne, celle qui passe les robots."""
    d = _prepared_or_422(item_id)
    p = d["prepared"]
    if not (p.get("cv_markdown") or "").strip():
        raise HTTPException(422, "Pas de CV adapté dans ce dossier.")
    data = export.cv_pdf(p.get("cv_structured"), p.get("cv_markdown") or "",
                         p.get("lang") or "fr", layout=layout)
    suffix = "design" if str(layout).lower() == "designed" else "ATS"
    name = f"CV_{(d['item'].get('company') or 'offre').replace(' ', '_')}_{suffix}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
