"""Templates de message d'outreach — éditables par l'utilisateur, persistés.

L'utilisateur définit UNE FOIS ses messages types (invitation LinkedIn ≤300 car.,
message de suivi, e-mail) ; l'agent les personnalise par offre via des placeholders :
  {company} {role} {my_name} {highlight} {link} {first_name}

Placeholders inconnus laissés tels quels (rendu tolérant). Store JSON fail-open,
chemin surchargeable via CAREER_TEMPLATES_PATH (tests).
"""
import json
import os
import tempfile
from typing import Dict

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "career_templates.json"
)

DEFAULTS: Dict[str, str] = {
    "linkedin_invite": (
        "Bonjour {first_name}, je candidate au stage {role} chez {company}. "
        "Mon projet {highlight} correspond bien au poste — au plaisir d'échanger ! {my_name}"
    ),
    "linkedin_message": (
        "Bonjour {first_name},\n\n"
        "Je viens de postuler au stage {role} chez {company} et je me permets de vous écrire directement.\n"
        "Ce poste m'intéresse particulièrement : j'ai notamment travaillé sur {highlight}, "
        "ce qui rejoint vos besoins.\n\n"
        "Seriez-vous disponible pour un court échange ? Mon CV adapté à l'offre est joint à ma candidature.\n\n"
        "Merci beaucoup,\n{my_name}"
    ),
    "email": (
        "Objet : Candidature — Stage {role} ({my_name})\n\n"
        "Bonjour,\n\n"
        "Je vous adresse ma candidature pour le stage {role} chez {company} ({link}).\n"
        "Mon expérience sur {highlight} correspond directement à vos attentes ; "
        "vous trouverez en pièces jointes mon CV adapté au poste et ma lettre de motivation.\n\n"
        "Je reste disponible pour un entretien à votre convenance.\n\n"
        "Cordialement,\n{my_name}"
    ),
}


def _path() -> str:
    return os.getenv("CAREER_TEMPLATES_PATH", "").strip() or _DEFAULT_PATH


def get_all() -> Dict[str, str]:
    """Templates courants : défauts recouverts par les personnalisations sauvegardées."""
    out = dict(DEFAULTS)
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for k, v in saved.items():
                if isinstance(v, str) and v.strip():
                    out[k] = v
    except (FileNotFoundError, ValueError, TypeError, OSError):
        pass
    return out


def save(templates: Dict[str, str]) -> Dict[str, str]:
    """Sauvegarde les templates fournis (str non vides uniquement). Retourne l'état courant."""
    clean = {k: v for k, v in (templates or {}).items() if isinstance(v, str) and v.strip()}
    try:
        p = _path()
        d = os.path.dirname(p) or "."
        os.makedirs(d, exist_ok=True)
        current = {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                current = json.load(f) or {}
        except (FileNotFoundError, ValueError, OSError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        current.update(clean)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except OSError:
        pass  # fail-open
    return get_all()


class _Tolerant(dict):
    def __missing__(self, key):  # placeholder inconnu → laissé tel quel
        return "{" + key + "}"


def render(key: str, variables: Dict[str, str]) -> str:
    """Rend un template avec les variables de l'offre. Clé inconnue → chaîne vide."""
    tpl = get_all().get(key, "")
    if not tpl:
        return ""
    safe = {k: str(v) for k, v in (variables or {}).items() if v is not None}
    try:
        return tpl.format_map(_Tolerant(safe))
    except (ValueError, IndexError):  # accolades malformées dans un template édité
        return tpl
