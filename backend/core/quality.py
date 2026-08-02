"""Qualité rédactionnelle DÉTERMINISTE des documents générés (lettre, CV).

Pendant de `ats.py` : là où l'ATS mesure la pertinence, ce module mesure la
CORRECTION du texte — sans LLM, donc testable et reproductible. Il sert de
seconde fonction objectif aux boucles agentiques (`agent.optimize_*`).

Détecte ce qu'un LLM rate le plus souvent dans une candidature :
  - **placeholders non remplis** : « [Nom] », « XXX », « TODO », « à compléter » ;
  - **mélange de langues** : bouts d'anglais dans une lettre française (et
    inversement) — mesuré sur les MOTS-OUTILS, pour ne pas pénaliser les termes
    métier anglais légitimes (« Machine Learning », « Data Scientist ») ;
  - **fautes de frappe/typographie** : espace avant une virgule, doubles espaces,
    mot dupliqué (« de de »), ponctuation triplée, apostrophes incohérentes ;
  - **typographie française** : espace manquante avant « : ; ! ? » ;
  - **artefacts de LLM** : préambules (« Voici la lettre… »), blocs de code.

`score()` renvoie 0-100 (100 = impeccable) + la liste des problèmes.
"""
import re
import unicodedata
from typing import Dict, List

SEVERITY_PENALTY = {"critical": 20, "high": 10, "medium": 4, "low": 1}

# Mots-outils DISCRIMINANTS (présents dans une langue, absents de l'autre).
# Volontairement sans les ambigus (a, on, son, plus, but, as, an…).
_FR_STOP = {
    "le", "la", "les", "des", "une", "dans", "avec", "pour", "sur", "mes", "ses", "cette",
    "chez", "être", "avoir", "comme", "ainsi", "notamment", "suis", "mon", "ma", "votre",
    "vos", "je", "vous", "aux", "du", "et", "qui", "que", "ne", "pas", "ces", "leur", "nos",
    "notre", "sont", "était", "cela", "dont", "où", "très", "bien", "tout", "tous", "toute",
    "ce", "au", "par", "mais", "donc", "lors", "elles", "ils", "vers", "sans", "sous",
}
_EN_STOP = {
    "the", "and", "with", "for", "this", "that", "have", "been", "from", "will", "your",
    "our", "their", "would", "which", "while", "about", "through", "was", "are", "were",
    "they", "has", "its", "into", "than", "then", "when", "where", "who", "why", "how",
    "what", "of", "in", "to", "it", "is", "you", "my", "me", "at", "be", "or", "we", "should",
}

# Placeholders : crochets/accolades/chevrons non remplis, jokers, mentions « à compléter ».
_PH_BRACKET = re.compile(r"\[[^\]\n]{1,60}\](?!\()")        # [Nom] — hors lien Markdown [x](y)
_PH_BRACE = re.compile(r"\{\{?[^}\n]{1,60}\}\}?")
_PH_ANGLE = re.compile(r"<[A-Za-zÀ-ÿ][^>\n]{0,60}>")
_PH_WORDS = re.compile(
    r"\b(?:X{3,}|TODO|TBD|FIXME|lorem ipsum|à compléter|a completer|votre nom|"
    r"nom de l['’]entreprise|insérer|inserer|placeholder)\b", re.IGNORECASE)
_PH_UNDERSCORE = re.compile(r"_{3,}")

# Artefacts de LLM : préambule bavard ou bloc de code encadrant la réponse.
_PREAMBLE = re.compile(
    r"^\s*(?:voici|voilà|bien sûr|certainement|here (?:is|'s)|sure[,!]|certainly)\b[^\n]{0,120}"
    r"(?::|\.)\s*$", re.IGNORECASE | re.MULTILINE)
_CODE_FENCE = re.compile(r"^\s*```", re.MULTILINE)

_WORD = re.compile(r"[A-Za-zÀ-ÿ]+(?:['’][A-Za-zÀ-ÿ]+)?")


def _words(text: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def language_mix(text: str, lang: str = "fr") -> Dict:
    """Part de mots-outils de la LANGUE ÉTRANGÈRE. Retourne
    {expected, foreign_pct, samples[], reliable}. `reliable` False si le texte est
    trop court pour conclure (évite les faux positifs)."""
    expected = "en" if str(lang).lower().startswith("en") else "fr"
    ws = _words(text)
    fr = [w for w in ws if w in _FR_STOP]
    en = [w for w in ws if w in _EN_STOP]
    native, foreign = (en, fr) if expected == "en" else (fr, en)
    total = len(native) + len(foreign)
    pct = round(100 * len(foreign) / total) if total else 0
    # échantillon des intrus, dans l'ordre d'apparition, dédupliqué
    seen, samples = set(), []
    for w in foreign:
        if w not in seen:
            seen.add(w)
            samples.append(w)
    return {"expected": expected, "foreign_pct": pct, "samples": samples[:8],
            "reliable": total >= 10}


def _typo_issues(text: str, lang: str) -> List[Dict]:
    """Fautes de frappe et de typographie, toutes langues + règles françaises."""
    out = []
    t = text or ""

    def add(kind, severity, detail, count):
        if count:
            out.append({"type": kind, "severity": severity, "detail": detail, "count": count})

    add("space_before_punct", "high", "espace avant une virgule ou un point",
        len(re.findall(r"\s+[,.](?:\s|$)", t)))
    add("double_space", "low", "double espace",
        len(re.findall(r"(?<=\S)  +(?=\S)", t)))
    add("repeated_word", "high", "mot répété consécutivement",
        len(re.findall(r"\b([A-Za-zÀ-ÿ]{2,})\s+\1\b", t, re.IGNORECASE)))
    add("triple_punct", "low", "ponctuation répétée (!!! / ???)",
        len(re.findall(r"[!?]{3,}", t)))
    add("space_before_paren", "low", "parenthèse mal espacée",
        len(re.findall(r"\(\s|\s\)", t)))

    if lang == "fr":
        # Français : espace requise AVANT : ; ! ? (fine insécable en typographie soignée)
        add("fr_missing_space", "medium", "espace manquante avant « : ; ! ? »",
            len(re.findall(r"[A-Za-zÀ-ÿ0-9][;!?](?:\s|$)|[A-Za-zÀ-ÿ0-9]:(?:\s|$)", t)))
        straight, curly = t.count("'"), t.count("’")
        if straight and curly:      # mélange d'apostrophes = rendu incohérent
            add("mixed_apostrophes", "low", "apostrophes droites et typographiques mélangées", 1)
    return out


def _placeholder_issues(text: str) -> List[Dict]:
    t = text or ""
    found = (_PH_BRACKET.findall(t) + _PH_BRACE.findall(t) + _PH_ANGLE.findall(t)
             + _PH_WORDS.findall(t) + _PH_UNDERSCORE.findall(t))
    if not found:
        return []
    return [{"type": "placeholder", "severity": "critical",
             "detail": "champ non rempli : " + ", ".join(sorted({f.strip() for f in found})[:5]),
             "count": len(found)}]


def issues(text: str, lang: str = "fr", kind: str = "letter") -> List[Dict]:
    """Tous les problèmes détectés, triés du plus grave au moins grave."""
    lg = "en" if str(lang).lower().startswith("en") else "fr"
    t = text or ""
    out: List[Dict] = []

    out += _placeholder_issues(t)

    mix = language_mix(t, lg)
    if mix["reliable"] and mix["foreign_pct"] >= 12:
        sev = "critical" if mix["foreign_pct"] >= 35 else "high"
        out.append({"type": "language_mix", "severity": sev,
                    "detail": f"{mix['foreign_pct']}% de mots-outils d'une autre langue "
                              f"({', '.join(mix['samples'][:5])})",
                    "count": 1})

    out += _typo_issues(t, lg)

    n_pre = len(_PREAMBLE.findall(t))
    if n_pre:
        out.append({"type": "llm_preamble", "severity": "high",
                    "detail": "préambule de l'IA laissé dans le document", "count": n_pre})
    if _CODE_FENCE.search(t):
        out.append({"type": "code_fence", "severity": "medium",
                    "detail": "bloc de code ``` autour du document", "count": 1})

    if kind == "letter":
        words = len(_words(t))
        if words and words < 120:
            out.append({"type": "too_short", "severity": "medium",
                        "detail": f"lettre très courte ({words} mots)", "count": 1})
        elif words > 600:
            out.append({"type": "too_long", "severity": "low",
                        "detail": f"lettre longue ({words} mots)", "count": 1})

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(out, key=lambda i: (order.get(i["severity"], 9), -i["count"]))


def score(text: str, lang: str = "fr", kind: str = "letter") -> Dict:
    """Note de qualité rédactionnelle 0-100 (100 = impeccable) + problèmes.
    Chaque problème coûte sa pénalité de sévérité, majorée par sa fréquence
    (racine carrée : 5 doubles espaces ne doivent pas anéantir la note)."""
    found = issues(text, lang, kind)
    penalty = 0.0
    for i in found:
        base = SEVERITY_PENALTY.get(i["severity"], 1)
        penalty += base * min(3.0, max(1, i.get("count", 1)) ** 0.5)
    return {"score": max(0, round(100 - penalty)), "issues": found, "penalty": round(penalty, 1)}


def normalize(text: str, lang: str = "fr") -> str:
    """Corrections mécaniques SÛRES, sans LLM (appliquées avant la relecture) :
    retire les blocs de code encadrants et les préambules, corrige les espacements.
    Ne touche jamais au contenu factuel."""
    t = unicodedata.normalize("NFC", text or "").strip()
    # blocs de code encadrant tout le document
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t)
    t = _PREAMBLE.sub("", t)
    t = re.sub(r"[ \t]+([,.])", r"\1", t)               # espace avant , ou .
    t = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", t)       # doubles espaces
    t = re.sub(r"\n{3,}", "\n\n", t)                     # lignes vides en excès
    if not str(lang).lower().startswith("en"):
        # Espace avant la ponctuation double française. Volontairement une espace
        # ASCII et non une fine insécable (U+202F) : les ATS parsent mal l'Unicode
        # exotique, et la lisibilité reste correcte.
        t = re.sub(r"(?<=[A-Za-zÀ-ÿ0-9\)])(?=[;!?])", " ", t)
        t = re.sub(r"(?<=[A-Za-zÀ-ÿ0-9\)]):(?=\s)", " :", t)
    return t.strip()
