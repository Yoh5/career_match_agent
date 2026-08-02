# -*- coding: utf-8 -*-
"""Tests de la qualité rédactionnelle déterministe (core/quality) — sans LLM."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import quality  # noqa: E402

_GOOD_FR = (
    "Madame, Monsieur,\n\n"
    "Actuellement en dernière année d'école d'ingénieur, je souhaite rejoindre votre équipe "
    "en tant que stagiaire en intelligence artificielle. Mon parcours m'a conduit à concevoir "
    "des agents autonomes fondés sur des modèles de langage, en Python et FastAPI.\n\n"
    "Au cours de mon stage précédent, j'ai développé un agent conversationnel de présélection "
    "des candidatures, déployé et utilisé quotidiennement par les équipes de recrutement. "
    "Cette expérience m'a appris à livrer un service fiable, testé et documenté, dans un cadre "
    "exigeant où la qualité des réponses conditionnait la confiance des utilisateurs.\n\n"
    "Votre offre m'intéresse particulièrement pour la dimension produit qu'elle porte, que je "
    "retrouve dans mes propres réalisations. Je serais ravi de vous exposer ma démarche et mes "
    "résultats lors d'un entretien, à votre convenance.\n\n"
    "Cordialement,\nAxel AHO"
)


def test_clean_letter_scores_high():
    r = quality.score(_GOOD_FR, "fr", "letter")
    assert r["score"] >= 95 and r["issues"] == []


def test_detects_placeholders():
    txt = _GOOD_FR.replace("votre équipe", "[Entreprise]") + "\n\nXXX à compléter"
    found = [i for i in quality.issues(txt, "fr") if i["type"] == "placeholder"]
    assert found and found[0]["severity"] == "critical"
    assert quality.score(txt, "fr")["score"] < 80


def test_markdown_link_is_not_a_placeholder():
    txt = _GOOD_FR + "\n\nPortfolio : [axel.dev](https://axel.dev)"
    assert not [i for i in quality.issues(txt, "fr") if i["type"] == "placeholder"]


def test_detects_language_mix_french_letter_with_english():
    txt = ("Madame, Monsieur,\n\nJe suis très motivé par ce poste. I have been working on "
           "machine learning projects for the last two years and I would like to join your "
           "team because it is the best place to grow.\n\nCordialement,\nAxel")
    issues = [i for i in quality.issues(txt, "fr") if i["type"] == "language_mix"]
    assert issues and issues[0]["severity"] in ("high", "critical")


def test_english_technical_terms_do_not_trigger_language_mix():
    """Un CV français peut citer Machine Learning / Data Scientist sans être « mélangé »."""
    txt = ("Ingénieur en intelligence artificielle, je conçois des pipelines de Machine Learning "
           "et des agents LLM. J'ai occupé le poste de Data Scientist chez Holokia, où j'ai mis "
           "en production des modèles de Deep Learning avec Python, FastAPI et Docker. "
           "Mes travaux portent sur le Natural Language Processing et le Prompt Engineering.")
    assert quality.language_mix(txt, "fr")["foreign_pct"] < 12
    assert not [i for i in quality.issues(txt, "fr", "cv") if i["type"] == "language_mix"]


def test_short_text_language_verdict_is_not_reliable():
    assert quality.language_mix("Bonjour, the team.", "fr")["reliable"] is False
    assert not [i for i in quality.issues("Bonjour the team", "fr") if i["type"] == "language_mix"]


def test_detects_typos_and_repeated_words():
    txt = _GOOD_FR.replace("Mon parcours", "Mon mon parcours").replace("langage,", "langage ,")
    types = {i["type"] for i in quality.issues(txt, "fr")}
    assert "repeated_word" in types and "space_before_punct" in types


def test_detects_llm_preamble_and_code_fence():
    txt = "Voici la lettre de motivation :\n\n```\n" + _GOOD_FR + "\n```"
    types = {i["type"] for i in quality.issues(txt, "fr")}
    assert "llm_preamble" in types and "code_fence" in types


def test_letter_length_bounds():
    assert any(i["type"] == "too_short" for i in quality.issues("Bonjour, je postule.", "fr", "letter"))
    assert any(i["type"] == "too_long" for i in quality.issues("mot " * 700, "fr", "letter"))
    # un CV n'est pas jugé sur la longueur d'une lettre
    assert not [i for i in quality.issues("mot " * 700, "fr", "cv") if i["type"] in ("too_short", "too_long")]


def test_score_is_bounded_and_ordered():
    awful = "Voici :\n[Nom] XXX  the and with for this that have been from will your ,bad  ."
    r = quality.score(awful, "fr")
    assert 0 <= r["score"] <= 100
    sev = [i["severity"] for i in r["issues"]]
    assert sev == sorted(sev, key=lambda s: ["critical", "high", "medium", "low"].index(s))


def test_normalize_fixes_mechanical_issues():
    raw = "```markdown\nVoici la lettre :\nBonjour , je  postule.\n```"
    out = quality.normalize(raw, "fr")
    assert "```" not in out and "Voici la lettre" not in out
    assert "Bonjour, je postule" in out          # espace avant virgule + double espace corrigés


def test_normalize_adds_french_spacing_only_in_french():
    assert quality.normalize("Objectif: réussir!", "fr") == "Objectif : réussir !"
    assert quality.normalize("Goal: succeed!", "en") == "Goal: succeed!"


def test_normalize_is_idempotent():
    once = quality.normalize(_GOOD_FR, "fr")
    assert quality.normalize(once, "fr") == once
