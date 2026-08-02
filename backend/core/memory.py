"""Mémoire long terme du Career Match Agent (#4) — fail-open, testable sans réseau.

Persiste les candidatures analysées afin d'apprendre d'une session à l'autre :
  - dédoublonnage : « cette offre a déjà été analysée » (+ ce qui avait été décidé) ;
  - profil agrégé du candidat (nb de candidatures, fit moyen) ;
  - écarts RÉCURRENTS : mots-clés qui manquent souvent → « forme-toi / ajoute X ».

Chemin surchargeable via CAREER_MEMORY_PATH (tests). Écriture atomique. Aucune
erreur d'E/S ne remonte : la mémoire ne doit jamais casser l'app.
"""
import hashlib
import json
import os
import tempfile
import time
from collections import Counter
from typing import Dict, List, Optional

_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "career_memory.json"
)
_CAP = 200  # nombre max de candidatures conservées


def _path() -> str:
    return os.getenv("CAREER_MEMORY_PATH", "").strip() or _DEFAULT


def _load() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"applications": []}
    except (FileNotFoundError, ValueError, TypeError, OSError):
        return {"applications": []}


def _save(data: dict) -> None:
    try:
        p = _path()
        d = os.path.dirname(p) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except OSError:
        pass  # fail-open


def _hash(offer_text: str) -> str:
    return hashlib.sha1((offer_text or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def _title(offer_text: str) -> str:
    for line in (offer_text or "").splitlines():
        s = line.strip()
        if len(s) >= 3:
            return s[:80]
    return "(offre)"


def record_application(offer_text: str, result: dict) -> None:
    """Enregistre (ou met à jour) une candidature analysée. `result` peut contenir
    fit_score, ats_pct, recommendation, missing_keywords."""
    result = result or {}
    data = _load()
    apps = data.setdefault("applications", [])
    rec = {
        "ts": int(time.time()),
        "hash": _hash(offer_text),
        "title": _title(offer_text),
        "fit_score": result.get("fit_score"),
        "ats_pct": result.get("ats_pct"),
        "recommendation": result.get("recommendation"),
        "missing_keywords": [
            str(k).strip().lower() for k in (result.get("missing_keywords") or []) if str(k).strip()
        ][:30],
    }
    apps[:] = [a for a in apps if a.get("hash") != rec["hash"]]  # dédoublonnage
    apps.append(rec)
    if len(apps) > _CAP:
        del apps[:-_CAP]
    _save(data)


def recall(offer_text: str) -> Optional[dict]:
    """Enregistrement précédent pour la MÊME offre, sinon None."""
    h = _hash(offer_text)
    for a in reversed(_load().get("applications", [])):
        if a.get("hash") == h:
            return a
    return None


def recurring_gaps(min_count: int = 2, top: int = 8) -> List[Dict]:
    """Mots-clés manquants récurrents à travers les offres analysées
    (comptés une fois par offre). Trié par fréquence décroissante."""
    c: Counter = Counter()
    for a in _load().get("applications", []):
        for k in set(a.get("missing_keywords") or []):
            c[k] += 1
    return [{"keyword": k, "count": n} for k, n in c.most_common(top) if n >= min_count]


def profile_summary() -> Dict:
    """Vue agrégée du candidat (pour nourrir la recommandation / l'UI)."""
    apps = _load().get("applications", [])
    scores = [a["fit_score"] for a in apps if isinstance(a.get("fit_score"), (int, float))]
    return {
        "count": len(apps),
        "avg_fit": round(sum(scores) / len(scores)) if scores else None,
        "recurring_gaps": recurring_gaps(),
    }
