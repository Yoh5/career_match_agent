"""Sourcing d'offres de stage — APIs PUBLIQUES d'ATS (approche career-ops).

Aucune automatisation LinkedIn/Indeed (CGU) : on interroge les job boards que les
entreprises exposent volontairement en JSON public :
  - Greenhouse : https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
  - Lever      : https://api.lever.co/v0/postings/{company}?mode=json
  - Ashby      : https://api.ashbyhq.com/posting-api/job-board/{org}
  - RemoteOK   : https://remoteok.com/api  (agrégateur, flux JSON public)

Chaque source est fail-open : une source en erreur n'empêche pas les autres.
Tout est normalisé en {source, company, title, url, location, description}.
"""
import re
from typing import Dict, List, Tuple

# Termes qui signalent un stage / une alternance (FR + EN)
STAGE_TERMS = (
    "stage", "stagiaire", "intern", "internship", "alternance", "alternant",
    "apprenti", "apprentissage", "pfe", "pfa", "trainee", "work-study", "working student",
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$", re.IGNORECASE)


def _get_json(url: str, timeout: int = 20):
    """GET → (json, err). Isolé pour être monkeypatché dans les tests."""
    try:
        import httpx
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "CareerMatchAgent/1.0"}) as client:
            r = client.get(url)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    except Exception as e:  # réseau, JSON invalide…
        return None, str(e)


def _strip_html(html: str) -> str:
    # Greenhouse renvoie le HTML ÉCHAPPÉ (&lt;p&gt;) → déséchapper AVANT de retirer les balises.
    from html import unescape
    text = re.sub(r"(?s)<[^>]+>", " ", unescape(html or ""))
    return re.sub(r"\s+", " ", text).strip()


def _valid_slug(s: str) -> bool:
    return bool(_SLUG_RE.match((s or "").strip()))


# ── Connecteurs (un par ATS) ────────────────────────────────────────────────

def greenhouse_jobs(board: str) -> Tuple[List[Dict], str]:
    if not _valid_slug(board):
        return [], f"identifiant Greenhouse invalide : {board!r}"
    data, err = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{board.strip()}/jobs?content=true")
    if err:
        return [], f"greenhouse:{board} — {err}"
    jobs = []
    for j in (data or {}).get("jobs", []):
        jobs.append({
            "source": "greenhouse", "company": board,
            "title": (j.get("title") or "").strip(),
            "url": j.get("absolute_url") or "",
            "location": ((j.get("location") or {}).get("name") or "").strip(),
            "description": _strip_html(j.get("content") or "")[:6000],
        })
    return jobs, ""


def lever_jobs(company: str) -> Tuple[List[Dict], str]:
    if not _valid_slug(company):
        return [], f"identifiant Lever invalide : {company!r}"
    data, err = _get_json(f"https://api.lever.co/v0/postings/{company.strip()}?mode=json")
    if err:
        return [], f"lever:{company} — {err}"
    jobs = []
    for j in (data or []):
        cats = j.get("categories") or {}
        jobs.append({
            "source": "lever", "company": company,
            "title": (j.get("text") or "").strip(),
            "url": j.get("hostedUrl") or "",
            "location": (cats.get("location") or "").strip(),
            "description": ((j.get("descriptionPlain") or "") + " " + (cats.get("commitment") or ""))[:6000],
        })
    return jobs, ""


def ashby_jobs(org: str) -> Tuple[List[Dict], str]:
    if not _valid_slug(org):
        return [], f"identifiant Ashby invalide : {org!r}"
    data, err = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{org.strip()}")
    if err:
        return [], f"ashby:{org} — {err}"
    jobs = []
    for j in (data or {}).get("jobs", []):
        jobs.append({
            "source": "ashby", "company": org,
            "title": (j.get("title") or "").strip(),
            "url": j.get("jobUrl") or j.get("applyUrl") or "",
            "location": (j.get("location") or "").strip(),
            "description": _strip_html(j.get("descriptionHtml") or j.get("descriptionPlain") or "")[:6000],
        })
    return jobs, ""


def remoteok_jobs() -> Tuple[List[Dict], str]:
    data, err = _get_json("https://remoteok.com/api")
    if err:
        return [], f"remoteok — {err}"
    jobs = []
    for j in (data or []):
        if not isinstance(j, dict) or not j.get("position"):
            continue  # 1er élément = mentions légales
        jobs.append({
            "source": "remoteok", "company": (j.get("company") or "").strip(),
            "title": (j.get("position") or "").strip(),
            "url": j.get("url") or "",
            "location": (j.get("location") or "Remote").strip(),
            "description": _strip_html(j.get("description") or "")[:6000],
        })
    return jobs, ""


# ── Filtrage + recherche agrégée ────────────────────────────────────────────

def looks_like_internship(job: Dict) -> bool:
    """Stage/alternance ? Cherche les termes dans le TITRE d'abord (signal fort),
    sinon dans la description ('internship program', 'stage de 6 mois'…)."""
    title = (job.get("title") or "").lower()
    if any(t in title for t in STAGE_TERMS):
        return True
    desc = (job.get("description") or "").lower()
    return any(re.search(r"\b" + re.escape(t), desc) for t in ("internship", "stage de", "alternance", "pfe", "pfa"))


# Équivalences de localisation FR/EN — les sources sont internationales : taper
# « Maroc » doit trouver une offre localisée « Casablanca » ou « Morocco » (et
# réciproquement), « Remote » doit couvrir « Anywhere / Worldwide ».
_LOC_ALIASES = {
    "maroc": ["maroc", "morocco", "casablanca", "rabat", "marrakech", "marrakesh",
              "tanger", "tangier", "agadir", "fès", "fes", "kenitra", "kénitra", "oujda", "salé", "sale"],
    "remote": ["remote", "anywhere", "worldwide", "télétravail", "teletravail", "full remote", "work from home"],
    "france": ["france", "paris", "lyon", "lille", "nantes", "bordeaux", "toulouse", "marseille", "grenoble"],
}
_LOC_ALIASES["morocco"] = _LOC_ALIASES["maroc"]


def _expand_location(term: str) -> List[str]:
    t = (term or "").strip().lower()
    return _LOC_ALIASES.get(t, [t])


def matches(job: Dict, keywords: List[str], location_terms: List[str]) -> bool:
    """AND sur la localisation (si fournie), OR sur les mots-clés (si fournis).
    La localisation passe par les équivalences FR/EN (Maroc↔Morocco↔villes…)."""
    hay = " ".join([job.get("title") or "", job.get("description") or ""]).lower()
    loc = (job.get("location") or "").lower()
    if location_terms:
        ok = any(a in loc or a in hay
                 for l in location_terms for a in _expand_location(l))
        if not ok:
            return False
    if keywords and not any(k.lower() in hay for k in keywords):
        return False
    return True


def search(profile: Dict) -> Tuple[List[Dict], List[str]]:
    """Recherche agrégée selon un profil cible. Retourne (offres, erreurs_par_source).

    profile = {
      keywords: [..], location: [..], internship_only: bool (défaut True),
      greenhouse: [boards], lever: [companies], ashby: [orgs], remoteok: bool,
      limit: int (défaut 40)
    }
    """
    profile = profile or {}
    keywords = [str(k).strip() for k in (profile.get("keywords") or []) if str(k).strip()]
    location = [str(l).strip() for l in (profile.get("location") or []) if str(l).strip()]
    internship_only = profile.get("internship_only", True)
    limit = max(1, min(int(profile.get("limit") or 40), 200))

    offers: List[Dict] = []
    errors: List[str] = []

    for board in (profile.get("greenhouse") or []):
        jobs, err = greenhouse_jobs(str(board))
        offers += jobs
        if err:
            errors.append(err)
    for company in (profile.get("lever") or []):
        jobs, err = lever_jobs(str(company))
        offers += jobs
        if err:
            errors.append(err)
    for org in (profile.get("ashby") or []):
        jobs, err = ashby_jobs(str(org))
        offers += jobs
        if err:
            errors.append(err)
    if profile.get("remoteok"):
        jobs, err = remoteok_jobs()
        offers += jobs
        if err:
            errors.append(err)

    out = []
    seen = set()
    for j in offers:
        if not j.get("url") or j["url"] in seen:
            continue
        if internship_only and not looks_like_internship(j):
            continue
        if not matches(j, keywords, location):
            continue
        seen.add(j["url"])
        out.append(j)
        if len(out) >= limit:
            break
    return out, errors
