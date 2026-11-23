"""E1: turn real behaviour data into per-department "recurring mistake" profiles.

Sources
  1. APT-Hunter report (Windows logs) → config/behaviour_map.csv → employee behaviours
  2. NEST-Phish participant responses → which phishing themes / cues fool people
  3. Quiz results recorded in the app (E3 feedback loop)

python -m spai.telemetry      # writes data/telemetry/profile.json
"""
import hashlib
import json
import re
import warnings
from datetime import datetime, timezone

import pandas as pd

from . import config

PROFILE = config.TELEMETRY / "profile.json"
QUIZ_LOG = config.TELEMETRY / "quiz_results.jsonl"
SIM_LOG = config.TELEMETRY / "sim_events.jsonl"
SIM_ACTIONS = ("delivered", "opened", "clicked", "submitted_data", "reported")
APT_REPORT = config.TELEMETRY / "sample_org" / "sample_org_Report.xlsx"
# Anonymised aggregate of APT-Hunter output (no raw log lines). Shared in git instead of the raw report.
APT_SUMMARY = config.TELEMETRY / "apt_hunter_summary.csv"
NEST = config.RESOURCES / "datasets" / "nest_phish" / "participant_responses_anonymized.csv"

CUES = {
    "has_link": "emails with a link",
    "has_attachment": "emails with an attachment",
    "has_urgent_language": "urgent or threatening wording",
    "has_external_sender": "look-alike external sender domains",
    "has_request_personal_information": "requests for passwords or personal details",
    "has_generic_greeting": "generic greetings",
}
THEME_MITRE = "T1566"


def _dept_for(pid: str) -> str:
    depts = config.org()["departments"]
    return depts[int(hashlib.md5(pid.encode()).hexdigest(), 16) % len(depts)]


def apt_hunter_mistakes() -> list[dict]:
    if not APT_REPORT.exists():
        if APT_SUMMARY.exists():
            df = pd.read_csv(APT_SUMMARY).fillna({"mitre": ""})
            return [{**r, "count": int(r["count"]), "rate": None} for r in df.to_dict("records")]
        return []
    bm = pd.read_csv(config.CONFIG / "behaviour_map.csv")
    rows = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sheets = pd.read_excel(APT_REPORT, sheet_name=None)
    for name, df in sheets.items():
        if "Detection Rule" not in df:
            continue
        host_col = next((c for c in ("Computer Name", "Computer", "MachineName") if c in df), None)
        for _, r in df.iterrows():
            rule = str(r["Detection Rule"])
            m = next(row for _, row in bm.iterrows() if re.search(row.rule_regex, rule))
            if m.employee_relevant == "no":
                continue
            host = str(r[host_col]) if host_col else ""
            rows.append({"host": host, "rule": rule, "behaviour": m.behaviour,
                         "mitre": m.mitre if isinstance(m.mitre, str) else "",
                         "topic": m.training_topic})
    if not rows:
        return []
    df = pd.DataFrame(rows)
    hosts = config.org().get("hosts") or {}
    default = config.org().get("default_host_department", "IT")
    df["department"] = df["host"].map(lambda h: hosts.get(h, default))
    out = []
    for (dept, beh), g in df.groupby(["department", "behaviour"]):
        out.append({"department": dept, "behaviour": beh, "mitre": g.mitre.iloc[0],
                    "topic": g.topic.iloc[0], "count": int(len(g)), "rate": None,
                    "source": "apt-hunter",
                    "evidence": f"{len(g)} detections: " + "; ".join(g.rule.value_counts().index[:3])})
    return out


def nest_mistakes() -> list[dict]:
    if not NEST.exists():
        return []
    cfg = config.org()
    df = pd.read_csv(NEST)
    df["department"] = df["participant_id"].map(_dept_for)
    phish = df[df.true_label == "phish"].copy()
    phish["missed"] = (phish.label_acc == 0).astype(int)
    out = []
    for dept, g in phish.groupby("department"):
        # by theme: "falls for delivery-notification phishing"
        for theme, t in g.groupby("theme"):
            rate = t.missed.mean()
            if rate >= cfg["mistake_min_rate"] and t.missed.sum() >= cfg["mistake_min_count"]:
                out.append({"department": dept, "behaviour": f"Falls for '{theme}' phishing",
                            "mitre": THEME_MITRE, "topic": f"Spotting {theme.lower()} scams",
                            "count": int(t.missed.sum()), "rate": round(float(rate), 3),
                            "source": "nest-phish",
                            "evidence": f"missed {int(t.missed.sum())} of {len(t)} phishing emails"})
        # by cue: "misses phishing that uses look-alike sender domains"
        for cue, label in CUES.items():
            t = g[g[cue] == 1]
            if len(t) == 0:
                continue
            rate = t.missed.mean()
            if rate >= cfg["mistake_min_rate"] and t.missed.sum() >= cfg["mistake_min_count"]:
                out.append({"department": dept, "behaviour": f"Misses phishing with {label}",
                            "mitre": THEME_MITRE, "topic": f"Red flag: {label}",
                            "count": int(t.missed.sum()), "rate": round(float(rate), 3),
                            "source": "nest-phish",
                            "evidence": f"missed {int(t.missed.sum())} of {len(t)} such emails"})
    # over-reporting legit mail is also worth knowing (alert fatigue)
    legit = df[df.true_label == "legit"]
    for dept, g in legit.groupby("department"):
        fp = (g.label_acc == 0).mean()
        if fp >= cfg["mistake_min_rate"]:
            out.append({"department": dept, "behaviour": "Flags genuine internal emails as phishing",
                        "mitre": "", "topic": "Verifying before reporting: how to check a real email",
                        "count": int((g.label_acc == 0).sum()), "rate": round(float(fp), 3),
                        "source": "nest-phish", "evidence": f"false-alarm rate {fp:.0%}"})
    return out


def quiz_mistakes() -> list[dict]:
    if not QUIZ_LOG.exists():
        return []
    df = pd.DataFrame([json.loads(l) for l in QUIZ_LOG.read_text(encoding="utf-8").splitlines()])
    out = []
    for (dept, topic), g in df.groupby(["department", "topic"]):
        wrong = 1 - g.score.mean()
        if wrong >= config.org()["mistake_min_rate"]:
            out.append({"department": dept, "behaviour": f"Low quiz scores on '{topic}'",
                        "mitre": "", "topic": topic, "count": int(len(g)), "rate": round(float(wrong), 3),
                        "source": "quiz", "evidence": f"average score {g.score.mean():.0%} over {len(g)} attempts"})
    return out


def sim_mistakes() -> list[dict]:
    """Phishing-simulation results (from the simulation front end) → recurring mistakes."""
    if not SIM_LOG.exists():
        return []
    df = pd.DataFrame([json.loads(l) for l in SIM_LOG.read_text(encoding="utf-8").splitlines()])
    out = []
    for (dept, topic), g in df.groupby(["department", "topic"]):
        users = g.groupby("user_id")["action"].apply(set)
        n = len(users)
        clicked = sum(bool(a & {"clicked", "submitted_data"}) for a in users)
        submitted = sum("submitted_data" in a for a in users)
        reported = sum("reported" in a for a in users)
        if n and clicked / n >= config.org()["mistake_min_rate"]:
            out.append({"department": dept, "behaviour": f"Clicked a '{topic}' phishing simulation",
                        "mitre": "T1566", "topic": topic, "count": clicked, "rate": round(clicked / n, 3),
                        "source": "simulation",
                        "evidence": f"{clicked}/{n} clicked, {submitted} entered data, {reported} reported"})
    return out


def record_sim_event(draft_id: str, department: str, user_id: str, action: str, topic: str):
    if action not in SIM_ACTIONS:
        raise ValueError(f"action must be one of {SIM_ACTIONS}")
    with SIM_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"draft_id": draft_id, "department": department, "user_id": user_id,
                            "action": action, "topic": topic,
                            "at": datetime.now(timezone.utc).isoformat()}) + "\n")


def record_quiz(department: str, topic: str, score: float, n_questions: int,
                user_id: str | None = None, missed: list[str] | None = None):
    with QUIZ_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"department": department, "topic": topic, "score": score,
                            "n": n_questions, "user_id": user_id, "missed": missed or [], "at": datetime.now(timezone.utc).isoformat()}) + "\n")


def export_apt_summary():
    """Write the anonymised APT-Hunter aggregate (department, behaviour, counts, rule names only)."""
    rows = apt_hunter_mistakes()
    pd.DataFrame(rows).drop(columns=["rate"], errors="ignore").to_csv(APT_SUMMARY, index=False)
    return len(rows)


def build_profile() -> dict:
    items = apt_hunter_mistakes() + nest_mistakes() + quiz_mistakes() + sim_mistakes()
    prof = {d: [] for d in config.org()["departments"]}
    for it in items:
        prof.setdefault(it["department"], []).append(it)
    for d in prof:
        # rank: rate when known, else log-scaled count
        prof[d].sort(key=lambda x: -(x["rate"] if x["rate"] is not None else min(1.0, x["count"] / 50)))
    PROFILE.write_text(json.dumps(prof, indent=1, ensure_ascii=False), encoding="utf-8")
    return prof


def profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else build_profile()


def mistakes_for(audience: str, n: int = 5) -> list[dict]:
    p = profile()
    if audience in p:
        return p[audience][:n]
    # "All staff": org-wide top mistakes, one per behaviour
    seen, out = set(), []
    for it in sorted((x for v in p.values() for x in v),
                     key=lambda x: -(x["rate"] if x["rate"] is not None else min(1.0, x["count"] / 50))):
        if it["behaviour"] not in seen:
            seen.add(it["behaviour"])
            out.append(it)
    return out[:n]


if __name__ == "__main__":
    p = build_profile()
    for d, items in p.items():
        print(f"\n{d}: {len(items)} recurring mistakes")
        for it in items[:4]:
            r = f"{it['rate']:.0%}" if it["rate"] is not None else f"{it['count']}x"
            print(f"  {r:>5}  {it['behaviour']}  [{it['source']}]")
