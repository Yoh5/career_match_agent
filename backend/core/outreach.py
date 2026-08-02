"""Outreach via lemlist — envoi SÛR de messages recruteur (jamais d'automatisation
LinkedIn directe : c'est lemlist qui gère l'envoi avec ses limites de sécurité).

L'agent pousse un lead (recruteur) + le message personnalisé dans une campagne
lemlist ; la campagne (configurée côté lemlist) fait l'invitation/le message
LinkedIn ou l'e-mail avec throttling. Chaque envoi est déclenché par un clic
explicite de l'utilisateur dans l'UI — pas d'envoi en masse automatique.

Fail-open : sans LEMLIST_API_KEY, tout renvoie (None, msg) et l'UI reste en
mode « copier le message ». `_request` est isolé pour être monkeypatché.
"""
import os
from typing import Dict, List, Optional, Tuple

API_BASE = "https://api.lemlist.com/api"


def _key() -> str:
    return os.getenv("LEMLIST_API_KEY", "").strip()


def is_enabled() -> bool:
    return bool(_key())


def _request(method: str, path: str, json_body: Optional[dict] = None) -> Tuple[Optional[object], Optional[str]]:
    """Appel API lemlist (auth basic : user vide + clé). Retourne (json, err)."""
    if not is_enabled():
        return None, "LEMLIST_API_KEY manquante — ajoute-la dans backend/.env pour activer l'envoi"
    try:
        import httpx
        with httpx.Client(timeout=20, auth=("", _key())) as client:
            r = client.request(method, API_BASE + path, json=json_body)
        if r.status_code >= 400:
            return None, f"lemlist HTTP {r.status_code} : {r.text[:200]}"
        try:
            return r.json(), None
        except ValueError:
            return {}, None
    except Exception as e:
        return None, f"lemlist injoignable ({e})"


def campaigns() -> Tuple[Optional[List[Dict]], Optional[str]]:
    """Campagnes lemlist du compte → [{_id, name}]."""
    data, err = _request("GET", "/campaigns")
    if err:
        return None, err
    out = []
    for c in (data or []):
        if isinstance(c, dict):
            out.append({"id": c.get("_id") or c.get("id"), "name": c.get("name") or "(campagne)"})
    return out, None


def add_lead(campaign_id: str, email: str, fields: Dict[str, str]) -> Tuple[Optional[dict], Optional[str]]:
    """Ajoute un recruteur (lead) à une campagne avec le message personnalisé
    en variables custom ({{message}}, {{companyName}}… côté lemlist).

    fields : first_name, last_name, company, message, linkedin_url (tous optionnels).
    """
    campaign_id = (campaign_id or "").strip()
    email = (email or "").strip()
    if not campaign_id:
        return None, "campaign_id manquant"
    if not email or "@" not in email:
        return None, "email du recruteur invalide"
    fields = fields or {}
    body = {
        "firstName": fields.get("first_name") or "",
        "lastName": fields.get("last_name") or "",
        "companyName": fields.get("company") or "",
        "linkedinUrl": fields.get("linkedin_url") or "",
        # variable custom utilisable dans le template de la campagne lemlist : {{message}}
        "message": fields.get("message") or "",
    }
    body = {k: v for k, v in body.items() if v}
    return _request("POST", f"/campaigns/{campaign_id}/leads/{email}?deduplicate=true", json_body=body)
