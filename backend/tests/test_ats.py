# -*- coding: utf-8 -*-
"""Tests du signal ATS déterministe (core/ats) — sans réseau."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import ats  # noqa: E402


def test_extract_keywords_finds_tech_terms():
    offer = "Recherche stage en Python, FastAPI et Docker. Connaissances LLM appréciées."
    kws = ats.extract_keywords(offer)
    for t in ("python", "fastapi", "docker", "llm"):
        assert t in [k.lower() for k in kws]


def test_extract_keywords_word_boundary_no_false_positive():
    # "storage" ne doit PAS matcher "rag" ; "good" ne doit PAS matcher "go"
    offer = "Cloud storage, good practices, réseau."
    kws = [k.lower() for k in ats.extract_keywords(offer)]
    assert "rag" not in kws
    assert "go" not in kws


def test_extract_keywords_extra_from_llm():
    kws = ats.extract_keywords("Poste autour de Streamlit et RAG.", extra=["streamlit"])
    low = [k.lower() for k in kws]
    assert "streamlit" in low
    assert "rag" in low


def test_coverage_pct_and_lists():
    cov = ats.coverage("J'ai fait du Python et du Docker.", ["python", "docker", "kubernetes", "aws"])
    assert cov["pct"] == 50
    assert set(cov["matched"]) == {"python", "docker"}
    assert set(cov["missing"]) == {"kubernetes", "aws"}


def test_coverage_empty_keywords():
    assert ats.coverage("peu importe", []) == {"matched": [], "missing": [], "pct": 0}
