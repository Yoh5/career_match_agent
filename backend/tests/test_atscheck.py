# -*- coding: utf-8 -*-
"""Tests de l'audit de parsing ATS (core/atscheck) — 100 % offline, sans LLM.

L'enjeu de ces tests : prouver que l'audit détecte les pathologies qui font
recaler un CV pour de vrai (texte non extractible, lettres éclatées, mots-clés
perdus à la mise en page, coordonnées soudées ou enterrées) — et qu'il ne crie
pas au loup sur un CV sain.
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import atscheck, export  # noqa: E402

_STRUCTURED = {
    "name": "Axel AHO", "role": "AI / Agent Engineer",
    "contact": {"email": "aho.axel5@gmail.com", "phone": "+212 777076845",
                "location": "Casablanca", "linkedin": "linkedin.com/in/axelaho",
                "github": "github.com/Yoh5"},
    "summary": "Élève ingénieur en IA. Je conçois et déploie des agents LLM en production, "
               "de la conception au déploiement continu, avec Python et FastAPI.",
    "experiences": [
        {"title": "AI / Agent Engineer", "org": "Holokia", "date": "2025 - 2026",
         "stack": "Python, FastAPI, LangGraph, Docker",
         "bullets": ["Agent d'entretien RH autonome sur WhatsApp et web, déployé en production",
                     "Notation sur quatre axes et indice d'intégrité anti-triche",
                     "Mise en production continue sur Render avec Supabase et Redis"]},
        {"title": "Développeur logiciel", "org": "Orabank Bénin", "date": "2024 - 2025",
         "stack": "PHP, SQL", "bullets": ["Scripts PHP d'extraction alimentant le reporting",
                                          "Intégration de requêtes SQL et configuration réseau"]},
    ],
    "projects": [{"title": "Career Match Agent", "meta": "projet personnel", "stack": "OpenAI",
                  "bullets": ["Boucle agentique à objectifs déterministes ATS et rédaction",
                              "Audit de parsing du PDF réellement envoyé"]}],
    "education": [{"title": "Cycle ingénieur IA & Data", "meta": "HESTIM, 2025 - 2028"},
                  {"title": "Bachelor en génie logiciel", "meta": "EPITECH Bénin, 2021 - 2024"}],
    "skills": [{"group": "IA & Agents", "items": ["LLM", "LangGraph", "RAG", "Prompt engineering"]},
               {"group": "Backend", "items": ["Python", "FastAPI", "Django", "SQL"]},
               {"group": "Cloud", "items": ["Docker", "CI/CD", "AWS", "Linux"]}],
    "certifications": ["Coursera - Base de données Oracle"],
    "languages": ["Français", "Anglais"],
}


def _pdf(layout="ats"):
    return export.cv_pdf(_STRUCTURED, "", "fr", layout=layout)


# ── Extraction ──────────────────────────────────────────────────────────────

def test_extract_pdf_text_reads_generated_pdf():
    text, err = atscheck.extract_pdf_text(_pdf())
    assert err is None
    assert "Axel AHO" in text and "Holokia" in text


def test_extract_pdf_text_fails_cleanly_on_garbage():
    text, err = atscheck.extract_pdf_text(b"ceci n'est pas un PDF")
    assert err and text == ""


# ── Le CV généré par l'agent doit passer l'audit ────────────────────────────

def test_generated_ats_pdf_scores_high():
    rep = atscheck.audit(_pdf())
    assert rep["score"] >= 85, rep["issues"]
    assert rep["contact"]["email"] == "aho.axel5@gmail.com"
    assert rep["contact"]["phone"]
    assert set(rep["sections"]["found"]) == {"experience", "education", "skills"}


def test_generated_pdf_loses_no_keyword():
    kws = ["python", "fastapi", "langgraph", "docker", "sql", "llm", "rag"]
    source = " ".join(kws)
    rep = atscheck.audit(_pdf(), kws, source_text=source)
    assert rep["keyword_loss"] == []
    assert rep["ats_pct"] == 100


def test_repair_char_spacing_rebuilds_words():
    """Le texte éclaté est recollé — les mots séparés par 2 espaces le restent."""
    broken = "D é v e l o p p e m e n t  d ' u n  s y s t è m e\nP y t h o n  F a s t A P I"
    fixed, done = atscheck.repair_char_spacing(broken * 4)
    assert done
    assert "Développement d'un système" in fixed
    assert "Python FastAPI" in fixed


def test_repair_char_spacing_leaves_healthy_text_alone():
    sain = "Ingénieur IA, Python et FastAPI, déploiement continu sur Docker. " * 8
    fixed, done = atscheck.repair_char_spacing(sain)
    assert not done and fixed == sain


def test_audit_still_works_without_pdfminer(monkeypatch):
    """pdfminer.six est optionnel : absent, l'audit tourne sur pypdf et le signale."""
    monkeypatch.setattr(atscheck, "extract_pdf_text_miner",
                        lambda data: ("", "pdfminer.six non installé"))
    monkeypatch.setattr(atscheck, "ENGINES",
                        (("pypdf", atscheck.extract_pdf_text),
                         ("pdfminer", atscheck.extract_pdf_text_miner)))
    rep = atscheck.audit(_pdf())
    assert rep["engine"] == "pypdf" and rep["score"] >= 85
    assert "unavailable" in rep["engines"]["pdfminer"]


def test_audit_reports_when_no_engine_can_read_the_file():
    rep = atscheck.audit(b"ceci n'est pas un PDF")
    assert rep["score"] == 0
    assert rep["issues"][0]["type"] == "unreadable_pdf"


def test_audit_runs_every_available_engine_and_keeps_the_worst():
    rep = atscheck.audit(_pdf())
    assert rep["engine"] in rep["engines"]
    scores = [e["score"] for e in rep["engines"].values() if "score" in e]
    assert scores and rep["score"] <= min(scores) + 1        # -5 possible si les moteurs divergent


# ── Détection des pathologies ───────────────────────────────────────────────

def test_detects_pdf_without_extractable_text():
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()                                   # page blanche = CV « image »
    rep = atscheck.audit(bytes(pdf.output()))
    assert rep["score"] == 0
    assert any(i["type"] == "not_extractable" for i in rep["issues"])


def test_char_spacing_ratio_flags_letter_by_letter_text():
    exploded = " ".join("Developpement d un systeme d authentification complet par Laravel "
                        "avec Python et FastAPI sur Docker en production continue".replace(" ", ""))
    assert atscheck.char_spacing_ratio(exploded) > 0.9
    normal = ("Développement d'un système d'authentification complet en Laravel, "
              "avec Python et FastAPI, déployé sur Docker. " * 4)
    assert atscheck.char_spacing_ratio(normal) < 0.1


def test_audit_flags_char_spacing_as_critical():
    exploded = " ".join("Python FastAPI Docker Laravel MySQL production continue "
                        "ingenieur intelligence artificielle donnees".replace(" ", "")) * 3
    rep = atscheck._audit_text(exploded, 1)
    issue = [i for i in rep["issues"] if i["type"] == "char_spacing"]
    assert issue and issue[0]["severity"] == "critical"


def test_detects_keyword_loss_between_source_and_pdf():
    source = ("Python FastAPI LangGraph Kubernetes Terraform. "        # 5 mots-clés côté source
              "Ingénieur en intelligence artificielle, conception et déploiement d'agents "
              "autonomes, mise en production continue et supervision des traitements.")
    partial = {"name": "Axel AHO", "contact": {"email": "a@b.co", "phone": "+212 777076845"},
               # le PDF ne porte que 2 des 5 mots-clés : les 3 autres sont « perdus »
               "summary": "Ingénieur en intelligence artificielle, conception et déploiement "
                          "d'agents autonomes, mise en production continue et supervision des "
                          "traitements. Stack Python et FastAPI uniquement."}
    rep = atscheck.audit(export.cv_pdf(partial, "", "fr"),
                         ["python", "fastapi", "langgraph", "kubernetes", "terraform"],
                         source_text=source)
    assert set(rep["keyword_loss"]) == {"langgraph", "kubernetes", "terraform"}
    assert any(i["type"] == "keyword_loss" and i["severity"] == "critical" for i in rep["issues"])


def test_detects_glued_contact():
    rep = atscheck._audit_text("Axel AHOaho.axel5@gmail.com +212 777076845\n"
                               "Expérience\nFormation\nCompétences\n2024 2025", 1)
    assert any(i["type"] == "glued_contact" for i in rep["issues"])


def test_detects_buried_contact():
    body = "Réalisations diverses sur des projets backend et data. " * 12
    rep = atscheck._audit_text(body + "\nAxel AHO\nmail@exemple.com\n+212 777076845", 1)
    assert any(i["type"] == "contact_buried" for i in rep["issues"])


def test_detects_column_interleave():
    line = ("Agent d'entretien RH autonome déployé en production sur Render COMPÉTENCES "
            "Python, SQL, Docker")
    rep = atscheck._audit_text(line, 1)
    assert any(i["type"] == "column_interleave" for i in rep["issues"])


def test_detects_glued_lines_without_flagging_camelcase_brands():
    ok = "FastAPI GitHub LangGraph JavaScript PostgreSQL " * 3
    assert len(atscheck._GLUED_CASE.findall(ok)) == 0
    glued = "parLaravel donneesIntegration reportingConfiguration"
    assert len(atscheck._GLUED_CASE.findall(glued)) == 3


def test_missing_sections_are_reported():
    rep = atscheck._audit_text("Axel AHO\nmail@exemple.com\n+212 777076845\n"
                               "Quelques lignes sans aucun intitulé standard.\n2024 2025", 1)
    assert any(i["type"] == "missing_sections" for i in rep["issues"])


# ── Comparaison des deux mises en page ──────────────────────────────────────

def test_compare_layouts_audits_both_and_recommends():
    res = atscheck.compare_layouts(_STRUCTURED, "", "fr", ["python", "fastapi", "docker"])
    assert set(res) == {"ats", "designed", "recommended"}
    assert res["recommended"] in ("ats", "designed")
    assert res["ats"]["score"] >= res["designed"]["score"] or res["recommended"] == "designed"
    for layout in ("ats", "designed"):
        assert "text" not in res[layout]              # rapport compact
        assert res[layout]["bytes"] > 800


def test_compare_layouts_prefers_ats_on_a_tie():
    res = atscheck.compare_layouts(_STRUCTURED, "", "fr")
    if res["ats"]["score"] == res["designed"]["score"]:
        assert res["recommended"] == "ats"
