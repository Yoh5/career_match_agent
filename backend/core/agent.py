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
from core import llm, ats, quality

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
# Exigences de langue et de correction — la source des « erreurs de langue,
# d'orthographe et de placeholders » observées dans les documents générés.
_WRITING = {
    "fr": "QUALITÉ DE RÉDACTION (exigence stricte) :\n"
          "- Écris TOUT en français, sans une seule phrase ni tournure en anglais. Seuls les "
          "noms propres et les termes techniques consacrés (Python, Machine Learning, FastAPI) "
          "restent en anglais ; tout le reste — verbes, liaisons, descriptions — est en français.\n"
          "- Orthographe, grammaire, conjugaison et accords IRRÉPROCHABLES. Relis-toi : accords "
          "participe passé, pluriels, concordance des temps, genre des noms.\n"
          "- Typographie française : espace avant « : ; ! ? », apostrophes typographiques (') "
          "de façon cohérente, pas de double espace, pas d'espace avant une virgule.\n"
          "- AUCUN champ à trous : jamais de [Nom], [Entreprise], XXX, « à compléter ». Si une "
          "information manque, reformule la phrase pour t'en passer.\n"
          "- Rends UNIQUEMENT le document final : aucune phrase d'introduction du type « Voici… », "
          "aucun commentaire, aucun bloc de code ```.",
    "en": "WRITING QUALITY (strict requirement):\n"
          "- Write EVERYTHING in English — not a single sentence or phrase in another language.\n"
          "- Flawless spelling, grammar, tenses and agreement. Proofread yourself.\n"
          "- Clean typography: no double spaces, no space before a comma or period, "
          "consistent apostrophes.\n"
          "- NO placeholders whatsoever: never [Name], [Company], XXX, 'to be completed'. "
          "If a detail is missing, rephrase the sentence so it is not needed.\n"
          "- Output ONLY the final document: no introductory sentence such as 'Here is…', "
          "no commentary, no ``` code fence.",
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
            f"{_NO_FABRICATION['en']}\n{_ATS['en']}\n{_WRITING['en']}\n{style}\n"
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
            f"{_NO_FABRICATION['fr']}\n{_ATS['fr']}\n{_WRITING['fr']}\n{style}\n"
            f"=== OFFRE ===\n{offer_text[:5000]}\n\n=== CV ===\n{cv_text[:5000]}"
        )
    raw, err = llm.complete(prompt, json_mode=False, max_tokens=900, temperature=0.5)
    if err:
        return None, err
    return quality.normalize(raw, lg), None      # nettoyage mécanique sûr


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
            f"{_NO_FABRICATION['en']}\n{_ATS['en']}\n{_WRITING['en']}\n\n"
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
            "Les intitulés de section et TOUTES les descriptions sont en français ; garde les "
            "noms d'entreprise, d'école et les technologies tels quels.\n"
            f"{_NO_FABRICATION['fr']}\n{_ATS['fr']}\n{_WRITING['fr']}\n\n"
            f"=== OFFRE ===\n{offer_text[:5000]}\n\n=== CV DE BASE ===\n{cv_text[:6000]}"
        )
    raw, err = llm.complete(prompt, json_mode=False, max_tokens=1800, temperature=0.35)
    if err:
        return None, err
    return quality.normalize(raw, lg), None


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


def proofread(text: str, lang: str = "fr", kind: str = "letter", issues_found: list = None) -> tuple:
    """Relecture FINALE : corrige orthographe, grammaire, conjugaison, accords,
    typographie et traduit les passages restés dans la mauvaise langue — SANS
    toucher aux faits ni à la structure. Retourne (texte, err) ; fail-open.

    `issues_found` = problèmes repérés par `quality.issues()` : les signaler
    explicitement rend la correction bien plus fiable qu'une demande générique."""
    lg = _lang(lang)
    txt = (text or "").strip()
    if not txt:
        return txt, None
    listed = ""
    if issues_found:
        bullets = "\n".join(f"- {i.get('detail', i.get('type'))}" for i in issues_found[:10])
        listed = (f"\nProblèmes détectés automatiquement — corrige-les tous :\n{bullets}\n"
                  if lg == "fr" else
                  f"\nAutomatically detected problems — fix every one of them:\n{bullets}\n")
    doc = "CV" if kind == "cv" else ("lettre de motivation" if lg == "fr" else "cover letter")
    if lg == "en":
        prompt = (
            f"Proofread this {doc}. Fix every spelling, grammar, tense, agreement and "
            "typography mistake, and rewrite in English any passage left in another language. "
            "Keep the EXACT same facts, structure, sections and formatting — change nothing "
            "but the language quality. Remove any leftover placeholder by rephrasing.\n"
            f"{listed}"
            "Return ONLY the corrected document, with no preamble and no code fence.\n\n"
            f"=== DOCUMENT ===\n{txt[:7000]}"
        )
    else:
        prompt = (
            f"Relis et corrige {'ce' if kind == 'cv' else 'cette'} {doc}. Corrige TOUTES les "
            "fautes d'orthographe, de grammaire, de conjugaison, d'accord et de typographie, et "
            "réécris en français tout passage resté dans une autre langue.\n"
            "Conserve EXACTEMENT les mêmes faits, la même structure, les mêmes sections et la "
            "même mise en forme — ne change QUE la qualité de langue. Supprime tout champ à "
            "trous restant en reformulant la phrase.\n"
            f"{listed}"
            "Renvoie UNIQUEMENT le document corrigé, sans préambule ni bloc de code.\n\n"
            f"=== DOCUMENT ===\n{txt[:7000]}"
        )
    raw, err = llm.complete(prompt, json_mode=False, max_tokens=2000, temperature=0.1)
    if err:
        return None, err
    return quality.normalize(raw, lg), None


def _polish(text: str, cv_text: str, lang: str, kind: str, target: int = 92) -> tuple:
    """Passe de finition partagée par les boucles : mesure la qualité rédactionnelle
    et, si elle est insuffisante, fait relire le document — en ne gardant la version
    relue QUE si elle est réellement meilleure ET toujours fondée sur le CV.

    Retourne (texte_final, rapport_qualité, unsupported) où `unsupported` est le
    résultat de la vérification faite ici (None si aucune n'a eu lieu) : l'appelant
    le réutilise au lieu de relancer un contrôle d'intégrité identique."""
    q = quality.score(text, lang, kind)
    if q["score"] >= target:
        return text, q, None
    fixed, err = proofread(text, lang, kind, q["issues"])
    if err or not fixed:
        return text, q, None                            # fail-open : on garde l'original
    q2 = quality.score(fixed, lang, kind)
    if q2["score"] <= q["score"]:
        return text, q, None                            # la relecture n'a rien apporté
    if cv_text:                                         # la relecture ne doit rien inventer
        g, gerr = verify_grounding(fixed, cv_text, lang)
        if gerr:
            return fixed, q2, None
        if g and g["unsupported"]:
            return text, q, None                        # relecture écartée : elle invente
        return fixed, q2, []                            # relue, propre et vérifiée
    return fixed, q2, None


# =============================================================================
# BOUCLES AGENTIQUES — generate → measure → verify → revise → polish
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
               unsupported: list, lang: str = "fr", writing_issues: list = None) -> tuple:
    """Réécrit le CV adapté pour (a) intégrer les mots-clés manquants que le candidat
    possède VRAIMENT, (b) retirer/corriger les affirmations non fondées, (c) corriger
    les défauts de rédaction détectés (langue, fautes, champs à trous)."""
    lg = _lang(lang)
    miss = ", ".join(missing_keywords[:20]) or "—"
    bad = "\n".join(f"- {u}" for u in unsupported[:15]) or "—"
    wr = "\n".join(f"- {i.get('detail', i.get('type'))}" for i in (writing_issues or [])[:8]) or "—"
    if lg == "en":
        prompt = (
            "Improve this tailored CV. Three goals:\n"
            f"1) ATS: surface these offer keywords IF and ONLY IF the candidate genuinely has "
            f"them (per the base CV): {miss}\n"
            f"2) Integrity: REMOVE or correct these unsupported claims:\n{bad}\n"
            f"3) Writing: fix these detected problems:\n{wr}\n"
            f"{_NO_FABRICATION['en']}\n{_ATS['en']}\n{_WRITING['en']}\n"
            "Return the full improved CV in clean Markdown, nothing else.\n\n"
            f"=== OFFER ===\n{offer_text[:4000]}\n\n=== BASE CV ===\n{cv_text[:5000]}\n\n"
            f"=== CURRENT TAILORED CV ===\n{current[:5000]}"
        )
    else:
        prompt = (
            "Améliore ce CV adapté. Trois objectifs :\n"
            f"1) ATS : fais ressortir ces mots-clés de l'offre SI ET SEULEMENT SI le candidat "
            f"les possède vraiment (selon le CV de base) : {miss}\n"
            f"2) Intégrité : RETIRE ou corrige ces affirmations non fondées :\n{bad}\n"
            f"3) Rédaction : corrige ces problèmes détectés :\n{wr}\n"
            f"{_NO_FABRICATION['fr']}\n{_ATS['fr']}\n{_WRITING['fr']}\n"
            "Renvoie le CV amélioré complet en Markdown propre, rien d'autre.\n\n"
            f"=== OFFRE ===\n{offer_text[:4000]}\n\n=== CV DE BASE ===\n{cv_text[:5000]}\n\n"
            f"=== CV ADAPTÉ ACTUEL ===\n{current[:5000]}"
        )
    raw, err = llm.complete(prompt, json_mode=False, max_tokens=1800, temperature=0.3)
    if err:
        return None, err
    return quality.normalize(raw, lg), None


def _fingerprint(text: str) -> str:
    """Empreinte insensible aux espaces — sert à détecter qu'une révision n'a rien
    changé (convergence) et à éviter un tour de boucle inutile."""
    return " ".join((text or "").split()).lower()


def _cv_key(unsupported: list, ats_pct: int, q_score: int) -> tuple:
    """Ordre de préférence entre versions : intégrité d'abord (non négociable),
    puis un score composite pertinence/qualité (70/30) — une version un peu moins
    dense en mots-clés mais bien écrite doit pouvoir gagner."""
    return (0 if unsupported else 1, round(0.7 * ats_pct + 0.3 * q_score))


def optimize_cv(cv_text: str, offer_text: str, lang: str = "fr",
                target: int = 80, max_iters: int = 2, quality_target: int = 92) -> tuple:
    """Boucle agentique : génère → mesure (ATS + qualité rédactionnelle, tous deux
    déterministes) → vérifie l'intégrité → révise, en gardant la MEILLEURE version
    (intégrité d'abord, puis composite 70 % ATS / 30 % qualité), puis relit.

    Optimisations : une seule mesure ATS par tour (le dict porte pct ET missing),
    grounding mémorisé par version (plus de re-vérification finale), arrêt sur
    convergence, et reprise depuis la meilleure version si une révision régresse.

    Retourne (result, err) — result = {cv_markdown, ats_start, ats_final,
    iterations[], unsupported_final[], quality_start, quality_final, quality_issues[]}."""
    lg = _lang(lang)
    extra, _ = offer_keywords(offer_text, lang)             # mots-clés tous domaines (fail-open)
    keywords = ats.extract_keywords(offer_text, extra=extra)
    current, err = tailored_cv(cv_text, offer_text, lang)   # génération initiale
    if err:
        return None, err

    iterations = []
    best = best_key = best_unsup = None
    ats_start = q_start = None
    seen = set()

    for i in range(max(1, max_iters) + 1):
        cov = ats.coverage(current, keywords, offer_text)   # UNE mesure : pct, pondéré, manquants
        pct = cov["pct"]
        q = quality.score(current, lg, "cv")                # qualité déterministe
        grounding, _gerr = verify_grounding(current, cv_text, lang)   # fail-open
        unsupported = grounding["unsupported"] if grounding else []

        if ats_start is None:
            ats_start, q_start = pct, q["score"]
        iterations.append({"iter": i, "ats": pct, "ats_weighted": cov["weighted_pct"],
                           "quality": q["score"], "unsupported": len(unsupported)})

        key = _cv_key(unsupported, pct, q["score"])
        if best_key is None or key > best_key:
            best, best_key, best_unsup = current, key, unsupported

        if pct >= target and q["score"] >= quality_target and not unsupported:
            break                                           # tous les objectifs atteints
        if i >= max_iters:
            break                                           # budget épuisé

        # Les manquants ÉLIMINATOIRES d'abord : la liste est tronquée à 20 dans le
        # prompt, autant que ce soit par ce qui fait recaler et pas par un bonus.
        missing = cov["critical_missing"] + [k for k in cov["missing"] if k not in cov["critical_missing"]]
        revised, rerr = _revise_cv(current, cv_text, offer_text, missing,
                                   unsupported, lang, q["issues"])
        if rerr or not revised:
            break                                           # révision indispo → on garde le meilleur
        fp = _fingerprint(revised)
        if fp in seen or fp == _fingerprint(current):
            break                                           # convergence : rien de nouveau
        seen.add(fp)
        current = revised

    # Finition : relecture ciblée, conservée uniquement si elle améliore vraiment.
    # `polished_unsup` évite de revérifier l'intégrité déjà contrôlée dans _polish.
    final, q_final, polished_unsup = _polish(best, cv_text, lg, "cv", quality_target)
    if polished_unsup is not None:
        best_unsup = polished_unsup
    cov_final = ats.coverage(final, keywords, offer_text)
    return {
        "cv_markdown": final,
        "ats_start": ats_start,
        "ats_final": cov_final["pct"],
        "ats_weighted_final": cov_final["weighted_pct"],
        "critical_missing": cov_final["critical_missing"],
        "keywords": keywords,               # réutilisés pour l'audit de parsing du PDF
        "iterations": iterations,
        "unsupported_final": best_unsup or [],
        "quality_start": q_start,
        "quality_final": q_final["score"],
        "quality_issues": q_final["issues"],
    }, None


def optimize_cover_letter(cv_text: str, offer_text: str, lang: str = "fr",
                          tone: str = "professionnel", style_notes: str = "",
                          max_iters: int = 1, quality_target: int = 92) -> tuple:
    """Boucle agentique pour la LETTRE (elle était générée en un seul coup, sans
    aucun contrôle) : génère → mesure la qualité rédactionnelle (déterministe) →
    vérifie l'anti-invention → révise → relit. Garde la meilleure version.

    Retourne (result, err) — result = {cover_letter, quality_start, quality_final,
    quality_issues[], iterations[], unsupported_final[]}."""
    lg = _lang(lang)
    current, err = cover_letter(cv_text, offer_text, lang, tone, style_notes)
    if err:
        return None, err

    iterations = []
    best = best_key = best_unsup = None
    q_start = None

    for i in range(max(1, max_iters) + 1):
        q = quality.score(current, lg, "letter")
        grounding, _gerr = verify_grounding(current, cv_text, lang)
        unsupported = grounding["unsupported"] if grounding else []
        if q_start is None:
            q_start = q["score"]
        iterations.append({"iter": i, "quality": q["score"], "unsupported": len(unsupported)})

        key = (0 if unsupported else 1, q["score"])
        if best_key is None or key > best_key:
            best, best_key, best_unsup = current, key, unsupported

        if q["score"] >= quality_target and not unsupported:
            break
        if i >= max_iters:
            break

        revised, rerr = _revise_letter(current, cv_text, offer_text, unsupported,
                                       q["issues"], lang, tone, style_notes)
        if rerr or not revised or _fingerprint(revised) == _fingerprint(current):
            break
        current = revised

    final, q_final, polished_unsup = _polish(best, cv_text, lg, "letter", quality_target)
    if polished_unsup is not None:
        best_unsup = polished_unsup
    return {
        "cover_letter": final,
        "quality_start": q_start,
        "quality_final": q_final["score"],
        "quality_issues": q_final["issues"],
        "iterations": iterations,
        "unsupported_final": best_unsup or [],
    }, None


def _revise_letter(current: str, cv_text: str, offer_text: str, unsupported: list,
                   writing_issues: list, lang: str = "fr", tone: str = "professionnel",
                   style_notes: str = "") -> tuple:
    """Réécrit la lettre pour retirer les affirmations non fondées et corriger les
    défauts de rédaction détectés, à consignes de style constantes."""
    lg = _lang(lang)
    bad = "\n".join(f"- {u}" for u in (unsupported or [])[:12]) or "—"
    wr = "\n".join(f"- {i.get('detail', i.get('type'))}" for i in (writing_issues or [])[:10]) or "—"
    style = (style_notes or "").strip()[:1200]
    if lg == "en":
        extra = f"\nCandidate's style instructions (form only):\n{style}\n" if style else ""
        prompt = (
            "Rewrite this cover letter to fix two things, keeping the same structure, tone "
            f"({tone}) and length:\n"
            f"1) Integrity — REMOVE or correct these unsupported claims:\n{bad}\n"
            f"2) Writing — fix these detected problems:\n{wr}\n"
            f"{_NO_FABRICATION['en']}\n{_WRITING['en']}{extra}\n"
            f"=== OFFER ===\n{offer_text[:3500]}\n\n=== BASE CV ===\n{cv_text[:4000]}\n\n"
            f"=== CURRENT LETTER ===\n{current[:4000]}"
        )
    else:
        extra = f"\nConsignes de style du candidat (forme uniquement) :\n{style}\n" if style else ""
        prompt = (
            "Réécris cette lettre de motivation pour corriger deux choses, en gardant la même "
            f"structure, le même ton ({tone}) et la même longueur :\n"
            f"1) Intégrité — RETIRE ou corrige ces affirmations non fondées :\n{bad}\n"
            f"2) Rédaction — corrige ces problèmes détectés :\n{wr}\n"
            f"{_NO_FABRICATION['fr']}\n{_WRITING['fr']}{extra}\n"
            f"=== OFFRE ===\n{offer_text[:3500]}\n\n=== CV DE BASE ===\n{cv_text[:4000]}\n\n"
            f"=== LETTRE ACTUELLE ===\n{current[:4000]}"
        )
    raw, err = llm.complete(prompt, json_mode=False, max_tokens=1100, temperature=0.25)
    if err:
        return None, err
    return quality.normalize(raw, lg), None
