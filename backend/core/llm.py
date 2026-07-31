"""Primitive LLM partagée (OpenAI). Appel isolé + parse JSON tolérant.

`complete()` renvoie `(text, err)` — jamais d'exception qui casse l'app.
Sans `OPENAI_API_KEY`, `is_enabled()` est faux et les fonctions agentiques
renvoient une erreur exploitable côté API.
"""
import json
import os
import re


def _key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def _model() -> str:
    return os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o-mini"


def is_enabled() -> bool:
    return bool(_key())


def complete(prompt: str, json_mode: bool = True, max_tokens: int = 1600,
             temperature: float = 0.3) -> tuple:
    """Retourne (texte, err). err=None si OK."""
    if not _key():
        return "", "OPENAI_API_KEY manquante — ajoute ta clé dans backend/.env"
    try:
        from openai import OpenAI
        client = OpenAI(api_key=_key())
        kwargs = {
            "model": _model(),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or ""), None
    except Exception as e:  # réseau, quota, auth…
        return "", str(e)


def parse_json(raw: str):
    """json.loads tolérant : réessaie sur le premier objet {...} trouvé."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except (ValueError, TypeError):
                return None
        return None
