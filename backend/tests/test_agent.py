# -*- coding: utf-8 -*-
"""Tests du cœur agentique (core/agent) — LLM monkeypatché, sans réseau."""
import json
import os
import sys

_LINK_MD = """**Tech Watch Agent — agent de veille**
- Scanne 7+ sources en parallèle.
- github.com/Yoh5/agent_veille_tech

**Career Match Agent — candidature ciblée**
- Boucles agentiques à objectifs déterministes.
- github.com/Yoh5/career_match_agent
"""

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import agent  # noqa: E402

_CV = "Axel AHO. Ingénieur IA. Python, FastAPI, LangGraph. Projet: agent d'entretien Holokia."
_OFFER = "Stage AI Engineer : Python, FastAPI, LLM, agents."
_COV = {"pct": 60, "missing": ["docker"]}


def _ok(text):
    return lambda *a, **k: (text, None)


def _fail(msg="boom"):
    return lambda *a, **k: ("", msg)


# ── analyze ────────────────────────────────────────────────────

def test_analyze_parses_and_normalises(monkeypatch):
    fake = {"fit_score": 150, "verdict": "Bon fit.",
            "strengths": ["Python", "  "], "gaps": ["Docker"],
            "keywords_missing": ["docker"], "projects_to_highlight": ["Holokia"],
            "cv_suggestions": ["Ajoute Docker si tu l'as"]}
    monkeypatch.setattr(agent.llm, "complete", _ok(json.dumps(fake)))
    data, err = agent.analyze(_CV, _OFFER, _COV, "fr")
    assert err is None
    assert data["fit_score"] == 100                 # borné à 100
    assert data["strengths"] == ["Python"]          # vide filtré
    assert data["projects_to_highlight"] == ["Holokia"]


def test_analyze_llm_error(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", _fail("pas de clé"))
    data, err = agent.analyze(_CV, _OFFER, _COV, "fr")
    assert data is None and "pas de clé" in err


def test_analyze_bad_json(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", _ok("ceci n'est pas du json"))
    data, err = agent.analyze(_CV, _OFFER, _COV, "fr")
    assert data is None and err


def test_analyze_lang_selects_english_prompt(monkeypatch):
    captured = {}
    def _cap(prompt, **k):
        captured["p"] = prompt
        return (json.dumps({"fit_score": 70}), None)
    monkeypatch.setattr(agent.llm, "complete", _cap)
    agent.analyze(_CV, _OFFER, _COV, "en")
    assert "JOB OFFER" in captured["p"]              # prompt anglais


# ── cover_letter / tailored_cv ─────────────────────────────────

def test_cover_letter_ok(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", _ok("Madame, Monsieur, ..."))
    text, err = agent.cover_letter(_CV, _OFFER, "fr")
    assert err is None and text.startswith("Madame")


def test_cover_letter_error(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", _fail())
    text, err = agent.cover_letter(_CV, _OFFER, "fr")
    assert text is None and err


def test_tailored_cv_ok(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", _ok("# Axel AHO\n## Profil\n..."))
    md, err = agent.tailored_cv(_CV, _OFFER, "en")
    assert err is None and md.startswith("# Axel AHO")


# ── verify_grounding (#3) ──────────────────────────────────────

def test_verify_grounding_lists_unsupported(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", _ok(json.dumps({"unsupported": ["10 ans chez Google", "  "]})))
    res, err = agent.verify_grounding("doc", _CV, "fr")
    assert err is None and res["unsupported"] == ["10 ans chez Google"]


def test_verify_grounding_error(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", _fail("boom"))
    res, err = agent.verify_grounding("doc", _CV, "fr")
    assert res is None and err == "boom"


# ── optimize_cv : boucle generate→measure→verify→revise (#1) ────

_OPT_OFFER = "Stage : Python, FastAPI, Docker, LLM."   # keywords ATS = python, fastapi, docker, llm


def test_optimize_cv_improves_ats(monkeypatch):
    # gen initial = 2/4 mots-clés (50%), révision = 4/4 (100%), toujours fondé
    monkeypatch.setattr(agent, "tailored_cv", lambda *a, **k: ("Compétences : Python, FastAPI.", None))
    monkeypatch.setattr(agent, "verify_grounding", lambda *a, **k: ({"unsupported": []}, None))
    monkeypatch.setattr(agent, "_revise_cv", lambda *a, **k: ("Compétences : Python, FastAPI, Docker, LLM.", None))
    res, err = agent.optimize_cv(_CV, _OPT_OFFER, "fr", target=80, max_iters=2)
    assert err is None
    assert res["ats_start"] == 50 and res["ats_final"] == 100      # objectif dépassé
    assert "Docker" in res["cv_markdown"]
    assert len(res["iterations"]) >= 2


def test_optimize_cv_prefers_grounded_version(monkeypatch):
    # ATS déjà à 100% mais version initiale contient une invention ; la révision la nettoie
    monkeypatch.setattr(agent, "tailored_cv", lambda *a, **k: ("Python FastAPI Docker LLM — Directeur chez Google.", None))
    monkeypatch.setattr(agent, "verify_grounding",
                        lambda text, *a, **k: ({"unsupported": [] if "cleaned" in text else ["Directeur chez Google"]}, None))
    monkeypatch.setattr(agent, "_revise_cv", lambda *a, **k: ("Python FastAPI Docker LLM. cleaned", None))
    res, err = agent.optimize_cv(_CV, _OPT_OFFER, "fr", target=80, max_iters=2)
    assert err is None
    assert res["unsupported_final"] == []            # version retenue = sans invention
    assert "cleaned" in res["cv_markdown"]


def test_optimize_cv_failopen_on_initial_error(monkeypatch):
    monkeypatch.setattr(agent, "tailored_cv", lambda *a, **k: (None, "pas de clé"))
    res, err = agent.optimize_cv(_CV, _OPT_OFFER, "fr")
    assert res is None and err == "pas de clé"


# ── offer_keywords : extraction ATS tous domaines ──────────────

def test_offer_keywords_parses_any_domain(monkeypatch):
    fake = {"keywords": ["community management", "SEO", "Google Analytics", "  "]}
    monkeypatch.setattr(agent.llm, "complete", _ok(json.dumps(fake)))
    kws, err = agent.offer_keywords("Offre marketing digital…", "fr")
    assert err is None
    assert kws == ["community management", "SEO", "Google Analytics"]   # vides filtrés


def test_offer_keywords_failopen(monkeypatch):
    # fail-open : erreur LLM → ([], err), l'appelant retombe sur la liste tech
    monkeypatch.setattr(agent.llm, "complete", _fail("pas de clé"))
    kws, err = agent.offer_keywords("offre", "fr")
    assert kws == [] and err == "pas de clé"


# ── recommend : planification + go/no-go (#5) ──────────────────

def test_recommend_parses_and_normalises(monkeypatch):
    fake = {"decision": "Postuler", "confidence": 150,
            "rationale": "Bon fit.", "action_plan": ["Ajoute Docker", "  "]}
    monkeypatch.setattr(agent.llm, "complete", _ok(json.dumps(fake)))
    rec, err = agent.recommend({"fit_score": 78, "gaps": ["Docker"]}, {"pct": 70, "missing": ["docker"]}, "fr")
    assert err is None
    assert rec["decision"] == "postuler"          # normalisé en minuscule
    assert rec["confidence"] == 100               # borné
    assert rec["action_plan"] == ["Ajoute Docker"]


def test_recommend_error(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", _fail())
    rec, err = agent.recommend({"fit_score": 50}, {"pct": 40}, "fr")
    assert rec is None and err


# ── cv_to_structured : JSON pour la mise en page HTML ──────────

def test_cv_to_structured_parses(monkeypatch):
    fake = {"name": "Axel AHO", "role": "AI Engineer", "summary": "…",
            "experiences": [{"title": "Stage", "org": "Holokia", "bullets": ["a"]}]}
    monkeypatch.setattr(agent.llm, "complete", _ok(json.dumps(fake)))
    data, err = agent.cv_to_structured("# Axel AHO\n…", "fr")
    assert err is None and data["name"] == "Axel AHO"


def test_cv_to_structured_failopen(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", _fail("pas de clé"))
    data, err = agent.cv_to_structured("# CV", "fr")
    assert data is None and err == "pas de clé"


# ── restore_links : filet déterministe contre les URL perdues par le LLM ────

def test_restore_links_reattaches_urls_to_the_right_entry():
    """`cv_to_structured` supprime parfois les liens de dépôt en condensant.
    Sans filet, un CV d'ingénieur perd la preuve de ses projets."""
    structured = {"projects": [
        {"title": "Tech Watch Agent", "bullets": ["Scanne 7+ sources en parallèle."]},
        {"title": "Career Match Agent", "bullets": ["Boucles agentiques à objectifs déterministes."]},
    ]}
    out = agent.restore_links(structured, _LINK_MD)
    assert "github.com/Yoh5/agent_veille_tech" in out["projects"][0]["bullets"]
    assert "github.com/Yoh5/career_match_agent" in out["projects"][1]["bullets"]


def test_restore_links_is_a_noop_when_urls_already_present():
    structured = {"projects": [
        {"title": "Tech Watch Agent", "bullets": ["Scanne.", "github.com/Yoh5/agent_veille_tech"]},
        {"title": "Career Match Agent", "bullets": ["Boucles.", "github.com/Yoh5/career_match_agent"]},
    ]}
    before = [list(p["bullets"]) for p in structured["projects"]]
    out = agent.restore_links(structured, _LINK_MD)
    assert [p["bullets"] for p in out["projects"]] == before


def test_restore_links_never_invents_an_entry():
    """Une URL dont on ne sait pas à quelle entrée elle appartient est ignorée —
    on ne crée pas de projet fantôme pour la loger."""
    structured = {"projects": [{"title": "Autre projet", "bullets": ["x"]}]}
    out = agent.restore_links(structured, _LINK_MD)
    assert len(out["projects"]) == 1
    assert out["projects"][0]["bullets"] == ["x"]


def test_restore_links_tolerates_garbage():
    assert agent.restore_links(None, _LINK_MD) is None
    assert agent.restore_links({}, "") == {}
