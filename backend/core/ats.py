"""Signal ATS déterministe : mots-clés d'une offre + couverture par le CV.

Un ATS (Applicant Tracking System) matche des mots-clés. On extrait les termes
techniques présents dans l'offre (liste curée, frontières de mot pour éviter les
faux positifs) puis on mesure lesquels apparaissent dans le CV. Déterministe,
testable sans réseau — complète l'analyse LLM d'un chiffre objectif.
"""
import re
from typing import Dict, List

# Termes techniques reconnus (élargir librement). Minuscule = comparaison casse-insensible.
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
