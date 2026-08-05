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
         "iterations": [{}], "unsupported_final": [],
         "quality_start": 90, "quality_final": 98, "quality_issues": []}, None))
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
         "iterations": [{}], "unsupported_final": [],
         "quality_start": 90, "quality_final": 98, "quality_issues": []}, None))
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


# ── Audit de parsing ATS ────────────────────────────────────────────────────

_STRUCTURED = {
    "name": "Axel AHO", "role": "AI / Agent Engineer",
    "contact": {"email": "aho.axel5@gmail.com", "phone": "+212 777076845", "location": "Casablanca"},
    "summary": "Élève ingénieur IA, agents LLM en production, Python et FastAPI, "
               "déploiement continu et supervision des traitements.",
    "experiences": [{"title": "AI Engineer", "org": "Holokia", "date": "2025 - 2026",
                     "stack": "Python, FastAPI",
                     "bullets": ["Agent d'entretien RH autonome déployé en production",
                                 "Notation déterministe et indice d'intégrité"]}],
    "education": [{"title": "Cycle ingénieur IA", "meta": "HESTIM 2025 - 2028"}],
    "skills": [{"group": "Backend", "items": ["Python", "FastAPI", "Docker"]}],
}


def test_extract_cv_repairs_and_warns_on_letter_by_letter_pdf():
    """Un PDF extrait lettre par lettre est recollé, et l'utilisateur est prévenu."""
    from core import atscheck
    broken = ("D é v e l o p p e m e n t  d ' a g e n t s  L L M\n"
              "P y t h o n  F a s t A P I  D o c k e r\n") * 6
    fixed, repaired = atscheck.repair_char_spacing(broken)
    assert repaired and "Python FastAPI Docker" in fixed
    r = client.post("/extract-cv", files={"file": ("cv.txt", broken.encode("utf-8"), "text/plain")})
    d = r.json()
    assert "Développement d'agents LLM" in d["cv_text"]
    assert d["notes"] and "lettre par lettre" in d["notes"][0]


def test_extract_cv_leaves_a_healthy_cv_untouched():
    r = client.post("/extract-cv", files={"file": ("cv.txt", _CV.encode("utf-8"), "text/plain")})
    assert r.json()["notes"] == []


def test_ats_check_rejects_non_pdf():
    r = client.post("/ats-check", files={"file": ("cv.txt", b"pas un pdf", "text/plain")})
    assert r.status_code == 400


def test_ats_check_reports_on_a_real_pdf():
    """Le CV généré par l'app doit passer son propre audit — sans clé LLM."""
    from core import export
    pdf = export.cv_pdf(_STRUCTURED, "", "fr", layout="ats")
    r = client.post("/ats-check", files={"file": ("cv.pdf", pdf, "application/pdf")})
    assert r.status_code == 200
    rep = r.json()["report"]
    assert rep["score"] >= 80
    assert rep["contact"]["email"] == "aho.axel5@gmail.com"
    assert "text" not in rep                      # réponse compacte


def test_ats_check_flags_an_unreadable_pdf():
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    r = client.post("/ats-check", files={"file": ("vide.pdf", bytes(pdf.output()), "application/pdf")})
    rep = r.json()["report"]
    assert rep["score"] == 0
    assert any(i["type"] == "not_extractable" for i in rep["issues"])


def test_ats_compare_returns_both_layouts():
    r = client.post("/ats-check/compare", json={"cv_markdown": "# Axel AHO",
                                                "cv_structured": _STRUCTURED, "lang": "fr"})
    assert r.status_code == 200
    d = r.json()
    assert d["recommended"] in ("ats", "designed")
    assert d["ats"]["score"] and d["designed"]["score"]


def test_export_cv_pdf_defaults_to_the_ats_layout():
    r = client.post("/export/cv.pdf", json={"cv_markdown": "# Axel AHO\n## Compétences\n- Python",
                                            "cv_structured": _STRUCTURED, "lang": "fr"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert "_ATS.pdf" in r.headers["content-disposition"]
    r2 = client.post("/export/cv.pdf", json={"cv_markdown": "# Axel AHO",
                                             "cv_structured": _STRUCTURED, "layout": "designed"})
    assert "_design.pdf" in r2.headers["content-disposition"]
    assert r2.content != r.content


def test_tailored_cv_includes_the_parse_report(monkeypatch):
    """Le contrôle de bout en bout : le PDF réellement téléchargeable est audité."""
    _enable_llm(monkeypatch)
    monkeypatch.setattr(appmod.agent, "optimize_cv", lambda *a, **k: (
        {"cv_markdown": "# Axel AHO\n## Compétences\n- Python", "ats_start": 60, "ats_final": 90,
         "ats_weighted_final": 93, "critical_missing": [], "keywords": ["python", "fastapi"],
         "iterations": [{}], "unsupported_final": [],
         "quality_start": 90, "quality_final": 98, "quality_issues": []}, None))
    monkeypatch.setattr(appmod.agent, "cv_to_structured", lambda *a, **k: (_STRUCTURED, None))
    d = client.post("/tailored-cv", json={"cv_text": _CV, "offer_text": _OFFER}).json()
    assert d["ats_weighted_final"] == 93
    assert d["ats_parse"]["score"] >= 80
    assert d["ats_parse"]["keyword_loss"] == []


# ── E-mail de candidature ───────────────────────────────────────────────────

def test_outreach_email_endpoint(monkeypatch):
    _enable_llm(monkeypatch)
    monkeypatch.setattr(appmod.agent, "outreach_email", lambda *a, **k: (
        {"subject": "Candidature — Stage IA", "body": "Bonjour,\n\nJe candidate.\n\nAxel",
         "quality": 96, "quality_issues": [], "unsupported": []}, None))
    r = client.post("/outreach-email", json={"cv_text": _CV, "offer_text": _OFFER})
    assert r.status_code == 200
    d = r.json()
    assert d["subject"].startswith("Candidature") and "Je candidate" in d["body"]


def test_outreach_email_uses_the_saved_template_as_style_guide(monkeypatch, tmp_path):
    _enable_llm(monkeypatch)
    monkeypatch.setenv("CAREER_TEMPLATES_PATH", str(tmp_path / "tpl.json"))
    appmod.templates.save({"email": "Toujours signer 'Bien à vous'."})
    captured = {}
    def _cap(cv, offer, lang, tone, **k):
        captured.update(k)
        return ({"subject": "s", "body": "b", "quality": 90,
                 "quality_issues": [], "unsupported": []}, None)
    monkeypatch.setattr(appmod.agent, "outreach_email", _cap)
    client.post("/outreach-email", json={"cv_text": _CV, "offer_text": _OFFER})
    assert "Bien à vous" in captured["style_notes"]


def test_export_email_eml_downloads():
    r = client.post("/export/email.eml", json={"subject": "Candidature", "body": "Bonjour,\n\nMerci."})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("message/rfc822")
    assert b"Subject: Candidature" in r.content


def test_export_email_rejects_empty_body():
    assert client.post("/export/email.eml", json={"subject": "x", "body": " "}).status_code == 422
