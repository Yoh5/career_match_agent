# -*- coding: utf-8 -*-
"""Tests de la boucle ReAct (core/orchestrator) — LLM tool-calling scripté, sans réseau."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import orchestrator, agent, memory  # noqa: E402

_CV = "Axel AHO. Python, FastAPI. Projet agent d'entretien."
_OFFER = "Stage AI Engineer : Python, FastAPI, Docker."


def _script(steps):
    """Fabrique un faux complete_tools qui débite `steps` (listes de tool_calls)
    puis renvoie un message texte final."""
    calls = {"i": 0}

    def fake(messages, tools, **k):
        i = calls["i"]
        calls["i"] += 1
        if i < len(steps):
            tcs = [{"id": f"c{i}_{j}", "name": n, "arguments": a}
                   for j, (n, a) in enumerate(steps[i])]
            return {"content": None, "tool_calls": tcs}, None
        return {"content": "Candidature prête.", "tool_calls": []}, None
    return fake


def _patch_agent(monkeypatch):
    monkeypatch.setattr(agent, "offer_keywords", lambda *a, **k: (["python", "fastapi", "docker"], None))
    monkeypatch.setattr(agent, "analyze", lambda *a, **k: (
        {"fit_score": 75, "verdict": "Bon fit.", "gaps": ["Docker"],
         "projects_to_highlight": ["Holokia"], "strengths": [], "keywords_missing": [],
         "cv_suggestions": []}, None))
    monkeypatch.setattr(agent, "recommend", lambda *a, **k: (
        {"decision": "postuler", "confidence": 80, "rationale": "ok", "action_plan": ["Ajoute Docker"]}, None))
    monkeypatch.setattr(agent, "optimize_cv", lambda *a, **k: (
        {"cv_markdown": "# CV", "ats_start": 60, "ats_final": 100, "iterations": [{}],
         "unsupported_final": []}, None))
    monkeypatch.setattr(agent, "cover_letter", lambda *a, **k: ("Madame, Monsieur…", None))


def test_prepare_runs_react_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_MEMORY_PATH", str(tmp_path / "m.json"))
    _patch_agent(monkeypatch)
    monkeypatch.setattr(orchestrator.llm, "complete_tools", _script([
        [("analyze_fit", {})],
        [("recommend", {})],
        [("write_tailored_cv", {}), ("write_cover_letter", {"tone": "professionnel"})],
        [("finish", {"summary": "À postuler."})],
    ]))
    out, err = orchestrator.prepare_application(_CV, _OFFER, "", "fr")
    assert err is None
    assert out["analysis"]["fit_score"] == 75
    assert out["recommendation"]["decision"] == "postuler"
    assert out["tailored_cv"]["ats_final"] == 100
    assert out["cover_letter"].startswith("Madame")
    assert out["summary"] == "À postuler."
    assert [s["tool"] for s in out["steps"]][-1] == "finish"
    # #4 : la candidature a bien été mémorisée
    assert memory.recall(_OFFER)["recommendation"] == "postuler"


def test_prepare_llm_error_failopen(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_MEMORY_PATH", str(tmp_path / "m.json"))
    _patch_agent(monkeypatch)
    monkeypatch.setattr(orchestrator.llm, "complete_tools", lambda *a, **k: (None, "pas de clé"))
    out, err = orchestrator.prepare_application(_CV, _OFFER, "", "fr")
    assert out is None and err == "pas de clé"


def test_prepare_stops_at_finish(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_MEMORY_PATH", str(tmp_path / "m.json"))
    _patch_agent(monkeypatch)
    # finish dès le 1er tour → aucune analyse produite, mais pas d'erreur
    monkeypatch.setattr(orchestrator.llm, "complete_tools",
                        _script([[("finish", {"summary": "Stop."})]]))
    out, err = orchestrator.prepare_application(_CV, _OFFER, "", "fr")
    assert err is None and out["summary"] == "Stop."
    assert len(out["steps"]) == 1
