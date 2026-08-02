# -*- coding: utf-8 -*-
"""Tests du rendu Markdown → HTML (core/render) — déterministe, sans réseau."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import render  # noqa: E402


def test_headings_levels():
    h = render.md_to_html_fragment("# Titre\n## Section\n### Sous")
    assert "<h1>Titre</h1>" in h and "<h2>Section</h2>" in h and "<h3>Sous</h3>" in h


def test_bold_italic_and_link():
    h = render.md_to_html_fragment("Du **gras**, de l'*italique* et un [lien](https://ex.com).")
    assert "<strong>gras</strong>" in h
    assert "<em>italique</em>" in h
    assert '<a href="https://ex.com">lien</a>' in h


def test_unordered_and_ordered_lists():
    h = render.md_to_html_fragment("- a\n- b\n\n1. x\n2. y")
    assert "<ul>" in h and "<li>a</li>" in h and "</ul>" in h
    assert "<ol>" in h and "<li>x</li>" in h and "</ol>" in h


def test_horizontal_rule_and_paragraph():
    h = render.md_to_html_fragment("Para un.\n\n---\n\nPara deux.")
    assert "<hr>" in h
    assert "<p>Para un.</p>" in h and "<p>Para deux.</p>" in h


def test_html_is_escaped():
    # pas d'injection : les balises du contenu sont échappées
    h = render.md_to_html_fragment("Texte <script>alert(1)</script> & co")
    assert "<script>" not in h
    assert "&lt;script&gt;" in h and "&amp;" in h


def test_title_from_markdown():
    assert render.title_from_markdown("# Axel AHO\n## Profil") == "Axel AHO"
    assert render.title_from_markdown("pas de titre") == "CV"


def test_full_doc_is_self_contained_and_ats_friendly():
    doc = render.cv_markdown_to_html("# Axel AHO\n## Compétences\n- Python", render.title_from_markdown("# Axel AHO"))
    assert doc.startswith("<!doctype html>")
    assert "<title>Axel AHO</title>" in doc
    assert "@page" in doc                    # imprimable A4
    assert "<img" not in doc                 # ATS-friendly : pas d'image
    assert "http://" not in doc.split("<style>")[0]  # rien d'externe dans le head avant le style
