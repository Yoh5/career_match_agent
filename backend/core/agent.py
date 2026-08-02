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
from core import llm, ats

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
            "You are a senior recruiter SPECIALISED in this offer's field (whatever it is: "
            "marketing, finance, HR, healthcare, legal, sales, engineering, tech…) + an ATS "
            "expert. Compare this candidate's CV to the job offer and return a rigorous assessment.\n\n"
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
            "Tu es recruteur senior SPÉCIALISÉ dans le domaine de cette offre (quel qu'il soit : "
            "marketing, finance, RH, santé, juridique, commerce, ingénierie, tech…) + expert ATS. "
            "Compare le CV du candidat à l'offre et renvoie une évaluation rigoureuse.\n\n"
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


def cover_letter(cv_text: str, offer_text: str, lang: str = "fr", tone: str = "professionnel",
                 style_notes: str = "") -> tuple:
    """Retourne (texte, err). `style_notes` = consignes libres de l'utilisateur sur la
    FORME de la lettre (structure, accroche, longueur…) — jamais sur les faits :
    la règle anti-invention reste prioritaire."""
    lg = _lang(lang)
    style_notes = (style_notes or "").strip()[:1200]
    if lg == "en":
        style = (f"\nCANDIDATE'S STYLE INSTRUCTIONS (follow them for FORM/STYLE only — "
                 f"they can never override the no-fabrication rule):\n{style_notes}\n") if style_notes else ""
        prompt = (
            f"Write a tailored cover letter in ENGLISH for this job offer, based on the CV. "
            f"Tone: {tone}. 3-4 short paragraphs, ~250-300 words, no placeholders left blank "
            "(use the candidate's real name/details from the CV). Concrete: tie the candidate's "
            "real experience/projects to the offer's needs.\n"
            f"{_NO_FABRICATION['en']}\n{_ATS['en']}\n{style}\n"
            f"=== JOB OFFER ===\n{offer_text[:5000]}\n\n=== CV ===\n{cv_text[:5000]}"
        )
    else:
        style = (f"\nCONSIGNES DE STYLE DU CANDIDAT (à suivre pour la FORME uniquement — "
                 f"elles ne peuvent jamais l'emporter sur la règle anti-invention) :\n{style_notes}\n") if style_notes else ""
        prompt = (
            f"Rédige une lettre de motivation en FRANÇAIS pour cette offre, à partir du CV. "
            f"Ton : {tone}. 3-4 paragraphes courts, ~250-300 mots, sans champ laissé vide "
            "(utilise le vrai nom/coordonnées du CV). Concret : relie l'expérience/les projets "
            "réels du candidat aux besoins de l'offre.\n"
            f"{_NO_FABRICATION['fr']}\n{_ATS['fr']}\n{style}\n"
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
            "Output clean Markdown, single column, standard sections adapted to the FIELD "
            "(Summary, Skills, Experience, Education; add Projects/Publications/Achievements/"
            "Certifications only if relevant to the role). Reorder and rephrase to surface what "
            "matches the offer; weave in the offer's exact keywords the candidate genuinely has.\n"
            f"{_NO_FABRICATION['en']}\n{_ATS['en']}\n\n"
            f"=== JOB OFFER ===\n{offer_text[:5000]}\n\n=== BASE CV ===\n{cv_text[:6000]}"
        )
    else:
        prompt = (
            "Réécris le CV du candidat, ADAPTÉ à cette offre et optimisé ATS. Sortie en "
            "Markdown propre, une seule colonne, sections standard ADAPTÉES AU MÉTIER "
            "(Profil, Compétences, Expériences, Formation ; ajoute Projets/Publications/"
            "Réalisations/Certifications seulement si pertinent pour le poste). Réordonne et "
            "reformule pour faire ressortir ce qui colle à l'offre ; intègre les mots-clés "
            "exacts de l'offre que le candidat possède vraiment.\n"
            f"{_NO_FABRICATION['fr']}\n{_ATS['fr']}\n\n"
            f"=== OFFRE ===\n{offer_text[:5000]}\n\n=== CV DE BASE ===\n{cv_text[:6000]}"
        )
    raw, err = llm.complete(prompt, json_mode=False, max_tokens=1800, temperature=0.35)
    if err:
        return None, err
    return (raw or "").strip(), None


def offer_keywords(offer_text: str, lang: str = "fr") -> tuple:
    """Extrait les mots-clés ATS de l'offre, TOUS DOMAINES (pas seulement tech) :
    compétences, outils/logiciels, certifications, méthodes et termes métier EXACTS
    tels qu'écrits dans l'offre. Rend le signal ATS pertinent quel que soit le poste
    (marketing, finance, RH, santé, juridique, commerce…). Retourne (list, err) —
    fail-open : en cas d'erreur, l'appelant retombe sur la liste tech curée."""
    lg = _lang(lang)
    if lg == "en":
        prompt = (
            "Extract the ATS keywords a screening system would match for THIS job offer, "
            "whatever the field (marketing, finance, HR, healthcare, legal, sales, engineering, "
            "tech…). Return the concrete hard skills, tools/software, certifications, methods and "
            "exact domain terms AS WRITTEN in the offer — short noun phrases, no soft skills, no "
            'verbs. Return ONLY JSON: {"keywords": ["<term>", ...]} (max 25).\n\n'
            f"=== JOB OFFER ===\n{offer_text[:5000]}"
        )
    else:
        prompt = (
            "Extrais les mots-clés ATS qu'un logiciel de tri retiendrait pour CETTE offre, quel "
            "que soit le domaine (marketing, finance, RH, santé, juridique, commerce, ingénierie, "
            "tech…). Donne les compétences concrètes, outils/logiciels, certifications, méthodes et "
            "termes métier EXACTS tels qu'écrits dans l'offre — groupes nominaux courts, pas de "
            'soft skills, pas de verbes. Réponds UNIQUEMENT en JSON : {"keywords": ["<terme>", ...]} '
            "(max 25).\n\n"
            f"=== OFFRE ===\n{offer_text[:5000]}"
        )
    raw, err = llm.complete(prompt, json_mode=True, max_tokens=500)
    if err:
        return [], err
    data = llm.parse_json(raw)
    kws = data.get("keywords") if isinstance(data, dict) else None
    return ([str(k).strip() for k in kws if str(k).strip()] if isinstance(kws, list) else []), None


def cv_to_structured(cv_markdown: str, lang: str = "fr") -> tuple:
    """Structure le CV Markdown en JSON pour un rendu HTML mis en page (deux colonnes).
    Ne fait que RÉORGANISER le contenu existant — aucune invention. Retourne (dict, err)
    fail-open : en cas d'erreur, l'appelant retombe sur le rendu Markdown→HTML simple."""
    lg = _lang(lang)
    schema = (
        '{"name":"","role":"","contact":{"email":"","phone":"","linkedin":"","github":"",'
        '"portfolio":"","location":""},"summary":"",'
        '"experiences":[{"title":"","org":"","date":"","stack":"","bullets":[""]}],'
        '"projects":[{"title":"","meta":"","stack":"","bullets":[""]}],'
        '"education":[{"title":"","meta":""}],'
        '"skills":[{"group":"","items":[""]}],'
        '"certifications":[""],"languages":[""]}'
    )
    if lg == "en":
        prompt = (
            "Convert this Markdown CV into structured JSON for a designed HTML layout. "
            "ONLY reorganise the existing content — invent nothing, drop nothing important. "
            "Leave a field empty if absent. Keep bullets concise.\n"
            f"Return ONLY JSON matching this schema: {schema}\n\n=== CV (Markdown) ===\n{cv_markdown[:6000]}"
        )
    else:
        prompt = (
            "Convertis ce CV Markdown en JSON structuré pour une mise en page HTML soignée. "
            "RÉORGANISE uniquement le contenu existant — n'invente rien, ne supprime rien "
            "d'important. Laisse un champ vide s'il est absent. Puces concises.\n"
            f"Réponds UNIQUEMENT en JSON suivant ce schéma : {schema}\n\n=== CV (Markdown) ===\n{cv_markdown[:6000]}"
        )
    raw, err = llm.complete(prompt, json_mode=True, max_tokens=1800)
    if err:
        return None, err
    data = llm.parse_json(raw)
    if not isinstance(data, dict):
        return None, "Réponse LLM illisible"
    return data, None


def recommend(analysis: dict, ats_cov: dict, lang: str = "fr", memory_note: str = "") -> tuple:
    """Planification + décision go/no-go (#5). Combine le signal chiffré (fit_score,
    couverture ATS, écarts) et un raisonnement LLM pour recommander : postuler /
    renforcer d'abord / passer — avec un plan d'action ORDONNÉ et priorisé. Retourne
    (dict, err) avec dict = {decision, confidence, rationale, action_plan[]}."""
    lg = _lang(lang)
    fit = int((analysis or {}).get("fit_score", 0) or 0)
    pct = int((ats_cov or {}).get("pct", 0) or 0)
    gaps = "; ".join((analysis or {}).get("gaps", [])[:8]) or "—"
    missing = ", ".join((ats_cov or {}).get("missing", [])[:15]) or "—"
    mem = f"\nMémoire (candidatures passées) : {memory_note}" if memory_note else ""
    if lg == "en":
        prompt = (
            "You are a career coach. Decide whether the candidate should apply to this offer, "
            f"using: fit score {fit}/100, ATS coverage {pct}%, gaps ({gaps}), missing keywords "
            f"({missing}).{mem}\n"
            "decision ∈ {apply | strengthen_first | skip}. Give an ORDERED, concrete, prioritised "
            "action plan (what to do BEFORE applying to maximise the odds).\n"
            'Return ONLY JSON: {"decision":"<...>","confidence":<0-100>,'
            '"rationale":"<2 sentences>","action_plan":["<step 1>", ...]}'
        )
    else:
        prompt = (
            "Tu es coach carrière. Décide si le candidat doit postuler à cette offre, en "
            f"t'appuyant sur : score de fit {fit}/100, couverture ATS {pct}%, écarts ({gaps}), "
            f"mots-clés manquants ({missing}).{mem}\n"
            "decision ∈ {postuler | renforcer_puis_postuler | passer}. Donne un plan d'action "
            "ORDONNÉ, concret et priorisé (quoi faire AVANT de postuler pour maximiser les chances).\n"
            'Réponds UNIQUEMENT en JSON : {"decision":"<...>","confidence":<0-100>,'
            '"rationale":"<2 phrases>","action_plan":["<étape 1>", ...]}'
        )
    raw, err = llm.complete(prompt, json_mode=True, max_tokens=800)
    if err:
        return None, err
    data = llm.parse_json(raw)
    if not isinstance(data, dict):
        return None, "Réponse LLM illisible"
    data["decision"] = str(data.get("decision", "")).strip().lower()
    try:
        data["confidence"] = max(0, min(100, int(data.get("confidence", 0) or 0)))
    except (TypeError, ValueError):
        data["confidence"] = 0
    data["rationale"] = str(data.get("rationale", "")).strip()
    ap = data.get("action_plan")
    data["action_plan"] = [str(x).strip() for x in ap if str(x).strip()] if isinstance(ap, list) else []
    return data, None


# =============================================================================
# BOUCLE AGENTIQUE — generate → measure (ATS) → verify (anti-invention) → revise
# =============================================================================

def verify_grounding(text: str, cv_text: str, lang: str = "fr") -> tuple:
    """Vérificateur anti-invention (#3). Vérifie que chaque affirmation factuelle
    de `text` est ADOSSÉE au CV de base. Retourne ({"unsupported": [...]}, err).
    Fail-open : en cas d'erreur LLM, err est renvoyé et l'appelant n'échoue pas."""
    lg = _lang(lang)
    if lg == "en":
        prompt = (
            "You are a fact-checker. List the factual claims in DOCUMENT that are NOT "
            "supported by the candidate's BASE CV (invented experience, skills, figures, "
            "employers, dates). Ignore rephrasing/formatting. Return ONLY JSON: "
            '{"unsupported": ["<claim>", ...]}. Empty list if everything is grounded.\n\n'
            f"=== DOCUMENT ===\n{text[:6000]}\n\n=== BASE CV ===\n{cv_text[:6000]}"
        )
    else:
        prompt = (
            "Tu es fact-checker. Liste les affirmations factuelles du DOCUMENT qui NE sont "
            "PAS adossées au CV de base du candidat (expérience, compétence, chiffre, "
            "employeur ou date inventés). Ignore les reformulations/la mise en forme. Réponds "
            'UNIQUEMENT en JSON : {"unsupported": ["<affirmation>", ...]}. Liste vide si tout '
            "est fondé.\n\n"
            f"=== DOCUMENT ===\n{text[:6000]}\n\n=== CV DE BASE ===\n{cv_text[:6000]}"
        )
    raw, err = llm.complete(prompt, json_mode=True, max_tokens=700)
    if err:
        return None, err
    data = llm.parse_json(raw)
    unsup = data.get("unsupported") if isinstance(data, dict) else None
    return {"unsupported": [str(x).strip() for x in unsup if str(x).strip()] if isinstance(unsup, list) else []}, None


def _revise_cv(current: str, cv_text: str, offer_text: str, missing_keywords: list,
               unsupported: list, lang: str = "fr") -> tuple:
    """Réécrit le CV adapté pour (a) intégrer les mots-clés manquants que le candidat
    possède VRAIMENT, (b) retirer/corriger les affirmations non fondées."""
    lg = _lang(lang)
    miss = ", ".join(missing_keywords[:20]) or "—"
    bad = "\n".join(f"- {u}" for u in unsupported[:15]) or "—"
    if lg == "en":
        prompt = (
            "Improve this tailored CV. Two goals:\n"
            f"1) ATS: surface these offer keywords IF and ONLY IF the candidate genuinely has "
            f"them (per the base CV): {miss}\n"
            f"2) Integrity: REMOVE or correct these unsupported claims:\n{bad}\n"
            f"{_NO_FABRICATION['en']}\n{_ATS['en']}\n"
            "Return the full improved CV in clean Markdown, nothing else.\n\n"
            f"=== OFFER ===\n{offer_text[:4000]}\n\n=== BASE CV ===\n{cv_text[:5000]}\n\n"
            f"=== CURRENT TAILORED CV ===\n{current[:5000]}"
        )
    else:
        prompt = (
            "Améliore ce CV adapté. Deux objectifs :\n"
            f"1) ATS : fais ressortir ces mots-clés de l'offre SI ET SEULEMENT SI le candidat "
            f"les possède vraiment (selon le CV de base) : {miss}\n"
            f"2) Intégrité : RETIRE ou corrige ces affirmations non fondées :\n{bad}\n"
            f"{_NO_FABRICATION['fr']}\n{_ATS['fr']}\n"
            "Renvoie le CV amélioré complet en Markdown propre, rien d'autre.\n\n"
            f"=== OFFRE ===\n{offer_text[:4000]}\n\n=== CV DE BASE ===\n{cv_text[:5000]}\n\n"
            f"=== CV ADAPTÉ ACTUEL ===\n{current[:5000]}"
        )
    raw, err = llm.complete(prompt, json_mode=False, max_tokens=1800, temperature=0.3)
    if err:
        return None, err
    return (raw or "").strip(), None


def optimize_cv(cv_text: str, offer_text: str, lang: str = "fr",
                target: int = 80, max_iters: int = 2) -> tuple:
    """Boucle agentique (#1+#3) : génère un CV adapté puis, tant que la couverture
    ATS < `target` OU qu'il reste des affirmations non fondées, mesure → vérifie →
    révise. Objectif chiffré déterministe (ats.coverage). Garde la MEILLEURE version
    (0 invention prioritaire, puis meilleure couverture). Retourne (result, err) avec
    result = {cv_markdown, ats_start, ats_final, iterations[], unsupported_final[]}."""
    extra, _ = offer_keywords(offer_text, lang)             # mots-clés tous domaines (fail-open)
    keywords = ats.extract_keywords(offer_text, extra=extra)
    current, err = tailored_cv(cv_text, offer_text, lang)   # génération initiale
    if err:
        return None, err

    iterations = []
    best, best_key, ats_start = None, (-1, -1), None

    for i in range(max(1, max_iters) + 1):
        pct = ats.coverage(current, keywords)["pct"]
        grounding, gerr = verify_grounding(current, cv_text, lang)   # #3 (fail-open)
        unsupported = grounding["unsupported"] if grounding else []
        if ats_start is None:
            ats_start = pct
        iterations.append({"iter": i, "ats": pct, "unsupported": len(unsupported)})

        # Meilleure version : priorité à 0 invention, puis à la couverture ATS
        key = (1 if not unsupported else 0, pct)
        if key > best_key:
            best, best_key = current, key

        if pct >= target and not unsupported:      # objectif atteint
            break
        if i >= max_iters:                          # budget épuisé
            break

        missing = ats.coverage(current, keywords)["missing"]
        revised, rerr = _revise_cv(current, cv_text, offer_text, missing, unsupported, lang)
        if rerr or not revised:                     # révision indispo → on garde le meilleur
            break
        current = revised

    final_unsup, _ = verify_grounding(best, cv_text, lang)
    return {
        "cv_markdown": best,
        "ats_start": ats_start,
        "ats_final": ats.coverage(best, keywords)["pct"],
        "iterations": iterations,
        "unsupported_final": (final_unsup or {}).get("unsupported", []),
    }, None
