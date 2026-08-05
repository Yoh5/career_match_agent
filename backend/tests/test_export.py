# -*- coding: utf-8 -*-
"""Tests des exports bureautiques (core/export) — lettre .docx, CV .pdf, offline."""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import export  # noqa: E402

_STRUCTURED = {
    "name": "Axel AHO", "role": "Ingénieur IA",
    "contact": {"email": "a@b.co", "phone": "+212 6 00 00 00 00", "location": "Casablanca",
                "github": "github.com/Yoh5"},
    "summary": "Ingénieur IA — agents LLM, Python, FastAPI.",
    "experiences": [{"title": "Stagiaire IA", "org": "Holokia", "date": "2026",
                     "stack": "Python, FastAPI", "bullets": ["Agent d'entretien WhatsApp", "CI verte"]}],
    "projects": [{"title": "Career Match Agent", "meta": "perso", "stack": "OpenAI",
                  "bullets": ["Boucle agentique ATS"]}],
    "education": [{"title": "Diplôme d'ingénieur", "meta": "2027"}],
    "skills": [{"group": "Langages", "items": ["Python", "SQL"]}],
    "certifications": ["Cert X"], "languages": ["Français", "Anglais"],
}


def test_letter_docx_is_valid_word_file():
    data = export.letter_docx("Madame, Monsieur,\n\nPremier paragraphe — accents : éèàç.\n\nCordialement,\nAxel")
    assert data[:2] == b"PK"                                # zip = docx
    from docx import Document
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Madame, Monsieur," in text and "éèàç" in text


def test_cv_pdf_from_structured():
    data = export.cv_pdf(_STRUCTURED, "", "fr")
    assert data[:5] == b"%PDF-" and len(data) > 1200
    # le contenu texte du PDF contient bien le nom (flux non compressés par défaut ou métadonnées)
    from pypdf import PdfReader
    txt = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    assert "Axel AHO" in txt and "Career Match Agent" in txt


def test_cv_pdf_fallback_from_markdown():
    md = "# Axel AHO\n## Expériences\n- Stage IA chez Holokia\nTexte libre — tiret cadratin."
    data = export.cv_pdf(None, md, "fr")
    assert data[:5] == b"%PDF-"
    from pypdf import PdfReader
    txt = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    assert "Axel AHO" in txt and "Stage IA" in txt


def test_cv_pdf_survives_long_content_multipage():
    s = dict(_STRUCTURED)
    s["experiences"] = [{"title": f"Poste {i}", "org": "Org", "date": "2026",
                         "bullets": [f"réalisation {i}.{j} assez longue pour tester le retour à la ligne"
                                     for j in range(4)]} for i in range(14)]
    from pypdf import PdfReader
    for layout in ("ats", "designed"):
        data = export.cv_pdf(s, "", "fr", layout=layout)
        assert len(PdfReader(io.BytesIO(data)).pages) >= 2, layout      # pagination


# ── Les deux mises en page : une pour le robot, une pour l'œil ──────────────

def _text(data):
    from pypdf import PdfReader
    return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


def test_ats_layout_is_the_default():
    assert export.cv_pdf(_STRUCTURED, "", "fr") == export.cv_pdf(_STRUCTURED, "", "fr", layout="ats")


def test_ats_layout_uses_standard_section_headings():
    txt = _text(export.cv_pdf(_STRUCTURED, "", "fr", layout="ats"))
    for heading in ("PROFIL", "COMPÉTENCES", "EXPÉRIENCE PROFESSIONNELLE", "FORMATION"):
        assert heading in txt, heading


def test_ats_layout_english_headings():
    txt = _text(export.cv_pdf(_STRUCTURED, "", "en", layout="ats"))
    assert "PROFESSIONAL EXPERIENCE" in txt and "EDUCATION" in txt


def test_ats_layout_keeps_bullets_attached_to_their_text():
    # la puce est écrite DANS la chaîne : elle ne peut pas se détacher à l'extraction
    txt = _text(export.cv_pdf(_STRUCTURED, "", "fr", layout="ats"))
    assert "- Agent d'entretien WhatsApp" in txt


def test_ats_layout_puts_contact_at_the_top():
    txt = _text(export.cv_pdf(_STRUCTURED, "", "fr", layout="ats"))
    assert txt.index("a@b.co") < 120                 # l'ATS lit le candidat dans l'en-tête


def test_designed_layout_still_available():
    txt = _text(export.cv_pdf(_STRUCTURED, "", "fr", layout="designed"))
    assert "Axel AHO" in txt and "Career Match Agent" in txt


def test_accents_survive_the_pdf_round_trip():
    s = dict(_STRUCTURED, summary="Modélisation à Casablanca, coût réduit, données traitées.")
    txt = _text(export.cv_pdf(s, "", "fr"))
    assert "Modélisation" in txt and "coût" in txt


def test_latin_sanitizer():
    assert export._latin("émoji ✅ tiret — fine  espace") == "émoji  tiret - fine  espace"
