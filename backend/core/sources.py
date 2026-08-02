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

# Catalogue des sources QUE L'AGENT PROPOSE (boards publics vérifiés — l'utilisateur
# coche tout, une seule, ou plusieurs ; il peut aussi ajouter ses propres slugs).
CATALOG = [
    {"kind": "greenhouse", "slug": "doctolib",   "name": "Doctolib",   "note": "santé/tech, Paris — publie beaucoup de stages"},
    {"kind": "greenhouse", "slug": "datadog",    "name": "Datadog",    "note": "cloud/observabilité, Paris/international"},
    {"kind": "greenhouse", "slug": "gitlab",     "name": "GitLab",     "note": "dev tools, full remote"},
    {"kind": "greenhouse", "slug": "stripe",     "name": "Stripe",     "note": "fintech, international"},
    {"kind": "greenhouse", "slug": "duolingo",   "name": "Duolingo",   "note": "edtech/IA"},
    {"kind": "greenhouse", "slug": "cloudflare", "name": "Cloudflare", "note": "infra/réseau, international"},
    {"kind": "greenhouse", "slug": "dataiku",    "name": "Dataiku",    "note": "IA/data, Paris"},
    {"kind": "greenhouse", "slug": "mirakl",     "name": "Mirakl",     "note": "marketplace SaaS, Paris"},
    {"kind": "lever",      "slug": "swile",      "name": "Swile",      "note": "fintech RH, France"},
    {"kind": "lever",      "slug": "aircall",    "name": "Aircall",    "note": "SaaS télécom, Paris"},
    {"kind": "lever",      "slug": "ledger",     "name": "Ledger",     "note": "crypto/hardware, Paris"},
    {"kind": "lever",      "slug": "qonto",      "name": "Qonto",      "note": "néobanque pro, Paris"},
    {"kind": "ashby",      "slug": "linear",     "name": "Linear",     "note": "dev tools, remote"},
    {"kind": "ashby",      "slug": "ramp",       "name": "Ramp",       "note": "fintech, US/remote"},
    {"kind": "ashby",      "slug": "pennylane",  "name": "Pennylane",  "note": "fintech compta, Paris"},
    {"kind": "ashby",      "slug": "deel",       "name": "Deel",       "note": "RH global, remote"},
    {"kind": "ashby",      "slug": "sorare",     "name": "Sorare",     "note": "gaming/web3, Paris"},
    {"kind": "remoteok",   "slug": "remoteok",   "name": "RemoteOK",   "note": "agrégateur 100% remote (accessible depuis le Maroc)"},
    {"kind": "jobicy",     "slug": "france",     "name": "Jobicy (géo France)", "note": "agrégateur remote, filtre France/EMEA"},
    {"kind": "arbeitnow",  "slug": "arbeitnow",  "name": "Arbeitnow",  "note": "agrégateur Europe (dont France)"},
    {"kind": "rss",        "slug": "https://www.novojob.com/rss", "name": "Novojob (Afrique/Maghreb)",
     "note": "job board Afrique dont Maroc — flux parfois lent/indisponible"},
]


def catalog() -> List[Dict]:
    """Sources disponibles côté agent (l'UI les propose en cases à cocher)."""
    return CATALOG


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


def jobicy_jobs(geo: str = "") -> Tuple[List[Dict], str]:
    """Agrégateur remote Jobicy — API publique documentée (geo : france, emea…)."""
    url = "https://jobicy.com/api/v2/remote-jobs?count=50"
    if _valid_slug(geo):
        url += f"&geo={geo.strip().lower()}"
    data, err = _get_json(url)
    if err:
        return [], f"jobicy — {err}"
    jobs = []
    for j in (data or {}).get("jobs", []):
        jobs.append({
            "source": "jobicy", "company": (j.get("companyName") or "").strip(),
            "title": (j.get("jobTitle") or "").strip(),
            "url": j.get("url") or "",
            "location": (j.get("jobGeo") or "Remote").strip(),
            "description": _strip_html((j.get("jobExcerpt") or "") + " " + (j.get("jobLevel") or ""))[:6000],
        })
    return jobs, ""


def arbeitnow_jobs() -> Tuple[List[Dict], str]:
    """Agrégateur Europe Arbeitnow — API publique (France incluse)."""
    data, err = _get_json("https://www.arbeitnow.com/api/job-board-api")
    if err:
        return [], f"arbeitnow — {err}"
    jobs = []
    for j in (data or {}).get("data", []):
        jobs.append({
            "source": "arbeitnow", "company": (j.get("company_name") or "").strip(),
            "title": (j.get("title") or "").strip(),
            "url": j.get("url") or "",
            "location": (j.get("location") or ("Remote" if j.get("remote") else "")).strip(),
            "description": _strip_html((j.get("description") or "") + " " + " ".join(j.get("job_types") or []))[:6000],
        })
    return jobs, ""


def _get_text(url: str, timeout: int = 20):
    """GET texte brut (flux RSS). Isolé pour être monkeypatché dans les tests."""
    try:
        import httpx
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (CareerMatchAgent)"}) as client:
            r = client.get(url)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.text, None
    except Exception as e:
        return None, str(e)


def rss_jobs(feed_url: str) -> Tuple[List[Dict], str]:
    """Connecteur RSS générique — branche n'importe quel flux d'offres (Novojob
    Afrique/Maghreb, boards d'écoles, HelloWork…). Parse tolérant (CDATA ok)."""
    u = (feed_url or "").strip()
    if not re.match(r"^https?://", u, re.IGNORECASE):
        return [], f"URL de flux RSS invalide : {feed_url!r}"
    text, err = _get_text(u)
    if err:
        return [], f"rss:{u} — {err}"
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", u).split("/")[0])

    def _tag(block, name):
        m = re.search(rf"<{name}[^>]*>(?:\s*<!\[CDATA\[)?(.*?)(?:\]\]>\s*)?</{name}>", block, re.S | re.I)
        return (m.group(1).strip() if m else "")

    jobs = []
    for item in re.findall(r"<item[ >](.*?)</item>", text or "", re.S | re.I):
        title = _strip_html(_tag(item, "title"))
        link = _tag(item, "link")
        if not title or not link.startswith("http"):
            continue
        jobs.append({
            "source": f"rss:{host}", "company": host,
            "title": title, "url": link,
            "location": _strip_html(_tag(item, "category")),
            "description": _strip_html(_tag(item, "description"))[:6000],
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


def rank_offers(offers: List[Dict], target_text: str = "", cv_text: str = "",
                extra_keywords: List[str] = None) -> List[Dict]:
    """Classe les offres par pertinence — déterministe, sans réseau.

    match_pct = mélange de :
      - couverture des mots-clés de la RECHERCHE (description du stage voulu
        + mots-clés, enrichis par le LLM via `extra_keywords` si dispo) dans l'offre ;
      - part des mots-clés de L'OFFRE que le CV possède déjà (fit candidat).
    Ajoute `match_pct` à chaque offre et trie par pertinence décroissante.
    """
    from core import ats
    target_kw = ats.extract_keywords(target_text or "", extra=extra_keywords) if (target_text or extra_keywords) else []
    for o in offers or []:
        hay = " ".join([o.get("title") or "", o.get("description") or ""])
        parts = []
        if target_kw:
            parts.append(ats.coverage(hay, target_kw)["pct"])
        if cv_text and len(cv_text.strip()) >= 30:
            offer_kw = ats.extract_keywords(hay)
            if offer_kw:
                parts.append(ats.coverage(cv_text, offer_kw)["pct"])
        o["match_pct"] = round(sum(parts) / len(parts)) if parts else None
    return sorted(offers or [], key=lambda o: (o.get("match_pct") is not None, o.get("match_pct") or 0),
                  reverse=True)


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
    if profile.get("jobicy"):
        geo = profile["jobicy"] if isinstance(profile["jobicy"], str) else ""
        jobs, err = jobicy_jobs(geo)
        offers += jobs
        if err:
            errors.append(err)
    if profile.get("arbeitnow"):
        jobs, err = arbeitnow_jobs()
        offers += jobs
        if err:
            errors.append(err)
    for feed in (profile.get("rss") or []):
        jobs, err = rss_jobs(str(feed))
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
