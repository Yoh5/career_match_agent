# -*- coding: utf-8 -*-
"""Tests d'intégration des endpoints (app) — TestClient, LLM monkeypatché, sans réseau."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app as appmod  # noqa: E402
from core import agent  # noqa: E402

client = TestClient(appmod.app)

_CV = "Axel AHO. Ingénieur IA. Python, FastAPI, LangGraph. " * 2
_OFFER = "Stage AI Engineer : Python, FastAPI, Docker, LLM. " * 2


@pytest.fixture(autouse=True)
def _isolate_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_MEMORY_PATH", str(tmp_path / "mem.json"))


def _enable_llm(monkeypatch):
    monkeypatch.setattr(appmod.llm, "is_enabled", lambda: True)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and "llm_ready" in r.json()


def test_memory_empty():
    assert client.get("/memory").json()["count"] == 0


def test_extract_cv_txt():
    r = client.post("/extract-cv", files={"file": ("cv.txt", _CV.encode("utf-8"), "text/plain")})
    assert r.status_code == 200 and r.json()["chars"] > 30


def test_analyze_requires_key(monkeypatch):
    monkeypatch.setattr(appmod.llm, "is_enabled", lambda: False)
    r = client.post("/analyze", json={"cv_text": _CV, "offer_text": _OFFER})
    assert r.status_code == 503


def test_analyze_happy_path(monkeypatch):
    _enable_llm(monkeypatch)
    monkeypatch.setattr(appmod.agent, "offer_keywords", lambda *a, **k: (["python", "docker"], None))
    monkeypatch.setattr(appmod.agent, "analyze", lambda *a, **k: (
        {"fit_score": 72, "verdict": "Bon fit.", "strengths": ["Python"], "gaps": ["Docker"],
         "keywords_missing": ["docker"], "projects_to_highlight": ["Holokia"], "cv_suggestions": ["Ajoute Docker"]}, None))
    monkeypatch.setattr(appmod.agent, "recommend", lambda *a, **k: (
        {"decision": "postuler", "confidence": 80, "rationale": "ok", "action_plan": ["Ajoute Docker"]}, None))
    r = client.post("/analyze", json={"cv_text": _CV, "offer_text": _OFFER, "lang": "fr"})
    assert r.status_code == 200
    d = r.json()
    assert d["analysis"]["fit_score"] == 72
    assert d["recommendation"]["decision"] == "postuler"
    assert "ats" in d and "pct" in d["ats"]
    # la candidature a été mémorisée
    assert client.get("/memory").json()["count"] == 1


def test_tailored_cv_returns_html(monkeypatch):
    _enable_llm(monkeypatch)
    monkeypatch.setattr(appmod.agent, "optimize_cv", lambda *a, **k: (
        {"cv_markdown": "# Axel AHO\n## Compétences\n- Python", "ats_start": 60, "ats_final": 90,
         "iterations": [{}], "unsupported_final": []}, None))
    r = client.post("/tailored-cv", json={"cv_text": _CV, "offer_text": _OFFER})
    assert r.status_code == 200
    d = r.json()
    assert d["tailored_cv_markdown"].startswith("# Axel AHO")
    assert d["tailored_cv_html"].startswith("<!doctype html>")
    assert "<title>Axel AHO</title>" in d["tailored_cv_html"]
    assert d["ats_final"] == 90


def test_tailored_cv_uses_structured_layout(monkeypatch):
    _enable_llm(monkeypatch)
    monkeypatch.setattr(appmod.agent, "optimize_cv", lambda *a, **k: (
        {"cv_markdown": "# Axel AHO", "ats_start": 60, "ats_final": 90,
         "iterations": [{}], "unsupported_final": []}, None))
    monkeypatch.setattr(appmod.agent, "cv_to_structured", lambda *a, **k: (
        {"name": "Axel AHO", "skills": [{"group": "IA", "items": ["LangGraph"]}]}, None))
    r = client.post("/tailored-cv", json={"cv_text": _CV, "offer_text": _OFFER})
    html = r.json()["tailored_cv_html"]
    assert 'class="page"' in html and "<span>LangGraph</span>" in html   # mise en page deux colonnes


def test_prepare_delegates_to_orchestrator(monkeypatch):
    _enable_llm(monkeypatch)
    monkeypatch.setattr(appmod.orchestrator, "prepare_application",
                        lambda *a, **k: ({"steps": [{"tool": "finish", "result": {"done": True}}],
                                          "summary": "ok"}, None))
    r = client.post("/prepare", json={"cv_text": _CV, "offer_text": _OFFER})
    assert r.status_code == 200 and r.json()["summary"] == "ok"


def test_resolve_rejects_short_cv(monkeypatch):
    _enable_llm(monkeypatch)
    r = client.post("/analyze", json={"cv_text": "court", "offer_text": _OFFER})
    assert r.status_code == 422
