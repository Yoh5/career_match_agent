"""Signal ATS déterministe : mots-clés d'une offre + couverture par le CV.

Un ATS (Applicant Tracking System) matche des mots-clés. On mesure, de façon
déterministe (frontières de mot, casse-insensible), lesquels apparaissent dans le
CV — un chiffre objectif qui complète l'analyse LLM.

Les mots-clés à mesurer viennent de deux sources combinées :
  1. `extra` — mots-clés extraits de l'offre par le LLM, TOUS DOMAINES (via
     `agent.offer_keywords`). C'est la source principale, agnostique au métier.
  2. `TECH_TERMS` — liste tech curée, gardée en SUPPLÉMENT/filet (utile pour les
     offres tech même sans clé LLM). Domaine-agnostique = surtout porté par `extra`.
"""
import re
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


def _found(term: str, text: str) -> bool:
    """Vrai si `term` apparaît dans `text` en respectant les frontières de mot
    (évite 'rag' dans 'storage', 'go' dans 'good')."""
    return re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])",
                     (text or "").lower()) is not None


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


def coverage(cv_text: str, keywords: List[str]) -> Dict:
    """Part des mots-clés de l'offre présents dans le CV.
    Retourne {matched, missing, pct}."""
    kws = [k for k in (keywords or []) if str(k).strip()]
    matched = [k for k in kws if _found(k, cv_text)]
    missing = [k for k in kws if k not in matched]
    pct = round(100 * len(matched) / len(kws)) if kws else 0
    return {"matched": matched, "missing": missing, "pct": pct}
