"""Cœur agentique du Career Match Agent.

Trois capacités, toutes bilingues (fr/en) et orientées ATS :
- `analyze()`   : score de fit CV↔offre, forces/écarts, mots-clés ATS manquants,
                  projets à mettre en avant, et SUGGESTIONS d'amélioration du CV.
- `cover_letter()` : lettre de motivation adaptée à l'offre.
- `tailored_cv()`  : CV réorganisé/optimisé pour l'offre (format ATS).

Règle d'intégrité NON négociable, rappelée dans chaque prompt : **ne rien
inventer** — on ne fait que réorganiser, reformuler et mettre en avant ce qui
existe déjà dans le CV de base.
"""
from core import llm

_NO_FABRICATION = {
    "fr": "RÈGLE ABSOLUE : n'invente RIEN. N'ajoute aucune expérience, diplôme, "
          "compétence ou chiffre qui ne figure pas déjà dans le CV. Tu réorganises, "
          "reformules et mets en avant l'existant — jamais de mensonge.",
    "en": "ABSOLUTE RULE: invent NOTHING. Do not add any experience, degree, skill "
          "or figure not already in the CV. You reorganise, rephrase and surface what "
          "already exists — never fabricate.",
}
_ATS = {
    "fr": "Optimise pour les ATS : réutilise les mots-clés EXACTS de l'offre quand le "
          "candidat les possède vraiment, sections standard claires, texte simple sur une "
          "colonne, pas de tableau/graphisme/emoji, verbes d'action, résultats chiffrés.",
    "en": "Optimise for ATS: reuse the EXACT keywords from the offer when the candidate "
          "genuinely has them, clear standard sections, plain single-column text, no "
          "tables/graphics/emojis, action verbs, quantified results.",
}


def _lang(lang: str) -> str:
    return "en" if str(lang).lower().startswith("en") else "fr"


def analyze(cv_text: str, offer_text: str, ats_cov: dict, lang: str = "fr") -> tuple:
    """Retourne (dict, err). dict = {fit_score, verdict, strengths[], gaps[],
    keywords_missing[], projects_to_highlight[], cv_suggestions[]}."""
    lg = _lang(lang)
    missing = ", ".join((ats_cov or {}).get("missing", [])[:20]) or "—"
    pct = (ats_cov or {}).get("pct", 0)
    if lg == "en":
        prompt = (
            "You are a technical recruiter + ATS expert. Compare this candidate's CV to "
            "the job offer and return a rigorous assessment.\n\n"
            f"Deterministic ATS keyword coverage already computed: {pct}% "
            f"(missing offer keywords: {missing}).\n\n"
            "Return ONLY JSON:\n"
            '{"fit_score": <0-100>, "verdict": "<one sentence>", '
            '"strengths": ["<CV matches the offer on…>"], '
            '"gaps": ["<what is missing/weak vs the offer>"], '
            '"keywords_missing": ["<important offer keywords absent or under-used in the CV>"], '
            '"projects_to_highlight": ["<which of the candidate\'s projects to emphasise for THIS offer + why>"], '
            '"cv_suggestions": ["<concrete, actionable edits to raise the score: wording, keywords, ordering, quantification>"]}\n'
            "Be specific and honest. Base everything ONLY on the CV.\n\n"
            f"=== JOB OFFER ===\n{offer_text[:6000]}\n\n=== CANDIDATE CV ===\n{cv_text[:6000]}"
        )
    else:
        prompt = (
            "Tu es recruteur technique + expert ATS. Compare le CV du candidat à l'offre "
            "et renvoie une évaluation rigoureuse.\n\n"
            f"Couverture de mots-clés ATS déjà calculée : {pct}% "
            f"(mots-clés de l'offre manquants : {missing}).\n\n"
            "Réponds UNIQUEMENT en JSON :\n"
            '{"fit_score": <0-100>, "verdict": "<une phrase>", '
            '"strengths": ["<le CV colle à l\'offre sur…>"], '
            '"gaps": ["<ce qui manque/est faible vs l\'offre>"], '
            '"keywords_missing": ["<mots-clés importants de l\'offre absents ou sous-exploités dans le CV>"], '
            '"projects_to_highlight": ["<quels projets du candidat mettre en avant pour CETTE offre + pourquoi>"], '
            '"cv_suggestions": ["<modifications concrètes et actionnables pour augmenter le score : formulation, mots-clés, ordre, chiffrage>"]}\n'
            "Sois précis et honnête. Base TOUT uniquement sur le CV.\n\n"
            f"=== OFFRE ===\n{offer_text[:6000]}\n\n=== CV DU CANDIDAT ===\n{cv_text[:6000]}"
        )
    raw, err = llm.complete(prompt, json_mode=True, max_tokens=1600)
    if err:
        return None, err
    data = llm.parse_json(raw)
    if not isinstance(data, dict):
        return None, "Réponse LLM illisible"
    try:
        data["fit_score"] = max(0, min(100, int(data.get("fit_score", 0) or 0)))
    except (TypeError, ValueError):
        data["fit_score"] = 0
    for k in ("strengths", "gaps", "keywords_missing", "projects_to_highlight", "cv_suggestions"):
        v = data.get(k)
        data[k] = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
    data["verdict"] = str(data.get("verdict", "")).strip()
    return data, None


def cover_letter(cv_text: str, offer_text: str, lang: str = "fr", tone: str = "professionnel") -> tuple:
    """Retourne (texte, err)."""
    lg = _lang(lang)
    if lg == "en":
        prompt = (
            f"Write a tailored cover letter in ENGLISH for this job offer, based on the CV. "
            f"Tone: {tone}. 3-4 short paragraphs, ~250-300 words, no placeholders left blank "
            "(use the candidate's real name/details from the CV). Concrete: tie the candidate's "
            "real experience/projects to the offer's needs.\n"
            f"{_NO_FABRICATION['en']}\n{_ATS['en']}\n\n"
            f"=== JOB OFFER ===\n{offer_text[:5000]}\n\n=== CV ===\n{cv_text[:5000]}"
        )
    else:
        prompt = (
            f"Rédige une lettre de motivation en FRANÇAIS pour cette offre, à partir du CV. "
            f"Ton : {tone}. 3-4 paragraphes courts, ~250-300 mots, sans champ laissé vide "
            "(utilise le vrai nom/coordonnées du CV). Concret : relie l'expérience/les projets "
            "réels du candidat aux besoins de l'offre.\n"
            f"{_NO_FABRICATION['fr']}\n{_ATS['fr']}\n\n"
            f"=== OFFRE ===\n{offer_text[:5000]}\n\n=== CV ===\n{cv_text[:5000]}"
        )
    raw, err = llm.complete(prompt, json_mode=False, max_tokens=900, temperature=0.5)
    if err:
        return None, err
    return (raw or "").strip(), None


def tailored_cv(cv_text: str, offer_text: str, lang: str = "fr") -> tuple:
    """Retourne (markdown, err). CV réorganisé/optimisé pour l'offre, format ATS."""
    lg = _lang(lang)
    if lg == "en":
        prompt = (
            "Rewrite the candidate's CV, TAILORED to this job offer and ATS-optimised. "
            "Output clean Markdown, single column, standard sections (Summary, Skills, "
            "Experience, Projects, Education). Reorder and rephrase to surface what matches "
            "the offer; weave in the offer's exact keywords the candidate genuinely has.\n"
            f"{_NO_FABRICATION['en']}\n{_ATS['en']}\n\n"
            f"=== JOB OFFER ===\n{offer_text[:5000]}\n\n=== BASE CV ===\n{cv_text[:6000]}"
        )
    else:
        prompt = (
            "Réécris le CV du candidat, ADAPTÉ à cette offre et optimisé ATS. Sortie en "
            "Markdown propre, une seule colonne, sections standard (Profil, Compétences, "
            "Expériences, Projets, Formation). Réordonne et reformule pour faire ressortir "
            "ce qui colle à l'offre ; intègre les mots-clés exacts de l'offre que le candidat "
            "possède vraiment.\n"
            f"{_NO_FABRICATION['fr']}\n{_ATS['fr']}\n\n"
            f"=== OFFRE ===\n{offer_text[:5000]}\n\n=== CV DE BASE ===\n{cv_text[:6000]}"
        )
    raw, err = llm.complete(prompt, json_mode=False, max_tokens=1800, temperature=0.35)
    if err:
        return None, err
    return (raw or "").strip(), None
