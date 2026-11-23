"""Offline tests: no Gemini or Firecrawl calls. Run:  .venv/Scripts/python -m pytest -q"""
import json

import pytest
from fastapi.testclient import TestClient

from spai import config, guardrails, telemetry
from spai.api import app

client = TestClient(app)


# ---------- guardrails ----------
def test_untrusted_links_flagged():
    text = "See https://www.cisa.gov/mfa and https://evil-login.co/reset"
    assert guardrails.check_links(text) == ["https://evil-login.co/reset"]


def test_simulation_is_defanged():
    sim = {"sender": "billing@real-bank.com", "subject": "Pay now",
           "body": "Click https://real-bank.com/login or https://ok.example.com/x"}
    out, fixed = guardrails.defang_sim(sim)
    assert out["sender"].endswith(".example.com")
    assert "real-bank.com/login" not in out["body"]
    assert "https://ok.example.com/x" in out["body"]
    assert "TRAINING" in out["training_marker"]
    assert fixed


def test_citation_stats():
    s = guardrails.citation_stats("A [S1]. B [S2][S9]. C [ORG].", n_sources=3)
    assert s["cited_ids"] == [1, 2] and s["invalid_ids"] == [9] and s["n_org"] == 1


# ---------- telemetry ----------
def test_profile_has_every_department():
    prof = telemetry.build_profile()
    assert set(config.org()["departments"]) <= set(prof)
    assert any(prof.values())


def test_sim_events_become_mistakes(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "SIM_LOG", tmp_path / "sim.jsonl")
    for u in ("u1", "u2", "u3"):
        telemetry.record_sim_event("d1", "Finance", u, "opened", "Invoice fraud")
    telemetry.record_sim_event("d1", "Finance", "u1", "clicked", "Invoice fraud")
    telemetry.record_sim_event("d1", "Finance", "u2", "submitted_data", "Invoice fraud")
    m = telemetry.sim_mistakes()
    assert m and m[0]["rate"] == round(2 / 3, 3) and m[0]["source"] == "simulation"
    with pytest.raises(ValueError):
        telemetry.record_sim_event("d1", "Finance", "u1", "deleted", "x")


# ---------- API ----------
def test_health_and_meta():
    assert client.get("/health").json()["status"] == "ok"
    meta = client.get("/meta").json()
    assert "phishing_sim" in meta["formats"] and "Finance" in meta["departments"]


def test_generate_validation_needs_no_llm():
    r = client.post("/generate", json={"topic": "x", "audience": "Marketing"})
    assert r.status_code == 422
    r = client.post("/generate", json={"topic": "x", "format": "policy_summary"})
    assert r.status_code == 422


def test_kb_search():
    hits = client.get("/kb/search", params={"q": "MFA fatigue push", "k": 3}).json()
    assert len(hits) == 3 and all("url" in h for h in hits)


def test_missing_draft_404():
    assert client.get("/drafts/doesnotexist").status_code == 404


def test_quiz_hides_answers():
    for q in client.get("/quizzes").json():
        for item in q["questions"]:
            assert "answer_index" not in item and "explanation" not in item


def test_sim_event_endpoint(tmp_path, monkeypatch):
    sims = client.get("/simulations", params={"approved_only": False}).json()
    if not sims:
        pytest.skip("no simulation drafts yet")
    monkeypatch.setattr(telemetry, "SIM_LOG", tmp_path / "sim.jsonl")
    sid = sims[0]["id"]
    r = client.post(f"/simulations/{sid}/events",
                    json={"department": "Finance", "user_id": "t1", "action": "clicked"})
    assert r.status_code == 200
    stats = client.get(f"/simulations/{sid}/stats").json()
    assert stats["by_department"]["Finance"]["clicked"] == 1
    bad = client.post(f"/simulations/{sid}/events",
                      json={"department": "Finance", "user_id": "t1", "action": "nope"})
    assert bad.status_code == 422
