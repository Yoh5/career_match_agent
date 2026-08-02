# -*- coding: utf-8 -*-
"""Tests des boucles agentiques (optimize_cv / optimize_cover_letter) — LLM scripté.

On vérifie ce qui fait la valeur de la boucle : elle converge vers la MEILLEURE
version, ne régresse pas, ne gaspille pas d'appels, et intègre la qualité
rédactionnelle en plus de l'ATS et de l'anti-invention.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import agent, quality  # noqa: E402

_CV = ("Axel AHO. Ingénieur en intelligence artificielle. Compétences : Python, FastAPI, "
       "Docker, agents LLM, LangGraph. Expérience : stage chez Holokia sur un agent "
       "d'entretien automatisé. Formation : école d'ingénieur.")
_OFFER = "Stage ingénieur IA : Python, FastAPI, Docker, agents LLM, LangGraph, PostgreSQL."

_CLEAN_LETTER = (
    "Madame, Monsieur,\n\nActuellement en dernière année d'école d'ingénieur, je souhaite "
    "rejoindre votre équipe comme stagiaire en intelligence artificielle. Mon parcours m'a "
    "conduit à concevoir des agents autonomes fondés sur des modèles de langage, en Python "
    "et FastAPI, dans un cadre exigeant.\n\nChez Holokia, j'ai développé un agent d'entretien "
    "automatisé, déployé et utilisé quotidiennement par les équipes de recrutement. Cette "
    "expérience m'a appris à livrer un service fiable, testé et documenté, et à mesurer la "
    "qualité de mes résultats plutôt qu'à les supposer.\n\nVotre offre m'intéresse pour la "
    "dimension produit qu'elle porte, que je retrouve dans mes propres réalisations. Je serais "
    "ravi de vous exposer ma démarche lors d'un entretien, à votre convenance.\n\n"
    "Cordialement,\nAxel AHO"
)


class _Script:
    """LLM factice : renvoie les textes fournis dans l'ordre, et compte les appels
    par type de prompt (pour vérifier qu'on ne gaspille pas d'appels)."""

    def __init__(self, texts, groundings=None):
        self.texts = list(texts)
        self.groundings = list(groundings or [])
        self.calls = []

    def complete(self, prompt, json_mode=False, max_tokens=1000, temperature=0.2):
        if json_mode:
            self.calls.append("json")
            if "fact-checker" in prompt or "unsupported" in prompt:
                self.calls[-1] = "grounding"
                g = self.groundings.pop(0) if self.groundings else []
                return '{"unsupported": %s}' % (str(g).replace("'", '"')), None
            return '{"keywords": []}', None
        kind = ("revise" if "CV ADAPTÉ ACTUEL" in prompt or "LETTRE ACTUELLE" in prompt
                else "proofread" if "Relis et corrige" in prompt or "Proofread" in prompt
                else "generate")
        self.calls.append(kind)
        return (self.texts.pop(0) if self.texts else "—"), None

    def count(self, kind):
        return self.calls.count(kind)


def _install(monkeypatch, script):
    monkeypatch.setattr(agent.llm, "complete", script.complete)
    return script


# ── optimize_cv ────────────────────────────────────────────────────────────

def test_cv_loop_stops_when_all_objectives_met(monkeypatch):
    """CV déjà parfait (ATS + qualité + 0 invention) → aucune révision, aucune relecture."""
    perfect = ("# Axel AHO\n## Profil\nIngénieur en intelligence artificielle.\n"
               "## Compétences\n- Python, FastAPI, Docker, LangGraph, PostgreSQL\n"
               "## Expériences\n- Agents LLM chez Holokia\n")
    s = _install(monkeypatch, _Script([perfect], groundings=[[]]))
    res, err = agent.optimize_cv(_CV, _OFFER, "fr")
    assert err is None
    assert res["cv_markdown"] == perfect.strip()
    assert len(res["iterations"]) == 1
    assert s.count("revise") == 0 and s.count("proofread") == 0
    assert s.count("grounding") == 1          # une seule vérification, pas de doublon final


def test_cv_loop_keeps_best_version_not_last(monkeypatch):
    """Si la révision dégrade (invention introduite), on garde la version antérieure."""
    good = "# Axel AHO\n## Compétences\n- Python, FastAPI, Docker, LangGraph, PostgreSQL\n"
    worse = "# Axel AHO\n## Compétences\n- Python\n## Expériences\n- Directeur chez Google\n"
    s = _install(monkeypatch, _Script([good, worse, worse], groundings=[[], ["Directeur chez Google"], []]))
    res, err = agent.optimize_cv(_CV, _OFFER, "fr", target=100, max_iters=1)
    assert err is None
    assert "Google" not in res["cv_markdown"]        # la version inventée est écartée
    assert res["unsupported_final"] == []


def test_cv_loop_stops_on_convergence(monkeypatch):
    """Une révision identique à l'existant arrête la boucle (pas de tour inutile)."""
    same = "# Axel AHO\n## Compétences\n- Python\n"
    s = _install(monkeypatch, _Script([same, same, same, same], groundings=[[], [], [], []]))
    res, err = agent.optimize_cv(_CV, _OFFER, "fr", target=100, max_iters=3)
    assert err is None
    assert len(res["iterations"]) == 1 and s.count("revise") == 1   # détecté au 1er retour


def test_cv_loop_reports_quality_and_ats(monkeypatch):
    cv = "# Axel AHO\n## Compétences\n- Python, FastAPI, Docker\n"
    _install(monkeypatch, _Script([cv], groundings=[[]]))
    res, _ = agent.optimize_cv(_CV, _OFFER, "fr")
    assert 0 <= res["quality_start"] <= 100 and 0 <= res["quality_final"] <= 100
    assert res["ats_start"] is not None and res["ats_final"] is not None
    assert "quality" in res["iterations"][0] and "ats" in res["iterations"][0]


def test_cv_loop_polishes_a_badly_written_cv(monkeypatch):
    """CV avec un défaut rédactionnel → relecture déclenchée et conservée si meilleure."""
    dirty = "# Axel AHO\n## Compétences\n- Python , FastAPI\n- Docker Docker\n"
    clean = "# Axel AHO\n## Compétences\n- Python, FastAPI\n- Docker\n"
    # 1er texte = génération, 2e = relecture
    s = _install(monkeypatch, _Script([dirty, clean], groundings=[[], []]))
    res, _ = agent.optimize_cv(_CV, _OFFER, "fr", target=0, max_iters=0)
    assert s.count("proofread") == 1
    assert res["cv_markdown"] == clean.strip()
    assert res["quality_final"] > res["quality_start"]


def test_cv_loop_discards_proofread_that_invents(monkeypatch):
    """La relecture ne doit jamais introduire d'invention : sinon on garde l'original."""
    dirty = "# Axel AHO\n## Compétences\n- Python , FastAPI\n"
    invented = "# Axel AHO\n## Compétences\n- Python, FastAPI\n## Expériences\n- CTO chez Meta\n"
    s = _install(monkeypatch, _Script([dirty, invented], groundings=[[], ["CTO chez Meta"]]))
    res, _ = agent.optimize_cv(_CV, _OFFER, "fr", target=0, max_iters=0)
    assert "Meta" not in res["cv_markdown"]


def test_cv_loop_fails_open_on_generation_error(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", lambda *a, **k: (None, "quota dépassé"))
    res, err = agent.optimize_cv(_CV, _OFFER, "fr")
    assert res is None and "quota" in err


# ── optimize_cover_letter ──────────────────────────────────────────────────

def test_letter_loop_returns_clean_letter_without_extra_calls(monkeypatch):
    s = _install(monkeypatch, _Script([_CLEAN_LETTER], groundings=[[]]))
    res, err = agent.optimize_cover_letter(_CV, _OFFER, "fr")
    assert err is None
    assert res["cover_letter"].startswith("Madame, Monsieur,")
    assert res["quality_final"] >= 95
    assert s.count("revise") == 0 and s.count("proofread") == 0


def test_letter_loop_revises_a_letter_with_placeholders(monkeypatch):
    bad = _CLEAN_LETTER.replace("votre équipe", "[Entreprise]")
    s = _install(monkeypatch, _Script([bad, _CLEAN_LETTER], groundings=[[], []]))
    res, err = agent.optimize_cover_letter(_CV, _OFFER, "fr", max_iters=1)
    assert err is None
    assert "[Entreprise]" not in res["cover_letter"]
    assert res["quality_final"] > res["quality_start"]
    assert s.count("revise") == 1


def test_letter_loop_fixes_language_mix(monkeypatch):
    mixed = ("Madame, Monsieur,\n\nJe postule à ce stage. I have been working with machine "
             "learning for two years and I would like to join your team because it is the "
             "best place for me to grow and to learn from the experts that are there.\n\n"
             "Cordialement,\nAxel")
    assert any(i["type"] == "language_mix" for i in quality.issues(mixed, "fr"))
    s = _install(monkeypatch, _Script([mixed, _CLEAN_LETTER], groundings=[[], []]))
    res, _ = agent.optimize_cover_letter(_CV, _OFFER, "fr", max_iters=1)
    assert not any(i["type"] == "language_mix" for i in quality.issues(res["cover_letter"], "fr"))


def test_letter_loop_keeps_best_when_revision_is_worse(monkeypatch):
    good = _CLEAN_LETTER.replace("votre équipe", "[X]")      # léger défaut
    worse = "Voici :\n\n[Nom] XXX  ,mauvais  ."               # bien pire
    s = _install(monkeypatch, _Script([good, worse, worse], groundings=[[], [], []]))
    res, _ = agent.optimize_cover_letter(_CV, _OFFER, "fr", max_iters=1)
    assert "XXX" not in res["cover_letter"]


def test_letter_loop_fails_open(monkeypatch):
    monkeypatch.setattr(agent.llm, "complete", lambda *a, **k: (None, "API down"))
    res, err = agent.optimize_cover_letter(_CV, _OFFER, "fr")
    assert res is None and "API down" in err
