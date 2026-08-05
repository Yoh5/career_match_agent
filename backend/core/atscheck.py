# -*- coding: utf-8 -*-
"""Audit de parsing ATS : ce que le robot lit VRAIMENT dans le PDF envoyé.

Le maillon manquant de la chaîne. `ats.py` mesure la couverture de mots-clés sur
le **Markdown** produit par l'agent — mais ce n'est pas ce fichier-là qu'on
dépose sur le portail de candidature : on y dépose un **PDF**. Entre les deux, la
mise en page peut détruire le texte : deux colonnes entrelacées, CV scanné en
image, caractères mutilés, coordonnées collées à un titre. Un CV noté 92 % ATS
peut arriver illisible chez le recruteur, et personne ne le sait.

Ce module ferme la boucle : il **ré-extrait le PDF comme le font les ATS** puis
mesure ce qui a survécu.

**Deux extracteurs, pas un.** Un ATS est une boîte noire : on ignore quel
parseur tourne derrière le portail. Or ils ne se valent pas — sur un même PDF
Canva, `pypdf` peut rendre « P y t h o n » (une lettre par mot, zéro mot-clé
matché) là où `pdfminer.six` reconstruit correctement les mots. Le rapport
mesure donc chaque extracteur disponible et **retient le PIRE** : on ne
recommande pas un CV en pariant sur le parseur d'en face. `pdfminer.six` est
optionnel — absent, l'audit tourne sur `pypdf` seul et le signale.

Ce qui est mesuré :

  - le texte est-il extractible du tout (CV « image » = score 0, cas classique) ;
  - est-il **découpé lettre par lettre** — pathologie des exports Canva/Figma,
    où chaque glyphe est positionné individuellement : le texte s'affiche
    parfaitement à l'écran et ne matche AUCUN mot-clé ;
  - **quels mots-clés se perdent entre le Markdown et le PDF** — le signal le
    plus important, celui qui condamne une mise en page ;
  - e-mail et téléphone retrouvables par les regex que tout ATS applique ;
  - sections standard identifiables (expérience / formation / compétences) ;
  - dates d'expérience lisibles ;
  - caractères mutilés, mots recollés, en-têtes noyés dans une ligne de corps
    (signature d'une extraction en colonnes), nombre de pages.

100 % déterministe, aucun appel LLM, aucun réseau : c'est une mesure, pas un avis.
"""
import io
import re
from typing import Dict, List, Optional

from core import ats

SEVERITY_PENALTY = {"critical": 25, "high": 12, "medium": 5, "low": 2}

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Numéro international ou local, séparateurs libres — la regex large des ATS.
_PHONE = re.compile(r"(?:\+\d{1,3}[\s.\-]?)?(?:\(?\d{1,4}\)?[\s.\-]?){2,5}\d{2,4}")
_LINK = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin\.com|github\.com)/\S+", re.IGNORECASE)
# « AHOaho.axel5@… » : nom en capitales recollé à l'adresse par l'extraction.
_GLUED_EMAIL = re.compile(r"^[A-ZÀ-Ý]{2,}[a-zà-ÿ]")
_DATE = re.compile(r"(?:19|20)\d{2}")

# Vocabulaire des sections qu'un parseur cherche pour découper le CV (FR + EN).
_SECTIONS = {
    "experience": ("experience professionnelle", "experiences professionnelles", "experience",
                   "experiences", "parcours professionnel", "work experience",
                   "professional experience", "employment"),
    "education": ("formation", "formations", "education", "diplomes", "academic background",
                  "parcours academique"),
    "skills": ("competences", "competences techniques", "skills", "technical skills",
               "core competencies"),
}
_OPTIONAL_SECTIONS = {
    "summary": ("profil", "profile", "summary", "professional summary", "a propos", "about"),
    "projects": ("projets", "projects", "portfolio"),
}

# Caractères qui ne survivent pas à une chaîne d'export (emoji, pictos, puces exotiques).
_EXOTIC = re.compile(r"[�•▪●✓✔★☆\U0001F300-\U0001FAFF]")
# « co?t », « ma?trise » : une substitution latin-1 ratée au milieu d'un mot.
_MANGLED = re.compile(r"[A-Za-zÀ-ÿ]\?[A-Za-zÀ-ÿ]")
_TOKEN = re.compile(r"\S+")


def extract_pdf_text(data: bytes) -> tuple:
    """(texte, err) — ré-extraction avec pypdf, le moteur déjà utilisé par
    `extract.py` pour lire les CV entrants. Ne lève jamais."""
    try:
        from pypdf import PdfReader
    except ImportError:                                   # pragma: no cover - repli
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return "", "pypdf indisponible"
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
        return "\n".join(pages).strip(), None
    except Exception as e:
        return "", f"PDF illisible ({e})"


def extract_pdf_text_miner(data: bytes) -> tuple:
    """(texte, err) — seconde lecture avec pdfminer.six, dont les heuristiques
    d'espacement diffèrent de celles de pypdf. Optionnel : renvoie une erreur
    claire si la dépendance est absente (l'audit continue sur pypdf seul)."""
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        return "", "pdfminer.six non installé"
    try:
        return (extract_text(io.BytesIO(data)) or "").strip(), None
    except Exception as e:
        return "", f"PDF illisible ({e})"


ENGINES = (("pypdf", extract_pdf_text), ("pdfminer", extract_pdf_text_miner))


def _norm(s: str) -> str:
    return ats.fold(s)


def _sections_found(text: str) -> Dict[str, List[str]]:
    """Sections standard détectées / absentes, en ne regardant que les LIGNES
    courtes (un intitulé de section, pas une phrase qui contient le mot)."""
    heads = [_norm(l).strip(" :·-—|") for l in (text or "").splitlines()
             if l.strip() and len(l.strip()) <= 60]
    found, missing = [], []
    for key, variants in _SECTIONS.items():
        if any(h in variants or any(h.startswith(v) for v in variants) for h in heads):
            found.append(key)
        else:
            missing.append(key)
    optional = [k for k, variants in _OPTIONAL_SECTIONS.items()
                if any(h in variants or any(h.startswith(v) for v in variants) for h in heads)]
    return {"found": found, "missing": missing, "optional": optional}


def _heading_mid_line(text: str) -> int:
    """Intitulés de section noyés au MILIEU d'une ligne de corps de texte.

    Signature classique d'une extraction en colonnes : le parseur recolle la barre
    latérale au texte principal et produit « ...déployé en production COMPÉTENCES
    Python, SQL ». Un CV une colonne ne produit jamais ça."""
    variants = [v for group in list(_SECTIONS.values()) + list(_OPTIONAL_SECTIONS.values())
                for v in group if len(v) >= 6]
    hits = 0
    for line in (text or "").splitlines():
        n = _norm(line)
        if len(n) < 45:                    # trop court pour être une ligne de corps
            continue
        for v in variants:
            m = re.search(r"(?<![a-z])" + re.escape(v) + r"(?![a-z])", n)
            if m and m.start() > 25:       # l'intitulé commence loin du début de ligne
                hits += 1
                break
    return hits


def _glued_tokens(text: str) -> List[str]:
    """Mots anormalement longs = espaces perdus à l'extraction (« PythonFastAPIDocker »).
    Les URLs et e-mails sont exclus : ils sont légitimement longs."""
    out = []
    for tok in _TOKEN.findall(text or ""):
        t = tok.strip(".,;:()[]")
        if len(t) > 28 and not _LINK.search(t) and "@" not in t and "/" not in t:
            out.append(t[:40])
    return out[:5]


# « parLaravel », « reportingConfiguration » : deux mots recollés en fin de ligne.
# Le préfixe minuscule d'au moins 3 lettres protège les marques en CamelCase
# (FastAPI, GitHub, LangGraph, JavaScript commencent par une majuscule).
_GLUED_CASE = re.compile(r"\b[a-zà-ÿ]{3,}[A-ZÀ-Ý][a-zà-ÿ]{3,}")


def char_spacing_ratio(text: str) -> float:
    """Part de jetons d'UNE seule lettre — détecte le texte éclaté « P y t h o n ».

    Pathologie des PDF où chaque glyphe est positionné individuellement (exports
    Canva/Figma) : à l'écran le mot est parfait, à l'extraction c'est une suite
    de lettres isolées, et plus aucun mot-clé ne matche. Un texte normal reste
    sous ~0.1 (les « a », « à », « l » isolés)."""
    toks = [t for t in re.findall(r"[A-Za-zÀ-ÿ0-9']+", text or "")]
    if len(toks) < 40:
        return 0.0
    singles = sum(1 for t in toks if len(t) == 1)
    return singles / len(toks)


def _audit_text(text: str, pages: int, keywords: Optional[List[str]] = None,
                source_text: str = "", offer_text: str = "") -> Dict:
    """Audite UNE extraction (le texte tel qu'un parseur donné l'a lu).
    Toute la logique de contrôle vit ici ; `audit()` l'applique à chaque moteur."""
    issues: List[Dict] = []

    def add(kind, severity, detail, count=1):
        issues.append({"type": kind, "severity": severity, "detail": detail, "count": count})

    words = len(re.findall(r"[A-Za-zÀ-ÿ0-9']+", text))

    # 1. Texte extractible — le CV « image » est le cas le plus fatal et le plus fréquent.
    #    Rédhibitoire : inutile de compter des demi-points sur un CV que le robot ne lit pas,
    #    et les contrôles suivants n'auraient de toute façon rien à analyser.
    if len(text.strip()) < 80:
        add("not_extractable", "critical",
            "quasi aucun texte extractible : PDF scanné, exporté en image ou en "
            "contours — l'ATS ne lira RIEN")
        return {"score": 0, "issues": issues, "text": text, "pages": pages, "words": words,
                "char_spacing": 0.0, "contact": {"email": "", "phone": "", "links": []},
                "sections": {"found": [], "missing": list(_SECTIONS), "optional": []},
                "ats_pct": 0 if keywords else None, "ats_pct_source": None,
                "keyword_loss": [], "glued": [], "mangled": 0}

    # 2. Texte éclaté lettre par lettre : le CV s'affiche bien, ne matche rien.
    spacing = char_spacing_ratio(text)
    if spacing >= 0.35:
        add("char_spacing", "critical",
            f"{round(100 * spacing)}% du texte ressort en lettres isolées "
            "(« P y t h o n ») : aucun mot-clé n'est matchable")
    elif spacing >= 0.18:
        add("char_spacing", "high",
            f"{round(100 * spacing)}% de lettres isolées : une partie des mots-clés ne matchera pas")
    elif words < 60:
        add("too_little_text", "critical",
            f"seulement {words} mots extraits : l'essentiel du CV ne ressort pas du PDF")
    elif words < 150:
        add("too_little_text", "high",
            f"seulement {words} mots extraits : une partie du CV n'est pas lisible par le parseur")

    # 3. Perte de mots-clés entre la source et le PDF : la mise en page a mangé du contenu.
    kws = [k for k in (keywords or []) if str(k).strip()]
    ats_pct = ats_src = None
    loss: List[str] = []
    if kws:
        cov = ats.coverage(text, kws, offer_text)
        ats_pct = cov["pct"]
        if source_text:
            cov_src = ats.coverage(source_text, kws, offer_text)
            ats_src = cov_src["pct"]
            loss = [k for k in cov_src["matched"] if k not in cov["matched"]]
            if loss:
                add("keyword_loss", "critical",
                    "mots-clés présents dans le CV mais PERDUS à l'extraction du PDF : "
                    + ", ".join(loss[:8]), len(loss))
    elif source_text:
        # Sans offre, on compare quand même la matière : le PDF doit restituer
        # l'essentiel du texte source.
        src_words = len(re.findall(r"[A-Za-zÀ-ÿ0-9']+", source_text))
        if src_words and words < 0.7 * src_words:
            add("content_loss", "high",
                f"{round(100 * (1 - words / src_words))}% du texte source ne ressort pas du PDF",
                src_words - words)

    # 4. Coordonnées : un ATS crée la fiche candidat à partir de ces regex.
    email = _EMAIL.search(text)
    phones = [p for p in _PHONE.findall(text) if len(re.sub(r"\D", "", p)) >= 8]
    links = _LINK.findall(text)
    if not email:
        add("no_email", "critical", "aucune adresse e-mail détectable — fiche candidat incréable")
    else:
        # L'adresse est là, mais soudée au texte qui précède : l'ATS enregistre
        # « AxelAHOaho.axel5@gmail.com » et le mail de convocation part dans le vide.
        # Deux signatures : un caractère collé juste avant le match, ou un début de
        # partie locale en CAPITALES suivi de minuscules (« AHOaho… ») — un nom
        # recollé. Une adresse écrite « Axel.Aho@ » ne déclenche pas (une seule capitale).
        before = text[max(0, email.start() - 1):email.start()]
        local = email.group(0).split("@")[0]
        if re.match(r"[A-Za-zÀ-ÿ]", before) or _GLUED_EMAIL.match(local):
            add("glued_contact", "high",
                f"l'e-mail ressort collé au texte qui précède (« {email.group(0)[:40]} ») : "
                "l'ATS enregistrera une adresse fausse")
        # Bloc de contact enterré au milieu du document : le parseur cherche le
        # candidat dans les premières lignes, pas au tiers du CV.
        if len(text) > 400 and email.start() > 0.25 * len(text):
            add("contact_buried", "high",
                f"coordonnées trouvées à {round(100 * email.start() / len(text))}% du document "
                "au lieu de l'en-tête : l'ordre de lecture est désordonné")
    if not phones:
        add("no_phone", "high", "aucun numéro de téléphone détectable")

    # 5. Sections standard.
    sec = _sections_found(text)
    if len(sec["missing"]) >= 2:
        add("missing_sections", "high",
            "sections standard non identifiées : " + ", ".join(sec["missing"]))
    elif sec["missing"]:
        add("missing_sections", "medium",
            "section standard non identifiée : " + ", ".join(sec["missing"]))

    # 6. Dates : sans elles, l'ATS ne peut pas calculer l'ancienneté.
    if len(_DATE.findall(text)) < 2:
        add("no_dates", "medium", "moins de deux dates (AAAA) lisibles : ancienneté incalculable")

    # 7. Entrelacement de colonnes.
    mid = _heading_mid_line(text)
    if mid:
        add("column_interleave", "high",
            f"{mid} intitulé(s) de section retrouvé(s) au milieu d'une ligne : "
            "l'extraction mélange les colonnes", mid)

    # 8. Caractères mutilés / exotiques.
    mangled = len(_MANGLED.findall(text))
    if mangled:
        add("mangled_chars", "medium",
            f"{mangled} caractère(s) accentué(s) transformé(s) en « ? » à l'export", mangled)
    exotic = len(_EXOTIC.findall(text))
    if exotic > 3:
        add("exotic_glyphs", "low",
            f"{exotic} pictogrammes/puces exotiques : certains parseurs les rendent en déchets",
            exotic)

    # 9. Mots recollés (espace perdue en fin de ligne ou entre colonnes).
    glued = _glued_tokens(text)
    cased = _GLUED_CASE.findall(text)
    if glued:
        add("glued_words", "medium", "mots recollés à l'extraction : " + ", ".join(glued), len(glued))
    if len(cased) >= 3:
        add("glued_lines", "medium",
            "mots collés d'une ligne à l'autre : " + ", ".join(cased[:5]), len(cased))

    # 10. Longueur.
    if pages > 2:
        add("too_many_pages", "low", f"{pages} pages — au-delà de 2, une partie n'est plus lue")

    penalty = sum(SEVERITY_PENALTY.get(i["severity"], 1) * min(3.0, max(1, i.get("count", 1)) ** 0.5)
                  for i in issues)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    issues.sort(key=lambda i: (order.get(i["severity"], 9), -i.get("count", 1)))

    return {
        "score": max(0, round(100 - penalty)),
        "issues": issues,
        "text": text,
        "pages": pages,
        "words": words,
        "char_spacing": round(spacing, 3),
        "contact": {"email": email.group(0) if email else "",
                    "phone": phones[0].strip() if phones else "",
                    "links": links[:5]},
        "sections": sec,
        "ats_pct": ats_pct,
        "ats_pct_source": ats_src,
        "keyword_loss": loss,
        "glued": glued,
        "mangled": mangled,
    }


def _page_count(pdf_bytes: bytes) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        return 0


def repair_char_spacing(text: str) -> tuple:
    """Recolle un texte extrait lettre par lettre. Retourne (texte, réparé?).

    Dans ces PDF, l'extracteur sépare les glyphes par UNE espace et les mots par
    DEUX : « D é v e l o p p e m e n t  d ’ u n ». On protège donc les doubles
    espaces, on supprime les simples, puis on restaure. Le seuil (35 % de lettres
    isolées) évite d'appliquer la transformation à un texte sain — sur un CV
    normal, elle collerait tout.

    Sans ça, un CV Canva déposé ici arrive au LLM en bouillie et TOUT le reste de
    la chaîne (analyse, mots-clés, CV adapté) travaille sur du bruit."""
    if char_spacing_ratio(text) < 0.35:
        return text, False
    out = []
    for line in (text or "").splitlines():
        tmp = re.sub(r" {2,}", "\x00", line)          # séparation de mots à préserver
        tmp = tmp.replace(" ", "")                     # espaces inter-glyphes
        out.append(tmp.replace("\x00", " ").strip())
    return "\n".join(out).strip(), True


def audit(pdf_bytes: bytes, keywords: Optional[List[str]] = None, source_text: str = "",
          offer_text: str = "") -> Dict:
    """Rapport de parsing ATS d'un PDF, mesuré sur TOUS les extracteurs disponibles
    et arbitré sur le **pire** — parce qu'on ne choisit pas le parseur d'en face.

    Retourne ``{score, issues[], text, pages, words, char_spacing, contact{},
    sections{}, ats_pct, ats_pct_source, keyword_loss[], glued[], mangled,
    engines{}, engine}``.

    - `keywords` — mots-clés de l'offre : la couverture est alors mesurée sur le
      texte **ré-extrait**, le seul chiffre qui décrit ce que le robot voit.
    - `source_text` — le Markdown/texte d'origine : permet de calculer la PERTE
      due à la mise en page (`keyword_loss`), le diagnostic le plus actionnable.
    """
    pages = _page_count(pdf_bytes)
    reports, errors = {}, {}
    for name, fn in ENGINES:
        text, err = fn(pdf_bytes)
        if err:
            errors[name] = err
            continue
        reports[name] = _audit_text(text, pages, keywords, source_text, offer_text)

    if not reports:                                  # aucun moteur n'a pu lire le PDF
        detail = " ; ".join(f"{k} : {v}" for k, v in errors.items()) or "aucun extracteur disponible"
        return {"score": 0, "pages": pages, "words": 0, "char_spacing": 0.0, "text": "",
                "issues": [{"type": "unreadable_pdf", "severity": "critical",
                            "detail": detail, "count": 1}],
                "contact": {}, "sections": {"found": [], "missing": list(_SECTIONS), "optional": []},
                "ats_pct": None, "ats_pct_source": None, "keyword_loss": [], "glued": [],
                "mangled": 0, "engines": {}, "engine": None}

    worst = min(reports, key=lambda k: reports[k]["score"])
    best = max(reports, key=lambda k: reports[k]["score"])
    out = dict(reports[worst])
    out["engine"] = worst
    out["engines"] = {k: {"score": v["score"], "words": v["words"], "ats_pct": v["ats_pct"],
                          "char_spacing": v["char_spacing"],
                          "email": v["contact"].get("email", ""),
                          "phone": v["contact"].get("phone", ""),
                          "sections": v["sections"]["found"]} for k, v in reports.items()}
    for name, err in errors.items():                 # extracteur absent : on le dit, sans pénaliser
        out["engines"][name] = {"unavailable": err}

    gap = reports[best]["score"] - reports[worst]["score"]
    if gap >= 20:
        out["issues"] = [{"type": "parser_dependent", "severity": "high",
                          "detail": f"le résultat dépend du parseur ({best} : {reports[best]['score']}/100, "
                                    f"{worst} : {reports[worst]['score']}/100) — c'est un pari sur "
                                    "l'outil du recruteur", "count": 1}] + out["issues"]
        out["score"] = max(0, out["score"] - 5)
    return out


def compare_layouts(structured: Optional[Dict], cv_markdown: str, lang: str = "fr",
                    keywords: Optional[List[str]] = None, offer_text: str = "") -> Dict:
    """Rend le CV dans les DEUX mises en page et audite chacune.

    Sert de preuve chiffrée plutôt que d'affirmation : plutôt que de décréter
    « le 2 colonnes casse l'ATS », on montre le score de chacune sur CE CV-là et
    on recommande celle qui gagne (à égalité, la version une colonne)."""
    from core import export

    out = {}
    for layout in ("ats", "designed"):
        data = export.cv_pdf(structured, cv_markdown, lang, layout=layout)
        rep = audit(data, keywords, cv_markdown, offer_text)
        rep.pop("text", None)                    # rapport comparatif : pas besoin du texte
        rep["bytes"] = len(data)
        out[layout] = rep
    out["recommended"] = "ats" if out["ats"]["score"] >= out["designed"]["score"] else "designed"
    return out
