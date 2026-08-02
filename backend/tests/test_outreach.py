# -*- coding: utf-8 -*-
"""Tests du client lemlist (core/outreach) — fail-open, HTTP monkeypatché."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import outreach  # noqa: E402


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("LEMLIST_API_KEY", raising=False)
    assert not outreach.is_enabled()
    res, err = outreach.campaigns()
    assert res is None and "LEMLIST_API_KEY" in err
    res, err = outreach.add_lead("c1", "a@b.co", {})
    assert res is None and err


def test_add_lead_validates_inputs(monkeypatch):
    monkeypatch.setenv("LEMLIST_API_KEY", "k")
    res, err = outreach.add_lead("", "a@b.co", {})
    assert err == "campaign_id manquant"
    res, err = outreach.add_lead("c1", "pas-un-email", {})
    assert "email" in err


def test_add_lead_builds_request(monkeypatch):
    monkeypatch.setenv("LEMLIST_API_KEY", "k")
    calls = {}

    def fake_request(method, path, json_body=None):
        calls.update(method=method, path=path, body=json_body)
        return {"ok": True}, None

    monkeypatch.setattr(outreach, "_request", fake_request)
    res, err = outreach.add_lead("camp1", "marie@acme.com", {
        "first_name": "Marie", "company": "Acme", "message": "Bonjour Marie…",
    })
    assert err is None and res == {"ok": True}
    assert calls["method"] == "POST"
    assert "/campaigns/camp1/leads/marie@acme.com" in calls["path"]
    assert "deduplicate=true" in calls["path"]
    assert calls["body"]["firstName"] == "Marie" and calls["body"]["message"].startswith("Bonjour")


def test_campaigns_normalizes(monkeypatch):
    monkeypatch.setenv("LEMLIST_API_KEY", "k")
    monkeypatch.setattr(outreach, "_request",
                        lambda m, p, json_body=None: ([{"_id": "c1", "name": "Stages"}, "junk"], None))
    camps, err = outreach.campaigns()
    assert err is None and camps == [{"id": "c1", "name": "Stages"}]
