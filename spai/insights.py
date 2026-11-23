"""Learning analytics and helpers built on telemetry + knowledge base.

- check_email     : "Is this phishing?" checker for employees (rules + optional LLM explanation)
- trends          : weekly click rate and quiz score per department, before/after comparison
- staleness       : approved modules that newer guidance may have overtaken
- progress        : one employee's weekly / monthly progress report
- weekly_overview : department totals for admins (no ranking of individuals)
- auto_refresh    : background loop that refreshes feeds daily and snapshots weekly reports
"""
import json
import os
import re
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import config, guardrails, kb, llm, memory, telemetry

REPORTS = config.OUTPUTS / "reports"
LAST_REFRESH = config.ROOT / "data" / "last_refresh.txt"


# ---------------- shared readers ----------------
def _rows(path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def _when(r) -> datetime:
    return datetime.fromisoformat(r["at"])


def _week(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def _sim_by_user(rows):
    """{(user, draft_id): {"actions": set, "first": datetime, "department", "topic"}}"""
    out = {}
    for r in rows:
        k = (r["user_id"], r["draft_id"])
        e = out.setdefault(k, {"actions": set(), "first": _when(r), "department": r["department"],
                               "topic": r["topic"], "draft_id": r["draft_id"]})
        e["actions"].add(r["action"])
        e["first"] = min(e["first"], _when(r))
    return out


def _clicked(actions) -> bool:
    return bool(actions & {"clicked", "submitted_data"})


AVOID_AFTER_DAYS = 3


def _avoided(e) -> bool:
    """Reported it, or did not click within AVOID_AFTER_DAYS of delivery."""
    if _clicked(e["actions"]):
        return False
    return "reported" in e["actions"] or datetime.now(timezone.utc) - e["first"] > timedelta(days=AVOID_AFTER_DAYS)


# ---------------- 1. phishing checker ----------------
URGENT = re.compile(r"\b(urgent|immediately|within 24 hours|asap|final notice|suspended|locked|act now|expire[sd]?)\b", re.I)
CREDS = re.compile(r"\b(password|passcode|otp|one[- ]time code|verify your account|login|log in|sign in|bank details|card number)\b", re.I)
MONEY = re.compile(r"\b(invoice|payment|wire|transfer|gift ?cards?|bank account|refund|payroll)\b", re.I)
GENERIC = re.compile(r"^\s*(dear (customer|user|employee|sir|madam|team)|hello user)", re.I | re.M)
ATTACH = re.compile(r"\.(zip|exe|scr|js|iso|html?|docm|xlsm)\b", re.I)
SENDER = re.compile(r"^\s*from:.*?([\w.+-]+@([\w-]+\.)+[\w-]+)", re.I | re.M)

CHECK_PROMPT = """You help an employee decide whether an email is phishing.
EMAIL:
{email}

AUTOMATIC CHECKS FOUND:
{flags}

TRUSTED GUIDANCE (cite as [S#]):
{sources}

Return JSON: {{"verdict": "likely phishing" | "suspicious" | "probably safe",
"explanation": "2-3 plain sentences for a non-technical employee",
"what_to_do": ["short step", ...]}}
Never tell them to click links or reply. Reporting address: {report}."""


def check_email(text: str, use_llm: bool = True) -> dict:
    flags = []
    links = guardrails.URL_RE.findall(text)
    bad_links = [u for u in links if not guardrails._trusted(guardrails._dom(u))]
    if bad_links:
        flags.append(f"Links to unknown sites: {', '.join(bad_links[:3])}")
    for rx, msg in ((URGENT, "Urgent or threatening wording"), (CREDS, "Asks for passwords, codes or account details"),
                    (MONEY, "Mentions payments, invoices or bank details"), (GENERIC, "Generic greeting"),
                    (ATTACH, "Risky attachment type")):
        m = rx.search(text)
        if m:
            flags.append(f"{msg} (\"{m.group(0).strip()}\")")
    s = SENDER.search(text)
    if s and links:
        sdom = s.group(1).split("@")[1].lower()
        if any(sdom not in guardrails._dom(u) for u in links):
            flags.append(f"Sender domain ({sdom}) differs from the link domain")
    score = min(1.0, 0.2 * len(flags) + (0.2 if bad_links else 0))
    verdict = "likely phishing" if score >= 0.6 else "suspicious" if score >= 0.3 else "probably safe"
    out = {"verdict": verdict, "risk": round(score, 2), "flags": flags,
           "explanation": "", "what_to_do": [f"Don't click links or open attachments. Report it to {config.org()['report_address']}."]
           if verdict != "probably safe" else ["If anything still feels off, ask the security team before acting."],
           "sources": [], "ai": False}
    if not use_llm:
        return out
    try:
        hits = kb.retrieve(text[:1500], k=4, kinds=["guidance"])
        src = "\n".join(f"[S{i + 1}] {h['title']}: {h['text'][:500]}" for i, h in enumerate(hits))
        j, _ = llm.generate_json(CHECK_PROMPT.format(email=text[:4000], flags="\n".join(f"- {f}" for f in flags) or "(none)",
                                                     sources=src, report=config.org()["report_address"]),
                                 role="cheap", temperature=0.1)
        out.update({k: j[k] for k in ("verdict", "explanation", "what_to_do") if j.get(k)})
        out["sources"] = [{"title": h["title"], "url": h["url"]} for h in hits]
        out["ai"] = True
    except Exception as e:  # rules-only answer still works without quota
        out["explanation"] = "Automatic checks only (the AI explanation is unavailable right now)."
        out["ai_error"] = str(e)[:200]
    return out


# ---------------- 2. trends ----------------
def trends(department: str) -> dict:
    weeks = defaultdict(lambda: {"sent": 0, "clicked": 0, "reported": 0, "quiz": []})
    for (u, _), e in _sim_by_user(_rows(telemetry.SIM_LOG)).items():
        if e["department"] != department:
            continue
        w = weeks[_week(e["first"])]
        w["sent"] += 1
        w["clicked"] += _clicked(e["actions"])
        w["reported"] += "reported" in e["actions"]
    for r in _rows(telemetry.QUIZ_LOG):
        if r["department"] == department:
            weeks[_week(_when(r))]["quiz"].append(r["score"])
    series = []
    for wk in sorted(weeks):
        w = weeks[wk]
        series.append({"week": wk, "sent": w["sent"],
                       "click_rate": round(w["clicked"] / w["sent"], 3) if w["sent"] else None,
                       "report_rate": round(w["reported"] / w["sent"], 3) if w["sent"] else None,
                       "quiz_avg": round(sum(w["quiz"]) / len(w["quiz"]), 3) if w["quiz"] else None})

    def first_last(key):
        vals = [s[key] for s in series if s[key] is not None]
        return {"before": vals[0], "after": vals[-1]} if len(vals) >= 2 else None
    return {"department": department, "weeks": series,
            "change": {"click_rate": first_last("click_rate"), "quiz_avg": first_last("quiz_avg")}}


# ---------------- 3. staleness ----------------
def staleness(min_score: float = 0.62) -> list[dict]:
    fresh = config.sources()["freshness_days"]
    out = []
    for m in memory.modules():
        mdate = m.get("date", "")
        age = (date.today() - date.fromisoformat(mdate)).days if mdate else None
        newer = [h for h in kb.retrieve(m["topic"], k=8)
                 if h.get("date_known") and h["date"] > mdate and h["score"] >= min_score]
        reasons = []
        if age is not None and age > fresh:
            reasons.append(f"approved {age} days ago")
        if newer:
            reasons.append(f"{len(newer)} newer source(s) on this topic")
        out.append({"id": m["id"], "title": m["title"], "topic": m["topic"], "date": mdate,
                    "status": "update suggested" if reasons else "current", "reasons": reasons,
                    "newer_sources": [{"title": h["title"], "url": h["url"], "date": h["date"]} for h in newer[:3]]})
    return out


# ---------------- 4. employee progress ----------------
def _tips_for_clicks(draft_ids) -> list[str]:
    tips = []
    for did in draft_ids:
        for folder in ("approved", "drafts"):
            p = config.OUTPUTS / folder / f"{did}.json"
            if p.exists():
                c = json.loads(p.read_text(encoding="utf-8"))["content"]
                tips += (c.get("phishing_sim") or {}).get("red_flags") or c.get("red_flags") or []
                break
    return tips


def progress(user_id: str, days: int = 7, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    sims = {k: e for k, e in _sim_by_user(_rows(telemetry.SIM_LOG)).items() if k[0] == user_id}
    quizzes = [r for r in _rows(telemetry.QUIZ_LOG) if r.get("user_id") == user_id]
    if not sims and not quizzes:
        return {"user_id": user_id, "found": False}
    dept = (next(iter(sims.values()))["department"] if sims else quizzes[-1]["department"])

    def in_win(dt, a, b):
        return a <= dt.date() <= b

    def summarise(a, b):
        s = [e for e in sims.values() if in_win(e["first"], a, b)]
        q = [r for r in quizzes if in_win(_when(r), a, b)]
        return {"simulations": len(s),
                "avoided": sum(_avoided(e) for e in s),
                "reported": sum("reported" in e["actions"] for e in s),
                "clicked": sum(_clicked(e["actions"]) for e in s),
                "quizzes": len(q),
                "quiz_avg": round(sum(r["score"] for r in q) / len(q), 3) if q else None,
                "clicked_topics": sorted({e["topic"] for e in s if _clicked(e["actions"])}),
                "clicked_drafts": [e["draft_id"] for e in s if _clicked(e["actions"])],
                "missed": [m for r in q for m in r.get("missed", [])]}

    week = summarise(start, today)
    prev = summarise(start - timedelta(days=days), start - timedelta(days=1))
    month = summarise(today - timedelta(days=29), today)

    # streak: consecutive weeks (ending this week) with activity and no clicks
    streak, end = 0, today
    while True:
        w = summarise(end - timedelta(days=6), end)
        if (w["simulations"] or w["quizzes"]) and not w["clicked"]:
            streak += 1
            end -= timedelta(days=7)
        else:
            break

    tips = _tips_for_clicks(week.pop("clicked_drafts"))[:3] + week["missed"][:2]
    for s in (prev, month):
        s.pop("clicked_drafts")

    team = trends(dept)["weeks"]
    lines = []
    if week["avoided"]:
        lines.append(f"You spotted and avoided {week['avoided']} phishing simulation(s).")
    if week["reported"]:
        lines.append(f"You reported {week['reported']}: that is exactly the right move.")
    if week["quiz_avg"] is not None:
        trend = ""
        if prev["quiz_avg"] is not None:
            d = week["quiz_avg"] - prev["quiz_avg"]
            trend = " (up from last week)" if d > 0 else " (down from last week)" if d < 0 else ""
        lines.append(f"Quiz average {week['quiz_avg']:.0%}{trend}.")
    if week["clicked"]:
        lines.append(f"You clicked {week['clicked']} simulation(s): {', '.join(week['clicked_topics'])}. See the tips below.")
    if not lines:
        lines.append("No security activity this week.")
    return {"user_id": user_id, "found": True, "department": dept, "period": [start.isoformat(), today.isoformat()],
            "headline": lines[0], "lines": lines, "week": week, "previous_week": prev, "month": month,
            "streak_weeks": streak, "tips": tips,
            "team": {"department": dept, "recent_weeks": team[-2:]}}


# ---------------- 5. admin weekly overview (departments only) ----------------
def weekly_overview(days: int = 7) -> dict:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    deps = {d: {"employees": set(), "simulations": 0, "avoided": 0, "reported": 0, "clicked": 0, "quiz": []}
            for d in config.org()["departments"]}
    for (u, _), e in _sim_by_user(_rows(telemetry.SIM_LOG)).items():
        if start <= e["first"].date() <= today and e["department"] in deps:
            d = deps[e["department"]]
            d["employees"].add(u)
            d["simulations"] += 1
            d["avoided"] += _avoided(e)
            d["reported"] += "reported" in e["actions"]
            d["clicked"] += _clicked(e["actions"])
    for r in _rows(telemetry.QUIZ_LOG):
        if start <= _when(r).date() <= today and r["department"] in deps:
            deps[r["department"]]["quiz"].append(r["score"])
            if r.get("user_id"):
                deps[r["department"]]["employees"].add(r["user_id"])
    return {"period": [start.isoformat(), today.isoformat()],
            "departments": {k: {"employees": len(v["employees"]), "simulations": v["simulations"],
                                "avoided": v["avoided"], "reported": v["reported"], "clicked": v["clicked"],
                                "quiz_avg": round(sum(v["quiz"]) / len(v["quiz"]), 3) if v["quiz"] else None}
                            for k, v in deps.items()}}


def employees() -> list[str]:
    ids = {r["user_id"] for r in _rows(telemetry.SIM_LOG)} | {r["user_id"] for r in _rows(telemetry.QUIZ_LOG) if r.get("user_id")}
    return sorted(ids)


def snapshot_week() -> str:
    """Save this week's reports (overview + every employee) to outputs/reports/<week>.json."""
    REPORTS.mkdir(parents=True, exist_ok=True)
    wk = _week(datetime.now(timezone.utc))
    data = {"week": wk, "overview": weekly_overview(), "employees": {u: progress(u) for u in employees()}}
    p = REPORTS / f"{wk}.json"
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return str(p)


# ---------------- 6. daily refresh loop ----------------
def refresh_now():
    from . import ingest
    ingest.build(do_crawl=False)
    kb.index()
    LAST_REFRESH.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def last_refresh() -> str | None:
    return LAST_REFRESH.read_text(encoding="utf-8") if LAST_REFRESH.exists() else None


def _loop():
    while True:
        try:
            lr = last_refresh()
            if not lr or datetime.now(timezone.utc) - datetime.fromisoformat(lr) > timedelta(hours=24):
                refresh_now()
            snapshot_week()          # this week's file is kept up to date hourly
        except Exception as e:
            print("auto refresh failed:", e, flush=True)
        time.sleep(3600)


def start_auto_refresh():
    if os.environ.get("SPAI_AUTO_REFRESH", "1") != "0":
        threading.Thread(target=_loop, daemon=True, name="spai-refresh").start()
