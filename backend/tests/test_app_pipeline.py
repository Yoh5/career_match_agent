# -*- coding: utf-8 -*-
"""Tests d'intégration des endpoints pipeline/templates/outreach — sans réseau."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app as appmod  # noqa: E402

client = TestClient(appmod.app)

_CV = "Axel AHO. Ingénieur IA. Python, FastAPI, LangGraph, agents LLM. " * 2


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_PIPELINE_PATH", str(tmp_path / "pipe.json"))
    monkeypatch.setenv("CAREER_TEMPLATES_PATH", str(tmp_path / "tpl.json"))
    monkeypatch.setenv("CAREER_MEMORY_PATH", str(tmp_path / "mem.json"))
    monkeypatch.delenv("LEMLIST_API_KEY", raising=False)


def _seed_offer(monkeypatch):
    """Passe par /source avec le sourcing monkeypatché → 1 offre dans le pipeline."""
    monkeypatch.setattr(appmod.sources, "search", lambda profile: ([{
        "source": "greenhouse", "company": "acme", "title": "Stage IA",
        "url": "https://x.io/1", "location": "Casablanca",
        "description": "Stage PFE 6 mois : Python, FastAPI, agents LLM. " * 3,
    }], []))
    r = client.post("/source", json={"greenhouse": ["acme"], "keywords": ["ia"]})
    assert r.status_code == 200
    return r.json()["items"][0]["id"]


def test_source_requires_at_least_one_source():
    assert client.post("/source", json={"keywords": ["ia"]}).status_code == 422


def test_source_adds_to_pipeline(monkeypatch):
    _seed_offer(monkeypatch)
    d = client.get("/pipeline").json()
    assert d["stats"]["total"] == 1 and d["items"][0]["status"] == "sourced"


def test_pipeline_status_update_and_validation(monkeypatch):
    oid = _seed_offer(monkeypatch)
    assert client.post(f"/pipeline/{oid}/status", json={"status": "skipped"}).status_code == 200
    assert client.post(f"/pipeline/{oid}/status", json={"status": "zzz"}).status_code == 422
    assert client.post("/pipeline/unknown/status", json={"status": "sent"}).status_code == 404


def test_pipeline_analyze(monkeypatch):
    oid = _seed_offer(monkeypatch)
    monkeypatch.setattr(appmod.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(appmod.agent, "offer_keywords", lambda *a, **k: (["python"], None))
    monkeypatch.setattr(appmod.agent, "analyze",
                        lambda *a, **k: ({"fit_score": 78, "verdict": "Bon fit", "strengths": [],
                                          "gaps": [], "projects_to_highlight": [], "cv_suggestions": [],
                                          "keywords_missing": []}, None))
    monkeypatch.setattr(appmod.agent, "recommend",
                        lambda *a, **k: ({"decision": "postuler", "confidence": 80,
                                          "rationale": "ok", "action_plan": []}, None))
    r = client.post(f"/pipeline/{oid}/analyze", json={"cv_text": _CV})
    assert r.status_code == 200
    assert r.json()["analysis"]["fit_score"] == 78
    it = client.get(f"/pipeline/{oid}").json()
    assert it["status"] == "analyzed" and it["fit_score"] == 78 and it["decision"] == "postuler"


def test_pipeline_prepare_builds_full_dossier(monkeypatch):
    oid = _seed_offer(monkeypatch)
    monkeypatch.setattr(appmod.llm, "is_enabled", lambda: True)
    monkeypatch.setattr(appmod.agent, "optimize_cv",
                        lambda *a, **k: ({"cv_markdown": "# Axel AHO\nPython", "ats_start": 50,
                                          "ats_final": 85, "iterations": [], "unsupported_final": []}, None))
    monkeypatch.setattr(appmod.agent, "cv_to_structured", lambda *a, **k: (None, "off"))
    monkeypatch.setattr(appmod.agent, "cover_letter", lambda *a, **k: ("Madame, Monsieur…", None))
    monkeypatch.setattr(appmod.agent, "analyze",
                        lambda *a, **k: ({"fit_score": 80, "projects_to_highlight":
                                          ["Career Match Agent — agent IA de candidature"]}, None))
    r = client.post(f"/pipeline/{oid}/prepare",
                    json={"cv_text": _CV, "my_name": "Axel AHO", "first_name": "Marie"})
    assert r.status_code == 200
    p = r.json()["prepared"]
    assert p["cv_markdown"].startswith("# Axel")
    assert "<html" in p["cv_html"].lower() or "<!doctype" in p["cv_html"].lower() or "<div" in p["cv_html"].lower()
    assert p["cover_letter"].startswith("Madame")
    # messages rendus depuis les templates avec les infos de L'OFFRE
    msg = p["messages"]["linkedin_message"]
    assert "acme" in msg and "Stage IA" in msg and "Axel AHO" in msg and "Marie" in msg
    assert "Career Match Agent" in msg                      # highlight tiré de l'analyse
    it = client.get(f"/pipeline/{oid}").json()
    assert it["status"] == "ready" and it["ats_pct"] == 85


def test_templates_get_and_put():
    t = client.get("/templates").json()
    assert "linkedin_message" in t
    r = client.put("/templates", json={"templates": {"linkedin_invite": "Yo {first_name} !"}})
    assert r.status_code == 200 and r.json()["linkedin_invite"] == "Yo {first_name} !"


def test_outreach_status_disabled():
    d = client.get("/outreach/status").json()
    assert d["enabled"] is False


def test_outreach_send_requires_key_then_prepared(monkeypatch):
    oid = _seed_offer(monkeypatch)
    body = {"item_id": oid, "campaign_id": "c1", "email": "m@acme.com"}
    assert client.post("/outreach/send", json=body).status_code == 503       # pas de clé
    monkeypatch.setenv("LEMLIST_API_KEY", "k")
    assert client.post("/outreach/send", json=body).status_code == 422       # pas préparé
    appmod.pipeline.update(oid, prepared={"messages": {"linkedin_message": "Bonjour Marie…"}})
    sent = {}
    monkeypatch.setattr(appmod.outreach, "add_lead",
                        lambda cid, email, fields: (sent.update(cid=cid, email=email, f=fields) or {"ok": 1}, None))
    r = client.post("/outreach/send", json=body)
    assert r.status_code == 200 and sent["email"] == "m@acme.com"
    assert sent["f"]["message"].startswith("Bonjour")
    assert client.get(f"/pipeline/{oid}").json()["status"] == "sent"
