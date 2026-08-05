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
    cov = ats.coverage("peu importe", [])
    assert cov["matched"] == [] and cov["missing"] == [] and cov["pct"] == 0
    assert cov["weighted_pct"] == 0 and cov["critical_missing"] == []


# ── Matching « comme un vrai ATS » : accents, séparateurs, pluriels, alias ──

def test_matching_folds_accents_both_ways():
    assert ats._found("modelisation", "Modélisation statistique")
    assert ats._found("modélisation", "modelisation statistique")


def test_matching_is_separator_insensitive():
    # node.js / nodejs / node js sont le même mot-clé ; idem ci/cd et cicd
    assert ats._found("node.js", "Backend en nodejs")
    assert ats._found("ci/cd", "pipelines CICD en place")
    assert ats._found("ci/cd", "intégration ci-cd")


def test_matching_tolerates_plural():
    assert ats._found("api", "conception d'APIs REST")
    assert ats._found("compétence", "compétences techniques")


def test_matching_knows_aliases():
    assert ats._found("javascript", "Maîtrise de JS")
    assert ats._found("machine learning", "projets ML supervisés")
    assert ats._found("kubernetes", "orchestration K8s")
    assert ats._found("postgresql", "base Postgres")


def test_matching_keeps_word_boundaries_despite_variants():
    # les variantes ne doivent pas rouvrir les faux positifs corrigés plus haut
    assert not ats._found("rag", "cloud storage")
    assert not ats._found("go", "good practices")


# ── Pondération : requis vs « serait un plus » ──────────────────────────────

_OFFER = """Stage Data
Profil recherché :
- Python et FastAPI obligatoires
- Docker au quotidien
Serait un plus : Kubernetes
Python reste central, Python partout.
"""


def test_keyword_weights_required_beats_nice_to_have():
    w = ats.keyword_weights(_OFFER, ["python", "kubernetes", "fastapi"])
    assert w["fastapi"]["tier"] == "required"
    assert w["kubernetes"]["tier"] == "nice"
    assert w["python"]["weight"] > w["kubernetes"]["weight"]


def test_weighted_coverage_and_critical_missing():
    kws = ["python", "fastapi", "docker", "kubernetes"]
    cov = ats.coverage("Je fais du Python et du Docker.", kws, _OFFER)
    assert cov["pct"] == 50                       # brut : 2 sur 4
    assert cov["weighted_pct"] > cov["pct"]       # pondéré : le bonus manquant pèse peu
    assert cov["critical_missing"] == ["fastapi"]  # Kubernetes n'est PAS éliminatoire


def test_weighted_pct_equals_pct_without_offer():
    kws = ["python", "docker", "aws", "azure"]
    cov = ats.coverage("Python et Docker", kws)
    assert cov["weighted_pct"] == cov["pct"]
