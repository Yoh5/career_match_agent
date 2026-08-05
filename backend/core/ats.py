"""Signal ATS déterministe : mots-clés d'une offre + couverture par le CV.

Un ATS (Applicant Tracking System) matche des mots-clés. On mesure, de façon
déterministe (frontières de mot, casse-insensible), lesquels apparaissent dans le
CV — un chiffre objectif qui complète l'analyse LLM.

Les mots-clés à mesurer viennent de deux sources combinées :
  1. `extra` — mots-clés extraits de l'offre par le LLM, TOUS DOMAINES (via
     `agent.offer_keywords`). C'est la source principale, agnostique au métier.
  2. `TECH_TERMS` — liste tech curée, gardée en SUPPLÉMENT/filet (utile pour les
     offres tech même sans clé LLM). Domaine-agnostique = surtout porté par `extra`.

Le matching imite ce que font les vrais ATS, et pas un `in` naïf :
  - **accents repliés** — « modélisation » trouve « modelisation » et l'inverse ;
  - **séparateurs souples** — `node.js` = `nodejs` = `node js` ; `ci/cd` = `cicd` ;
  - **pluriels** — « API » trouve « APIs », « compétence » trouve « compétences » ;
  - **alias** — `js` ↔ `javascript`, `k8s` ↔ `kubernetes`, `ML` ↔ `machine learning`,
    `RAG` ↔ `retrieval augmented generation`, et quelques paires FR/EN.

Et tous les mots-clés ne pèsent pas pareil : un terme listé sous « profil
recherché / requis » compte double, un « serait un plus » compte pour moitié
(`weighted_pct`). C'est cette pondération qui distingue un CV qui rate un
détail d'un CV qui rate le cœur du poste.
"""
import re
import unicodedata
from typing import Dict, List

# Supplément tech curé (filet déterministe). Le gros du signal vient désormais des
# mots-clés que le LLM extrait de l'offre (tous domaines) et passe via `extra`.
TECH_TERMS = [
    # Langages
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust", "php", "sql", "bash",
    # IA / LLM / Data
    "machine learning", "deep learning", "nlp", "llm", "rag", "prompt engineering", "agents",
    "langchain", "langgraph", "openai", "anthropic", "groq", "hugging face", "transformers",
    "scikit-learn", "pandas", "numpy", "pytorch", "tensorflow", "mlops", "computer vision", "data science",
    # Backend / API
    "fastapi", "django", "flask", "node.js", "express", "laravel", "rest", "api", "graphql", "microservices",
    # Bases de données
    "postgresql", "mysql", "mongodb", "redis", "supabase", "oracle", "nosql",
    # Cloud / DevOps
    "docker", "kubernetes", "aws", "gcp", "azure", "ci/cd", "github actions", "terraform", "ansible",
    "linux", "nginx", "git",
    # Frontend
    "react", "next.js", "vue", "angular", "html", "css", "tailwind",
    # Méthodo
    "agile", "scrum",
]

# ── Alias : formes qu'un recruteur écrit indifféremment ─────────────────────
# Chaque groupe est bidirectionnel : chercher n'importe quel membre trouve les
# autres. Volontairement conservateur — on n'ajoute PAS les abréviations qui sont
# aussi des mots courants (« next », « vue » = mot français, « react » suffit).
_ALIAS_GROUPS = [
    ["javascript", "js"],
    ["typescript", "ts"],
    ["kubernetes", "k8s"],
    ["machine learning", "ml", "apprentissage automatique"],
    ["deep learning", "apprentissage profond"],
    ["nlp", "natural language processing", "traitement automatique du langage"],
    ["llm", "large language model", "modele de langage"],
    ["rag", "retrieval augmented generation"],
    ["postgresql", "postgres"],
    ["node.js", "nodejs"],
    ["ci/cd", "cicd", "integration continue", "continuous integration"],
    ["rest", "restful", "api rest", "rest api"],
    ["github actions", "gh actions"],
    ["aws", "amazon web services"],
    ["gcp", "google cloud platform"],
    ["azure", "microsoft azure"],
    ["computer vision", "vision par ordinateur"],
    ["data science", "science des donnees"],
    ["scikit-learn", "sklearn"],
    ["react", "reactjs", "react.js"],
    ["next.js", "nextjs"],
    ["vue.js", "vuejs"],
    ["poo", "programmation orientee objet", "object oriented programming", "oop"],
    ["base de donnees", "database"],
]


def fold(s: str) -> str:
    """Minuscules sans accents — « Modélisation » → « modelisation ».
    Appliqué des deux côtés (terme ET texte) pour que le matching soit
    insensible aux accents, comme le sont les moteurs des ATS."""
    n = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def _alias_index() -> Dict[str, List[str]]:
    """{forme repliée → toutes les formes du groupe}."""
    idx: Dict[str, List[str]] = {}
    for group in _ALIAS_GROUPS:
        folded = [fold(g) for g in group]
        for f in folded:
            idx.setdefault(f, [])
            idx[f] += [x for x in folded if x not in idx[f]]
    return idx


_ALIASES = _alias_index()

# Séparateurs interchangeables ou omissibles à l'intérieur d'un terme :
# c'est ce qui fait que `node.js`, `nodejs` et `node js` sont le même mot-clé.
_SEP = re.compile(r"[\s./\\_\-]+")


def _pattern(form: str) -> str:
    """Regex d'une forme : séparateurs souples, pluriel optionnel, frontières de mot.

    Le pluriel n'est autorisé qu'à partir de 3 caractères (sinon « go » matcherait
    « goes ») et les suffixes longs à partir de 5 (« api » → « apis », mais pas
    « rag » → « rages »)."""
    parts = [re.escape(p) for p in _SEP.split(form) if p]
    if not parts:
        return ""
    core = r"[\s./\\_\-]*".join(parts)
    plural = ""
    if len(form) >= 5:
        plural = r"(?:s|es|x)?"
    elif len(form) >= 3:
        plural = r"s?"
    return r"(?<![a-z0-9])" + core + plural + r"(?![a-z0-9])"


def forms(term: str) -> List[str]:
    """Toutes les écritures acceptées pour `term` (lui-même + ses alias)."""
    f = fold(term).strip()
    if not f:
        return []
    return _ALIASES.get(f, [f])


def _found(term: str, text: str) -> bool:
    """Vrai si `term` — ou l'un de ses alias — apparaît dans `text`, accents repliés,
    séparateurs souples et pluriel toléré. Les frontières de mot évitent 'rag' dans
    'storage' ou 'go' dans 'good'."""
    folded = fold(text)
    for form in forms(term):
        pat = _pattern(form)
        if pat and re.search(pat, folded):
            return True
    return False


def _count(term: str, text: str) -> int:
    """Nombre d'occurrences (toutes formes confondues) — sert à la pondération."""
    folded = fold(text)
    total = 0
    for form in forms(term):
        pat = _pattern(form)
        if pat:
            total += len(re.findall(pat, folded))
    return total


def extract_keywords(offer_text: str, extra: List[str] = None) -> List[str]:
    """Mots-clés techniques présents dans l'offre (liste curée + `extra` éventuels
    fournis par le LLM). Triés, dédupliqués."""
    pool = list(TECH_TERMS) + [str(e).strip() for e in (extra or []) if str(e).strip()]
    found = [t for t in pool if _found(t, offer_text)]
    # dédup casse-insensible en gardant la première casse
    seen, out = set(), []
    for t in found:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return sorted(out, key=str.lower)


# ── Pondération : tous les mots-clés ne valent pas la même chose ────────────

# Un intitulé qui ouvre une liste d'exigences → ce qui suit est ÉLIMINATOIRE.
_REQUIRED_HINTS = (
    "profil recherche", "profil souhaite", "competences requises", "competences techniques",
    "pre-requis", "prerequis", "requis", "indispensable", "obligatoire", "exige",
    "vous maitrisez", "vous justifiez", "ce que nous recherchons",
    "requirements", "required", "must have", "must-have", "qualifications",
    "what you'll need", "what you need", "essential",
)
# Un intitulé qui ouvre une liste de bonus → ce qui suit est SECONDAIRE.
_NICE_HINTS = (
    "serait un plus", "un plus", "atout", "atouts", "apprecie", "souhaite mais",
    "bonus", "nice to have", "nice-to-have", "preferred", "desirable", "optionnel",
)

_TIER_WEIGHT = {"required": 2.0, "neutral": 1.0, "nice": 0.6}


def _tiered_lines(offer_text: str) -> List[tuple]:
    """Découpe l'offre en (ligne, palier) où palier ∈ required/neutral/nice.
    Le palier est porté par le dernier intitulé rencontré ; une ligne qui contient
    elle-même « serait un plus » bascule en `nice` sans contaminer les suivantes."""
    out = []
    current = "neutral"
    for raw in (offer_text or "").splitlines():
        line = raw.strip()
        f = fold(line)
        if not f:
            continue
        is_heading = len(line) <= 90
        if is_heading and any(h in f for h in _REQUIRED_HINTS):
            current = "required"
        elif is_heading and any(h in f for h in _NICE_HINTS):
            current = "nice"
        tier = "nice" if any(h in f for h in _NICE_HINTS) else current
        out.append((line, tier))
    return out


def keyword_weights(offer_text: str, keywords: List[str]) -> Dict[str, Dict]:
    """Poids de chaque mot-clé pour CETTE offre : {terme: {weight, tier, count}}.

    weight = poids du palier (requis ×2, bonus ×0.6) majoré par la répétition —
    un terme martelé trois fois dans l'offre est un vrai critère, pas un détail."""
    lines = _tiered_lines(offer_text)
    out: Dict[str, Dict] = {}
    for kw in keywords or []:
        term = str(kw).strip()
        if not term:
            continue
        tiers, count = set(), 0
        for line, tier in lines:
            n = _count(term, line)
            if n:
                count += n
                tiers.add(tier)
        # priorité : requis > neutre > bonus (un terme vu SEULEMENT en bonus
        # reste un bonus ; dès qu'il apparaît dans les exigences, il devient requis)
        best_tier = ("required" if "required" in tiers
                     else "neutral" if "neutral" in tiers
                     else "nice" if "nice" in tiers else "neutral")
        weight = _TIER_WEIGHT[best_tier]
        if count >= 3:
            weight *= 1.4
        elif count == 2:
            weight *= 1.15
        out[term] = {"weight": round(weight, 2), "tier": best_tier, "count": count}
    return out


def coverage(cv_text: str, keywords: List[str], offer_text: str = "") -> Dict:
    """Part des mots-clés de l'offre présents dans le CV.

    Retourne {matched, missing, pct, weighted_pct, critical_missing, weights}.
    - `pct` — couverture brute, un mot-clé = une voix (rétro-compatible).
    - `weighted_pct` — couverture pondérée par l'importance du mot-clé dans l'offre
      (nécessite `offer_text` ; sans lui, identique à `pct`).
    - `critical_missing` — les manquants au poids ≥ 1.5, ceux qui font vraiment
      recaler : c'est la liste à traiter en priorité."""
    kws = [k for k in (keywords or []) if str(k).strip()]
    matched = [k for k in kws if _found(k, cv_text)]
    missing = [k for k in kws if k not in matched]
    pct = round(100 * len(matched) / len(kws)) if kws else 0

    weights = keyword_weights(offer_text, kws) if offer_text else {}
    if weights:
        total = sum(weights[k]["weight"] for k in kws)
        got = sum(weights[k]["weight"] for k in matched)
        weighted = round(100 * got / total) if total else 0
        critical = [k for k in missing if weights[k]["weight"] >= 1.5]
    else:
        weighted, critical = pct, []
    return {"matched": matched, "missing": missing, "pct": pct,
            "weighted_pct": weighted, "critical_missing": critical, "weights": weights}
