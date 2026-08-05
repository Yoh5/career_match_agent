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


# ── Liens cliquables : un dépôt qu'on ne peut pas ouvrir ne sert à rien ─────

def _links(data):
    from pypdf import PdfReader
    return [(a.get_object().get("/A") or {}).get("/URI")
            for page in PdfReader(io.BytesIO(data)).pages
            for a in (page.get("/Annots") or [])
            if a.get_object().get("/Subtype") == "/Link"]


def test_href_builds_clickable_urls():
    assert export._href("github.com/Yoh5") == "https://github.com/Yoh5"
    assert export._href("https://github.com/Yoh5") == "https://github.com/Yoh5"
    assert export._href("- github.com/Yoh5/career_match_agent") == \
        "https://github.com/Yoh5/career_match_agent"
    assert export._href("a@b.co") == "mailto:a@b.co"


def test_href_ignores_plain_text():
    for s in ("Node.js", "React 19", "Développeur logiciel", "Python, FastAPI", ""):
        assert export._href(s) is None, s


def test_both_layouts_expose_contact_and_repo_links():
    s = dict(_STRUCTURED)
    s["projects"] = [{"title": "Career Match Agent", "meta": "perso",
                      "bullets": ["Boucle agentique ATS", "github.com/Yoh5/career_match_agent"]}]
    for layout in ("ats", "designed"):
        urls = _links(export.cv_pdf(s, "", "fr", layout=layout))
        assert "mailto:a@b.co" in urls, layout
        assert "https://github.com/Yoh5" in urls, layout
        assert "https://github.com/Yoh5/career_match_agent" in urls, layout


def test_links_do_not_alter_the_extracted_text():
    """L'annotation se pose PAR-DESSUS le texte : l'ATS lit toujours la même chose."""
    s = dict(_STRUCTURED)
    s["projects"] = [{"title": "P", "bullets": ["github.com/Yoh5/career_match_agent"]}]
    txt = _text(export.cv_pdf(s, "", "fr"))
    assert "github.com/Yoh5/career_match_agent" in txt


def test_ats_layout_autofits_to_one_page_when_close():
    from pypdf import PdfReader
    s = dict(_STRUCTURED)
    # contenu qui déborde de peu : l'auto-ajustement doit le ramener sur une page
    s["experiences"] = [{"title": f"Poste {i}", "org": "Org", "date": "2026",
                         "bullets": [f"réalisation {i}.{j} décrite sur une ligne complète"
                                     for j in range(3)]} for i in range(7)]
    data = export.cv_pdf(s, "", "fr", layout="ats")
    assert len(PdfReader(io.BytesIO(data)).pages) == 1


def test_accents_survive_the_pdf_round_trip():
    s = dict(_STRUCTURED, summary="Modélisation à Casablanca, coût réduit, données traitées.")
    txt = _text(export.cv_pdf(s, "", "fr"))
    assert "Modélisation" in txt and "coût" in txt


def test_latin_sanitizer():
    assert export._latin("émoji ✅ tiret — fine  espace") == "émoji  tiret - fine  espace"
