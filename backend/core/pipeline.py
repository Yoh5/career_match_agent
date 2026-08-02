"""File d'offres du pipeline de candidature — persistée, fail-open (même patron que memory.py).

Cycle de vie d'une offre :
  sourced → analyzed → ready → sent | skipped
    sourced  : trouvée par le sourcing (ou ajoutée à la main)
    analyzed : fit + ATS + go/no-go calculés
    ready    : dossier complet (CV adapté, lettre, message) — À TOI d'envoyer
    sent     : candidature envoyée (marquée par l'utilisateur ou via lemlist)
    skipped  : écartée (reco « passer » ou choix utilisateur)

Chemin surchargeable via CAREER_PIPELINE_PATH (tests). Écriture atomique.
"""
import hashlib
import json
import os
import tempfile
import time
from typing import Dict, List, Optional

STATUSES = ("sourced", "analyzed", "ready", "sent", "skipped")
_CAP = 300

_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "career_pipeline.json"
)


def _path() -> str:
    return os.getenv("CAREER_PIPELINE_PATH", "").strip() or _DEFAULT


def _load() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"items": []}
    except (FileNotFoundError, ValueError, TypeError, OSError):
        return {"items": []}


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


def _make_id(url: str) -> str:
    return hashlib.sha1((url or "").strip().lower().encode("utf-8")).hexdigest()[:12]


def add_offers(offers: List[Dict]) -> int:
    """Ajoute des offres sourcées (dédoublonnées par URL). Retourne le nb ajouté."""
    data = _load()
    items = data.setdefault("items", [])
    known = {it.get("id") for it in items}
    added = 0
    now = int(time.time())
    for o in offers or []:
        url = (o.get("url") or "").strip()
        if not url:
            continue
        oid = _make_id(url)
        if oid in known:
            continue
        items.append({
            "id": oid,
            "status": "sourced",
            "source": o.get("source") or "manual",
            "company": o.get("company") or "",
            "title": o.get("title") or "(offre)",
            "url": url,
            "location": o.get("location") or "",
            "offer_text": (o.get("description") or o.get("offer_text") or "")[:12000],
            "match_pct": o.get("match_pct"),
            "fit_score": None, "ats_pct": None, "decision": None,
            "prepared": {},
            "created": now, "updated": now,
        })
        known.add(oid)
        added += 1
    if len(items) > _CAP:
        # on évince les plus anciennes offres NON traitées d'abord
        keep = [it for it in items if it.get("status") not in ("sourced",)]
        rest = [it for it in items if it.get("status") == "sourced"]
        overflow = len(items) - _CAP
        items[:] = keep + rest[overflow:] if overflow < len(rest) else keep[-_CAP:]
    _save(data)
    return added


def list_items(status: Optional[str] = None) -> List[Dict]:
    """Offres du pipeline (les textes longs sont tronqués pour l'UI)."""
    items = _load().get("items", [])
    if status:
        items = [it for it in items if it.get("status") == status]
    out = []
    # tri : meilleures correspondances d'abord, puis plus récentes
    for it in sorted(items, key=lambda x: (x.get("match_pct") is not None,
                                           x.get("match_pct") or 0,
                                           x.get("updated", 0)), reverse=True):
        lite = {k: v for k, v in it.items() if k not in ("offer_text", "prepared")}
        lite["has_offer_text"] = bool((it.get("offer_text") or "").strip())
        lite["prepared_keys"] = sorted((it.get("prepared") or {}).keys())
        out.append(lite)
    return out


def get(item_id: str) -> Optional[Dict]:
    for it in _load().get("items", []):
        if it.get("id") == item_id:
            return it
    return None


def update(item_id: str, **fields) -> Optional[Dict]:
    """Met à jour une offre (statut, scores, livrables…). Retourne l'item ou None."""
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"Statut invalide : {fields['status']} (attendu : {', '.join(STATUSES)})")
    data = _load()
    for it in data.get("items", []):
        if it.get("id") == item_id:
            it.update(fields)
            it["updated"] = int(time.time())
            _save(data)
            return it
    return None


def stats() -> Dict:
    items = _load().get("items", [])
    by = {s: 0 for s in STATUSES}
    for it in items:
        by[it.get("status", "sourced")] = by.get(it.get("status", "sourced"), 0) + 1
    return {"total": len(items), "by_status": by}
