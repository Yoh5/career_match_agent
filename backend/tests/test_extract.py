# -*- coding: utf-8 -*-
"""Tests de l'extraction de texte (core/extract) — sans réseau."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import extract  # noqa: E402


def test_txt_and_md_decode():
    text, err = extract.extract_cv_text("cv.txt", "Bonjour é à".encode("utf-8"))
    assert err is None and "Bonjour" in text
    text, err = extract.extract_cv_text("cv.md", b"# Titre")
    assert err is None and "# Titre" in text


def test_unsupported_format_returns_error():
    text, err = extract.extract_cv_text("cv.png", b"\x89PNG")
    assert text == "" and "Format non supporté" in err


def test_html_to_text_strips_scripts_and_tags():
    html = "<html><head><style>.x{}</style></head><body><script>x=1</script>" \
           "<p>Bonjour&nbsp;&amp; bienvenue</p></body></html>"
    t = extract.html_to_text(html)
    assert "x=1" not in t and ".x{}" not in t
    assert "Bonjour" in t and "&" in t and "bienvenue" in t


def test_fetch_offer_url_rejects_non_http():
    text, err = extract.fetch_offer_url("ftp://exemple.com/offre")
    assert text == "" and "http/https" in err
    text, err = extract.fetch_offer_url("")
    assert text == "" and err
