# -*- coding: utf-8 -*-
"""Tests des templates de message (core/templates) — stockage redirigé."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import templates  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_store(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_TEMPLATES_PATH", str(tmp_path / "tpl.json"))


def test_defaults_present():
    t = templates.get_all()
    assert "linkedin_invite" in t and "linkedin_message" in t and "email" in t
    assert "{company}" in t["linkedin_message"]


def test_save_overrides_and_persists():
    templates.save({"linkedin_invite": "Salut {first_name}, dispo pour parler de {role} ?"})
    t = templates.get_all()
    assert t["linkedin_invite"].startswith("Salut")
    assert "{company}" in t["email"]                   # les autres gardent le défaut


def test_save_ignores_empty_and_non_str():
    before = templates.get_all()["email"]
    templates.save({"email": "", "linkedin_message": 42})
    t = templates.get_all()
    assert t["email"] == before and "{company}" in t["linkedin_message"]


def test_render_fills_placeholders():
    out = templates.render("linkedin_message", {
        "first_name": "Marie", "company": "Acme", "role": "Stage Data",
        "highlight": "mon agent IA", "my_name": "Axel", "link": "https://x.io",
    })
    assert "Marie" in out and "Acme" in out and "Stage Data" in out and "Axel" in out
    assert "{" not in out.replace("{}", "")            # tout est rempli


def test_render_tolerant_to_unknown_placeholder_and_key():
    templates.save({"linkedin_invite": "Hello {first_name}, voir {inconnu}"})
    out = templates.render("linkedin_invite", {"first_name": "Sam"})
    assert out == "Hello Sam, voir {inconnu}"          # placeholder inconnu laissé tel quel
    assert templates.render("nexiste_pas", {}) == ""
