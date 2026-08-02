# -*- coding: utf-8 -*-
"""Tests du sourcing d'offres (core/sources) — HTTP monkeypatché, sans réseau."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import sources  # noqa: E402


_GH = {"jobs": [
    {"title": "Stage Data Scientist", "absolute_url": "https://gh.io/1",
     "location": {"name": "Paris"}, "content": "&lt;p&gt;Stage de 6 mois&lt;/p&gt;"},
    {"title": "Senior Backend Engineer", "absolute_url": "https://gh.io/2",
     "location": {"name": "Paris"}, "content": "CDI"},
]}
_LEVER = [
    {"text": "Marketing Intern", "hostedUrl": "https://lv.io/1",
     "categories": {"location": "Remote", "commitment": "Internship"},
     "descriptionPlain": "Join our growth team"},
]
_ASHBY = {"jobs": [
    {"title": "Machine Learning Internship", "jobUrl": "https://as.io/1",
     "location": "Casablanca", "descriptionHtml": "<b>PFE</b> 6 months"},
]}
_ROK = [
    {"legal": "notice"},  # 1er élément = mentions légales, sans "position"
    {"position": "AI Intern", "url": "https://rok.io/1", "company": "Acme",
     "location": "Remote", "description": "internship program"},
]


def _fake_get(payloads):
    def fake(url, timeout=20):
        for frag, data in payloads.items():
            if frag in url:
                return data, None
        return None, "HTTP 404"
    return fake


def test_greenhouse_normalizes_jobs(monkeypatch):
    monkeypatch.setattr(sources, "_get_json", _fake_get({"greenhouse.io": _GH}))
    jobs, err = sources.greenhouse_jobs("acme")
    assert err == "" and len(jobs) == 2
    assert jobs[0]["source"] == "greenhouse" and jobs[0]["location"] == "Paris"
    assert "<" not in jobs[0]["description"]        # HTML nettoyé


def test_lever_and_ashby_normalize(monkeypatch):
    monkeypatch.setattr(sources, "_get_json", _fake_get({"lever.co": _LEVER, "ashbyhq.com": _ASHBY}))
    lv, _ = sources.lever_jobs("acme")
    asb, _ = sources.ashby_jobs("acme")
    assert lv[0]["title"] == "Marketing Intern" and "Internship" in lv[0]["description"]
    assert asb[0]["url"] == "https://as.io/1" and "PFE" in asb[0]["description"]


def test_remoteok_skips_legal_notice(monkeypatch):
    monkeypatch.setattr(sources, "_get_json", _fake_get({"remoteok.com": _ROK}))
    jobs, err = sources.remoteok_jobs()
    assert err == "" and len(jobs) == 1 and jobs[0]["company"] == "Acme"


def test_invalid_slug_rejected_without_network():
    jobs, err = sources.greenhouse_jobs("bad slug/../x")
    assert jobs == [] and "invalide" in err


def test_source_error_is_fail_open(monkeypatch):
    monkeypatch.setattr(sources, "_get_json", lambda *a, **k: (None, "timeout"))
    jobs, err = sources.lever_jobs("acme")
    assert jobs == [] and "timeout" in err


def test_looks_like_internship_title_and_description():
    assert sources.looks_like_internship({"title": "Stage Data", "description": ""})
    assert sources.looks_like_internship({"title": "ML role", "description": "great internship program"})
    assert not sources.looks_like_internship({"title": "Senior Engineer", "description": "CDI temps plein"})


def test_matches_keywords_and_location():
    job = {"title": "Stage Data Scientist", "description": "python pandas", "location": "Paris, France"}
    assert sources.matches(job, ["data"], [])
    assert sources.matches(job, [], ["paris"])
    assert not sources.matches(job, ["marketing"], [])
    assert not sources.matches(job, ["data"], ["berlin"])


def test_location_aliases_morocco_and_remote():
    """Sources internationales : « Maroc » doit trouver Casablanca/Morocco, et vice-versa."""
    casa = {"title": "Stage IA", "description": "", "location": "Casablanca"}
    morocco = {"title": "Data Intern", "description": "", "location": "Morocco (hybrid)"}
    anywhere = {"title": "Intern", "description": "", "location": "Anywhere"}
    assert sources.matches(casa, [], ["Maroc"])
    assert sources.matches(morocco, [], ["maroc"])
    assert sources.matches(casa, [], ["Morocco"])
    assert sources.matches(anywhere, [], ["Remote"])
    assert not sources.matches(casa, [], ["France"])


def test_search_aggregates_filters_and_dedupes(monkeypatch):
    monkeypatch.setattr(sources, "_get_json", _fake_get({
        "greenhouse.io": _GH, "lever.co": _LEVER, "ashbyhq.com": _ASHBY, "remoteok.com": _ROK,
    }))
    offers, errors = sources.search({
        "keywords": [], "internship_only": True,
        "greenhouse": ["acme"], "lever": ["acme"], "ashby": ["acme"], "remoteok": True,
    })
    assert errors == []
    urls = [o["url"] for o in offers]
    assert "https://gh.io/2" not in urls                 # senior CDI filtré
    assert len(urls) == len(set(urls)) == 4              # stages uniquement, dédupliqués


def test_search_respects_limit_and_keywords(monkeypatch):
    monkeypatch.setattr(sources, "_get_json", _fake_get({"greenhouse.io": _GH}))
    offers, _ = sources.search({"greenhouse": ["acme"], "keywords": ["data"], "limit": 1})
    assert len(offers) == 1 and "Data" in offers[0]["title"]
