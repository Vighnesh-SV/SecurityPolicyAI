"""Prepare a complete demo so every screen has something to show.

    .venv\\Scripts\\python scripts\\demo.py            # build the demo (safe to re-run)
    .venv\\Scripts\\python scripts\\demo.py --reset    # remove the demo activity again

What it does
  1. Content (REAL, made by the AI): one item of every format, reviewed by the judge; most are approved.
  2. Activity history (SIMULATED, every row tagged "demo": true): four weeks of phishing campaigns and
     quiz results for Finance, Sales and HR, showing improvement after training. Demo employee: fin-007.
  3. Rebuilds the department mistake profiles and the weekly report.
The generated content is real output; only the employee activity is simulated, and the app shows a
"Demo data" badge while it is loaded.
"""
import argparse
import json
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from spai import campaign, config, guardrails, insights, telemetry  # noqa: E402
from spai.api import APPROVED, DRAFTS, app  # noqa: E402

FLAG = config.ROOT / "data" / "demo_mode"
DEMO_USER = "fin-007"

POLICY = """Acceptable Use of Company IT - summary of key clauses
1. Company laptops and accounts are for business use; limited personal use is allowed if it does not affect work.
2. Never share passwords or MFA codes with anyone, including IT staff. IT will never ask for them.
3. Report lost or stolen devices to the security team within one hour.
4. Only install software from the company portal. Browser extensions need IT approval.
5. Customer data must not be copied to personal email, USB drives or personal cloud storage.
6. Suspicious emails must be reported with the Report Phishing button and then deleted.
7. Violations may lead to disciplinary action in line with the HR policy."""

CONTENT = [  # (topic, audience, format, approve)
    ("QR-code phishing (quishing)", "All staff", "newsletter", True),
    ("Invoice and payment-redirect fraud", "Finance", "quiz", True),
    ("Fake job applicant attachments", "HR", "tip", True),
    ("MFA fatigue and push-bombing", "All staff", "poster", True),
    ("Fake building access badge renewal", "Sales", "phishing_sim", True),
    ("Acceptable use of company IT", "All staff", "policy_summary", False),
]


def step(m):
    print(f"\n=== {m}", flush=True)


# ---------------- 1. real content ----------------
def build_content(client):
    have = {}
    for p in list(DRAFTS.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        have[(d["request"]["topic"], d["request"]["format"])] = d["id"]
        # re-run the deterministic guardrails with the current rules (fixes old false positives)
        txt = json.dumps(d["content"], ensure_ascii=False)
        d["guardrails"]["untrusted_links"] = guardrails.check_links(txt)
        p.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        if (APPROVED / p.name).exists():
            (APPROVED / p.name).write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    ids = {}
    for topic, aud, fmt, approve in CONTENT:
        did = have.get((topic, fmt))
        if not did:
            print(f"  generating {fmt}: {topic} ({aud}) ...", flush=True)
            body = {"topic": topic, "audience": aud, "format": fmt}
            if fmt == "policy_summary":
                body["policy_text"] = POLICY
            r = client.post("/generate", json=body)
            if r.status_code != 200:
                print(f"    failed: {r.status_code} {r.text[:200]}")
                continue
            did = r.json()["id"]
        else:
            print(f"  have {fmt}: {topic}")
        ids[(topic, fmt)] = did
        if approve and not (APPROVED / f"{did}.json").exists():
            r = client.post(f"/drafts/{did}/approve")
            print(f"    approve: {r.status_code}")
    return ids


# ---------------- 2. simulated activity ----------------
def _now():
    return datetime.now(timezone.utc)


def _append(path, rows):
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def build_activity(sim_ids: dict):
    """Four weekly campaigns per department with click rates falling as training kicks in."""
    rnd = random.Random(7)
    plans = {  # department: (draft id, topic, recipients, [click rate per week, oldest first], [report rate])
        "Finance": (sim_ids["Finance"], 12, [0.50, 0.42, 0.25, 0.17], [0.08, 0.17, 0.33, 0.42]),
        "Sales": (sim_ids["Sales"], 10, [0.60, 0.50, 0.40, 0.30], [0.10, 0.10, 0.20, 0.30]),
        "HR": (sim_ids["Finance"], 8, [0.38, 0.38, 0.25, 0.13], [0.13, 0.25, 0.25, 0.38]),
    }
    camps = json.loads(campaign.CAMPAIGNS.read_text(encoding="utf-8")) if campaign.CAMPAIGNS.exists() else {}
    events, quizzes = [], []
    for dept, (did, n, clicks, reports) in plans.items():
        d = json.loads(((APPROVED / f"{did}.json")).read_text(encoding="utf-8"))
        topic, title = d["request"]["topic"], d["content"]["title"]
        users = [f"{dept[:3].lower()}-{i + 1:03d}" for i in range(n)]
        for w, (cr, rr) in enumerate(zip(clicks, reports)):
            weeks_ago = 3 - w
            when = _now() - timedelta(days=7 * weeks_ago + (1 if weeks_ago else 0), hours=rnd.randint(1, 6))
            cid = "demo" + secrets.token_hex(3)
            camps[cid] = {"id": cid, "draft_id": did, "title": title, "topic": topic, "department": dept,
                          "created": when.isoformat(), "recipients": {secrets.token_hex(5): u for u in users}, "demo": True}
            order = users[:]
            rnd.shuffle(order)
            if dept == "Finance":          # the demo employee clicked once, then improved
                order.remove(DEMO_USER)
                order = ([DEMO_USER] + order) if w == 0 else (order + [DEMO_USER])
            n_click, n_report = round(cr * n), round(rr * n)
            clickers = set(order[:n_click])
            reporters = set([u for u in reversed(order) if u not in clickers][:n_report])
            if dept == "Finance" and w == 3:
                reporters.add(DEMO_USER)
            for u in users:
                t = when
                acts = ["delivered"]
                if u in clickers or u in reporters or rnd.random() < 0.5:
                    acts.append("opened")
                if u in clickers:
                    acts.append("clicked")
                    if rnd.random() < 0.4:
                        acts.append("submitted_data")
                if u in reporters:
                    acts.append("reported")
                for a in acts:
                    t += timedelta(minutes=rnd.randint(1, 90))
                    events.append({"draft_id": did, "department": dept, "user_id": u, "action": a, "topic": topic,
                                   "campaign_id": cid, "at": t.isoformat(), "demo": True})
            # quiz results that week
            avg = 0.5 + 0.1 * w
            quiz_topic = "Invoice and payment-redirect fraud" if dept == "Finance" else topic
            for u in rnd.sample(users, k=max(3, n // 2)):
                s = min(1.0, max(0.2, round(rnd.gauss(avg, 0.15) * 5) / 5))
                if u == DEMO_USER:
                    continue
                quizzes.append({"department": dept, "topic": quiz_topic, "score": s, "n": 5, "user_id": u,
                                "missed": [], "at": (when + timedelta(days=2)).isoformat(), "demo": True})
    # the demo employee's own quiz history (improving)
    for weeks_ago, s, missed in ((2, 0.6, ["Always confirm bank-detail changes by calling the vendor on a number you already have."]),
                                 (0, 0.8, ["Urgency plus a payment request is the classic invoice-fraud pattern: slow down."])):
        quizzes.append({"department": "Finance", "topic": "Invoice and payment-redirect fraud", "score": s, "n": 5,
                        "user_id": DEMO_USER, "missed": missed,
                        "at": (_now() - timedelta(days=7 * weeks_ago, hours=3)).isoformat(), "demo": True})
    campaign._write(camps)
    _append(telemetry.SIM_LOG, events)
    _append(telemetry.QUIZ_LOG, quizzes)
    print(f"  {len(camps)} campaigns, {len(events)} simulation events, {len(quizzes)} quiz results")


def reset():
    for path in (telemetry.SIM_LOG, telemetry.QUIZ_LOG):
        if path.exists():
            keep = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not json.loads(l).get("demo")]
            path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    if campaign.CAMPAIGNS.exists():
        c = {k: v for k, v in json.loads(campaign.CAMPAIGNS.read_text(encoding="utf-8")).items() if not v.get("demo")}
        campaign._write(c)
    FLAG.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="remove the simulated demo activity")
    a = ap.parse_args()
    step("removing earlier demo activity")
    reset()
    if a.reset:
        telemetry.build_profile()
        print("Demo activity removed (generated content is kept).")
        return
    client = TestClient(app)
    step("1/3 content: one of every format (uses the AI; ~1-2 min each)")
    ids = build_content(client)
    sims = {"Finance": ids.get(("Invoice and payment-redirect fraud", "phishing_sim")) or "2092fa0aac",
            "Sales": ids.get(("Fake building access badge renewal", "phishing_sim")) or "2092fa0aac"}
    for k, v in sims.items():
        if not (APPROVED / f"{v}.json").exists():
            client.post(f"/drafts/{v}/approve")
    step("2/3 four weeks of simulated campaigns and quizzes (tagged demo)")
    build_activity(sims)
    FLAG.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    step("3/3 profiles and weekly report")
    prof = telemetry.build_profile()
    print("  mistakes per department:", {k: len(v) for k, v in prof.items()})
    print("  weekly report saved:", insights.snapshot_week())
    print(f"\nDemo ready. Open http://localhost:8000 (admin) and the Presenter guide.\n"
          f"Employee portal demo login: {DEMO_USER}")


if __name__ == "__main__":
    main()
