"""E2: local phishing-simulation campaigns.

A campaign sends one approved simulation kit to N pseudonymous recipients of a department.
Each recipient gets a private inbox link. Everything they do (open, click, enter data, report)
is recorded through telemetry.record_sim_event, so clicks feed the department's mistake profile.

Nothing is emailed: the "inbox" is a local web page. Typed data is never stored.
"""
import html
import json
import secrets
from datetime import datetime, timezone

from . import config, telemetry

CAMPAIGNS = config.TELEMETRY / "campaigns.json"


def _all() -> dict:
    return json.loads(CAMPAIGNS.read_text(encoding="utf-8")) if CAMPAIGNS.exists() else {}


def _write(c: dict):
    CAMPAIGNS.write_text(json.dumps(c, indent=1), encoding="utf-8")


def create(draft: dict, department: str, n: int) -> dict:
    cid = secrets.token_hex(4)
    users = {secrets.token_hex(5): f"{department[:3].lower()}-{i + 1:03d}" for i in range(n)}
    c = {"id": cid, "draft_id": draft["id"], "title": draft["content"]["title"],
         "topic": draft["request"]["topic"], "department": department,
         "created": datetime.now(timezone.utc).isoformat(), "recipients": users}
    allc = _all()
    allc[cid] = c
    _write(allc)
    for uid in users.values():
        telemetry.record_sim_event(draft["id"], department, uid, "delivered", c["topic"], cid)
    return c


def get(cid: str) -> dict | None:
    return _all().get(cid)


def listing() -> list[dict]:
    return sorted(_all().values(), key=lambda c: c["created"], reverse=True)


def resolve(cid: str, token: str):
    c = get(cid)
    if not c or token not in c["recipients"]:
        return None, None
    return c, c["recipients"][token]


def record(c: dict, user: str, action: str):
    """Record once per user and action."""
    if telemetry.SIM_LOG.exists():
        for line in telemetry.SIM_LOG.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if _same(r, c) and r["user_id"] == user and r["action"] == action:
                return
    telemetry.record_sim_event(c["draft_id"], c["department"], user, action, c["topic"], c["id"])


def _same(r: dict, c: dict) -> bool:
    """Event belongs to campaign c (older events have no campaign_id: match by draft)."""
    return r.get("campaign_id") == c["id"] if r.get("campaign_id") else r["draft_id"] == c["draft_id"]


def funnel(c: dict) -> dict:
    users = set(c["recipients"].values())
    seen = {a: set() for a in telemetry.SIM_ACTIONS}
    if telemetry.SIM_LOG.exists():
        for line in telemetry.SIM_LOG.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if _same(r, c) and r["user_id"] in users:
                seen[r["action"]].add(r["user_id"])
    return {a: len(u) for a, u in seen.items()}


# ---------------- recipient pages (plain server-rendered HTML) ----------------
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<link rel="stylesheet" href="/ui/app.css?v=1795669216"></head><body class="recipient"><main class="narrow">{body}</main></body></html>"""


def _e(s) -> str:
    return html.escape(str(s or ""))


def inbox_page(c: dict, draft: dict, base: str) -> str:
    sim = draft["content"]["phishing_sim"]
    body = _e(sim.get("body", "")).replace("\n", "<br>")
    link = f'<a class="btn" href="{base}/click">Open the link in this email</a>'
    return PAGE.format(title="Inbox", body=f"""
<p class="muted small">Training inbox Â· {_e(sim.get('training_marker'))}</p>
<article class="card mail">
  <div class="mail-head"><div><b>From:</b> {_e(sim.get('sender'))}</div>
  <div><b>Subject:</b> {_e(sim.get('subject'))}</div></div>
  <div class="mail-body">{body}</div>
  <div class="row">{link}</div>
</article>
<form method="post" action="{base}/report"><button class="btn ghost">Report as phishing</button></form>""")


def landing_page(base: str) -> str:
    return PAGE.format(title="Sign in", body=f"""
<article class="card">
  <h2>Sign in to continue</h2>
  <form method="post" action="{base}/submit" autocomplete="off">
    <input name="u" placeholder="Email"><input name="p" type="password" placeholder="Password">
    <button class="btn">Sign in</button>
  </form>
  <p class="muted small">Training page. Do not type real credentials. Nothing you type is stored.</p>
</article>""")


def debrief_page(draft: dict, caught: bool, user: str = "") -> str:
    sim = draft["content"]["phishing_sim"]
    head = ("<h2>Well done: you reported it.</h2><p>This was a security-awareness simulation.</p>" if caught
            else "<h2>This was a phishing simulation.</h2><p>No harm done. Here is what to look for next time.</p>")
    flags = "".join(f"<li>{_e(f)}</li>" for f in sim.get("red_flags") or draft["content"].get("red_flags") or [])
    report = _e(draft["content"].get("report_how") or f"Report to {config.org()['report_address']}")
    return PAGE.format(title="Training debrief", body=f"""
<article class="card">{head}
  <h3>Red flags in this email</h3><ul>{flags}</ul>
  <h3>How to report</h3><p>{report}</p>
  <p><a class="btn ghost" href="/ui/learn.html?u={_e(user)}#progress">See your progress</a></p>
</article>""")
