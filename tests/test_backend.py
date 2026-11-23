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


def test_campaign_flow(tmp_path, monkeypatch):
    from spai import campaign
    sims = client.get("/simulations").json()
    if not sims:
        pytest.skip("no approved simulation yet")
    monkeypatch.setattr(telemetry, "SIM_LOG", tmp_path / "sim.jsonl")
    monkeypatch.setattr(campaign, "CAMPAIGNS", tmp_path / "campaigns.json")
    c = client.post("/campaigns", json={"draft_id": sims[0]["id"], "department": "HR", "recipients": 3}).json()
    a, b, _ = [l["url"].split("testserver")[1] for l in c["inbox_links"]]
    assert "TRAINING" in client.get(a).text
    client.get(a + "/click")
    client.get(a + "/click")                                 # counted once
    assert "phishing simulation" in client.post(a + "/submit", data={"u": "x", "p": "secret"}).text
    client.post(b + "/report")
    f = client.get("/campaigns").json()[0]["funnel"]
    assert f == {"delivered": 3, "opened": 1, "clicked": 1, "submitted_data": 1, "reported": 1}
    assert "secret" not in (tmp_path / "sim.jsonl").read_text()
    assert client.get("/inbox/nope/nope").status_code == 404


def test_web_ui_served():
    assert client.get("/ui/").status_code == 200
    assert client.get("/ui/learn.html").status_code == 200


def test_phishing_checker_rules():
    mail = ("From: it-support@micros0ft-helpdesk.co\nSubject: Account locked\n\nDear user, your mailbox is "
            "suspended. Verify your account immediately at https://micros0ft-helpdesk.co/login")
    r = client.post("/check", json={"text": mail, "use_llm": False}).json()
    assert r["verdict"] == "likely phishing" and len(r["flags"]) >= 3
    safe = client.post("/check", json={"text": "Hi all, lunch is at 1pm in the canteen today.", "use_llm": False}).json()
    assert safe["verdict"] == "probably safe"


def test_progress_trends_and_overview(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from spai import insights
    sim, quiz = tmp_path / "sim.jsonl", tmp_path / "quiz.jsonl"
    monkeypatch.setattr(telemetry, "SIM_LOG", sim)
    monkeypatch.setattr(telemetry, "QUIZ_LOG", quiz)
    now = datetime.now(timezone.utc)
    ago = (now - timedelta(days=8)).isoformat()
    rows = [  # last week: fin-001 clicked; this week: fin-001 reported, fin-002 clicked
        {"draft_id": "old", "department": "Finance", "user_id": "fin-001", "action": "delivered", "topic": "Invoices", "at": ago},
        {"draft_id": "old", "department": "Finance", "user_id": "fin-001", "action": "clicked", "topic": "Invoices", "at": ago},
        {"draft_id": "new", "department": "Finance", "user_id": "fin-001", "action": "delivered", "topic": "Payroll", "at": now.isoformat()},
        {"draft_id": "new", "department": "Finance", "user_id": "fin-001", "action": "reported", "topic": "Payroll", "at": now.isoformat()},
        {"draft_id": "new", "department": "Finance", "user_id": "fin-002", "action": "delivered", "topic": "Payroll", "at": now.isoformat()},
        {"draft_id": "new", "department": "Finance", "user_id": "fin-002", "action": "clicked", "topic": "Payroll", "at": now.isoformat()},
    ]
    sim.write_text("\n".join(json.dumps(r) for r in rows))
    quiz.write_text(json.dumps({"department": "Finance", "topic": "Invoices", "score": 0.8, "n": 5,
                                "user_id": "fin-001", "missed": ["Call the vendor on a known number."],
                                "at": now.isoformat()}))
    p = client.get("/progress/fin-001").json()
    assert p["found"] and p["week"]["avoided"] == 1 and p["week"]["reported"] == 1 and p["week"]["clicked"] == 0
    assert p["week"]["quiz_avg"] == 0.8 and p["streak_weeks"] == 1
    assert "Call the vendor on a known number." in p["tips"]
    assert client.get("/progress/nobody").json()["found"] is False
    t = client.get("/trends/Finance").json()
    assert [w["click_rate"] for w in t["weeks"]] == [1.0, 0.5]
    o = client.get("/reports/weekly").json()["departments"]["Finance"]
    assert o == {"employees": 2, "simulations": 2, "avoided": 1, "reported": 1, "clicked": 1, "quiz_avg": 0.8}
    monkeypatch.setattr(insights, "REPORTS", tmp_path / "reports")
    assert (tmp_path / "reports").exists() is False
    insights.snapshot_week()
    assert list((tmp_path / "reports").glob("*.json"))


def test_staleness_endpoint():
    r = client.get("/modules/staleness").json()
    assert "modules" in r and all(m["status"] in ("current", "update suggested") for m in r["modules"])
