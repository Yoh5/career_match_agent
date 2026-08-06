# -*- coding: utf-8 -*-
"""Tests de la file d'offres (core/pipeline) — stockage redirigé, sans réseau."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import pipeline  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_store(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_PIPELINE_PATH", str(tmp_path / "pipe.json"))


def _offer(url="https://x.io/1", title="Stage IA"):
    return {"source": "greenhouse", "company": "acme", "title": title,
            "url": url, "location": "Casablanca", "description": "Stage de 6 mois, Python."}


def test_add_and_list():
    assert pipeline.add_offers([_offer()]) == 1
    items = pipeline.list_items()
    assert len(items) == 1
    it = items[0]
    assert it["status"] == "sourced" and it["title"] == "Stage IA"
    assert it["has_offer_text"] is True
    assert "offer_text" not in it                      # version allégée pour l'UI


def test_add_dedupes_by_url():
    pipeline.add_offers([_offer()])
    assert pipeline.add_offers([_offer(), _offer("https://x.io/2")]) == 1
    assert pipeline.stats()["total"] == 2


def test_offer_without_url_ignored():
    assert pipeline.add_offers([{"title": "sans url"}]) == 0


def test_update_status_and_fields():
    pipeline.add_offers([_offer()])
    oid = pipeline.list_items()[0]["id"]
    it = pipeline.update(oid, status="analyzed", fit_score=82, ats_pct=70, decision="postuler")
    assert it["status"] == "analyzed" and it["fit_score"] == 82
    full = pipeline.get(oid)
    assert full["decision"] == "postuler" and full["offer_text"].startswith("Stage")


def test_update_invalid_status_raises():
    pipeline.add_offers([_offer()])
    oid = pipeline.list_items()[0]["id"]
    with pytest.raises(ValueError):
        pipeline.update(oid, status="n_importe_quoi")


def test_update_unknown_id_returns_none():
    assert pipeline.update("deadbeef", status="sent") is None


def test_list_filter_by_status_and_stats():
    pipeline.add_offers([_offer(), _offer("https://x.io/2")])
    oid = pipeline.list_items()[0]["id"]
    pipeline.update(oid, status="ready", prepared={"cv_markdown": "# CV"})
    assert len(pipeline.list_items("ready")) == 1
    assert pipeline.list_items("ready")[0]["prepared_keys"] == ["cv_markdown"]
    s = pipeline.stats()
    assert s["by_status"]["ready"] == 1 and s["by_status"]["sourced"] == 1


# ── Suppression : sans elle, le pipeline ne fait que grossir ────────────────

def test_remove_deletes_one_offer():
    pipeline.add_offers([_offer("https://a.co/1"), _offer("https://a.co/2")])
    target = pipeline.list_items()[0]["id"]
    assert pipeline.remove(target) is True
    ids = [it["id"] for it in pipeline.list_items()]
    assert target not in ids and len(ids) == 1


def test_remove_unknown_id_is_false():
    pipeline.add_offers([_offer("https://a.co/1")])
    assert pipeline.remove("nexistepas") is False
    assert len(pipeline.list_items()) == 1


def test_clear_empties_everything():
    pipeline.add_offers([_offer("https://a.co/1"), _offer("https://a.co/2")])
    assert pipeline.clear() == 2
    assert pipeline.list_items() == []


def test_clear_by_status_keeps_the_rest():
    pipeline.add_offers([_offer("https://a.co/1"), _offer("https://a.co/2")])
    kept = pipeline.list_items()[0]["id"]
    pipeline.update(kept, status="ready")
    assert pipeline.clear("sourced") == 1
    remaining = pipeline.list_items()
    assert len(remaining) == 1 and remaining[0]["id"] == kept


def test_clear_rejects_an_unknown_status():
    with pytest.raises(ValueError):
        pipeline.clear("nimportequoi")
