# -*- coding: utf-8 -*-
"""Tests de la mémoire long terme (core/memory) — stockage redirigé, sans réseau."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import memory  # noqa: E402


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREER_MEMORY_PATH", str(tmp_path / "mem.json"))


def test_record_and_recall_roundtrip(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    memory.record_application("Offre A\nDev Python", {"fit_score": 80, "ats_pct": 70,
                                                      "recommendation": "postuler",
                                                      "missing_keywords": ["Docker"]})
    rec = memory.recall("Offre A\nDev Python")
    assert rec and rec["fit_score"] == 80 and rec["recommendation"] == "postuler"
    assert rec["missing_keywords"] == ["docker"]          # normalisé minuscule
    assert rec["title"] == "Offre A"


def test_recall_unknown_returns_none(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    assert memory.recall("jamais vue") is None


def test_record_dedupes_same_offer(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    memory.record_application("Offre X", {"fit_score": 40})
    memory.record_application("Offre X", {"fit_score": 90})   # même offre → remplace
    prof = memory.profile_summary()
    assert prof["count"] == 1
    assert memory.recall("Offre X")["fit_score"] == 90


def test_recurring_gaps_counts_across_offers(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    memory.record_application("Offre 1", {"missing_keywords": ["Docker", "AWS"]})
    memory.record_application("Offre 2", {"missing_keywords": ["docker", "Kubernetes"]})
    memory.record_application("Offre 3", {"missing_keywords": ["Docker"]})
    gaps = {g["keyword"]: g["count"] for g in memory.recurring_gaps(min_count=2)}
    assert gaps.get("docker") == 3            # récurrent
    assert "aws" not in gaps                  # vu 1 fois seulement


def test_profile_summary_avg_fit(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    memory.record_application("A", {"fit_score": 60})
    memory.record_application("B", {"fit_score": 80})
    prof = memory.profile_summary()
    assert prof["count"] == 2 and prof["avg_fit"] == 70


def test_bad_store_is_failopen(monkeypatch, tmp_path):
    # fichier illisible → _load() retombe sur un store vide, pas d'exception
    p = tmp_path / "mem.json"
    p.write_text("pas du json", encoding="utf-8")
    monkeypatch.setenv("CAREER_MEMORY_PATH", str(p))
    assert memory.recall("x") is None
    assert memory.profile_summary()["count"] == 0
