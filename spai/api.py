"""REST API for the front end and the phishing-simulation module.

Run:   .venv/Scripts/uvicorn spai.api:app --port 8000
Docs:  http://localhost:8000/docs   (interactive Swagger UI, generated from this file)

LLM-backed endpoints (generate, judge, digest) take 10-90 s on the Gemini free tier.
"""
import json
from dataclasses import asdict
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import campaign, config, digest, export, generate, judge, kb, llm, memory, telemetry

app = FastAPI(title="SecurityPolicy AI API", version="1.0",
              description="Security awareness content: grounded generation, review, memory, telemetry.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DRAFTS = config.OUTPUTS / "drafts"
APPROVED = config.OUTPUTS / "approved"
DRAFTS.mkdir(parents=True, exist_ok=True)
APPROVED.mkdir(parents=True, exist_ok=True)

Format = Literal["newsletter", "tip", "quiz", "poster", "phishing_sim", "policy_summary"]


# ---------------- models ----------------
class GenerateIn(BaseModel):
    topic: str = Field(..., examples=["QR-code phishing (quishing)"])
    audience: str = "All staff"
    format: Format = "newsletter"
    language: Literal["English", "Hindi", "Telugu"] = "English"
    use_rag: bool = True
    use_memory: bool = True
    use_telemetry: bool = True
    policy_text: str = ""
    extra: str = ""
    review: bool = Field(True, description="Run the judge right away (one more LLM call)")


class QuizSubmitIn(BaseModel):
    department: str
    answers: list[int | None] = Field(..., description="Chosen option index per question, null if skipped")


class SimEventIn(BaseModel):
    department: str
    user_id: str = Field(..., description="Pseudonymous id; never send real names or emails")
    action: Literal["delivered", "opened", "clicked", "submitted_data", "reported"]


class CampaignIn(BaseModel):
    draft_id: str
    department: str
    recipients: int = Field(10, ge=1, le=200)


class DigestIn(BaseModel):
    days: int = Field(14, ge=1, le=90)


class RefreshIn(BaseModel):
    crawl: bool = Field(False, description="Spend Firecrawl credits on targets not cached yet")


# ---------------- helpers ----------------
def _path(draft_id: str):
    for folder in (APPROVED, DRAFTS):
        p = folder / f"{draft_id}.json"
        if p.exists():
            return p
    raise HTTPException(404, f"draft {draft_id} not found")


def _load(draft_id: str) -> dict:
    return json.loads(_path(draft_id).read_text(encoding="utf-8"))


def _save(d: dict, folder=DRAFTS):
    (folder / f"{d['id']}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


def _llm_guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except llm.LLMError as e:
        raise HTTPException(503, f"LLM unavailable (free-tier quota or busy models): {str(e)[:300]}")


def _check_audience(a: str):
    if a not in generate.AUDIENCES:
        raise HTTPException(422, f"audience must be one of {generate.AUDIENCES}")


# ---------------- meta ----------------
@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "kb_chunks": kb.stats()["chunks"], "approved_modules": len(memory.modules())}


@app.get("/meta", tags=["meta"])
def meta():
    """Options for front-end dropdowns."""
    return {"audiences": generate.AUDIENCES, "departments": config.org()["departments"],
            "formats": generate.FORMATS, "languages": generate.LANGUAGES,
            "organisation": config.org()["name"], "report_address": config.org()["report_address"],
            "sim_actions": list(telemetry.SIM_ACTIONS)}


# ---------------- content ----------------
@app.post("/generate", tags=["content"])
def generate_content(body: GenerateIn):
    """Create a grounded draft (and review it unless review=false). Returns the full draft."""
    _check_audience(body.audience)
    if body.format == "policy_summary" and not body.policy_text.strip():
        raise HTTPException(422, "policy_summary needs policy_text")
    req = generate.Request(**body.model_dump(exclude={"review"}))
    d = asdict(_llm_guard(generate.generate, req, use_cache=False))
    if body.review:
        d["review"] = _llm_guard(judge.judge, d, use_cache=False)
    _save(d)
    return d


@app.get("/drafts", tags=["content"])
def list_drafts(limit: int = 50):
    files = sorted(DRAFTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for p in files:
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"id": d["id"], "title": d["content"].get("title"), "created": d.get("created"),
                    **{k: d["request"][k] for k in ("topic", "audience", "format", "language")},
                    "approved": (APPROVED / p.name).exists(),
                    "metrics": d.get("review", {}).get("metrics")})
    return out


@app.get("/drafts/{draft_id}", tags=["content"])
def get_draft(draft_id: str):
    return _load(draft_id)


@app.post("/drafts/{draft_id}/review", tags=["content"])
def review_draft(draft_id: str):
    d = _load(draft_id)
    d["review"] = _llm_guard(judge.judge, d, use_cache=False)
    _save(d)
    return d["review"]


@app.post("/drafts/{draft_id}/approve", tags=["content"])
def approve_draft(draft_id: str):
    """Reviewer approves: stored in memory (future content builds on it and avoids repeating it)."""
    d = _load(draft_id)
    if (APPROVED / f"{draft_id}.json").exists():
        raise HTTPException(409, "already approved")
    entry = memory.remember_module(d)
    _save(d, APPROVED)
    return {"approved": draft_id, "module": {k: v for k, v in entry.items() if k != "embedding"}}


@app.get("/drafts/{draft_id}/export", tags=["content"])
def export_draft(draft_id: str, fmt: Literal["md", "docx"] = "md"):
    d = _load(draft_id)
    if fmt == "md":
        return Response(export.to_markdown(d), media_type="text/markdown",
                        headers={"Content-Disposition": f'attachment; filename="{draft_id}.md"'})
    return Response(export.to_docx(d),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{draft_id}.docx"'})


@app.get("/modules", tags=["content"])
def approved_modules():
    return [{k: v for k, v in m.items() if k != "embedding"} for m in memory.modules()]


# ---------------- quizzes (E3) ----------------
@app.get("/quizzes", tags=["quiz"])
def quizzes():
    out = []
    for p in APPROVED.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d["content"].get("quiz"):
            out.append({"id": d["id"], "title": d["content"]["title"], "topic": d["request"]["topic"],
                        "audience": d["request"]["audience"],
                        # answers are hidden; they are checked on submit
                        "questions": [{"question": q["question"], "options": q["options"]}
                                      for q in d["content"]["quiz"]]})
    return out


@app.post("/quizzes/{draft_id}/submit", tags=["quiz"])
def submit_quiz(draft_id: str, body: QuizSubmitIn):
    d = _load(draft_id)
    qs = d["content"].get("quiz") or []
    if not qs:
        raise HTTPException(404, "not a quiz")
    if len(body.answers) != len(qs):
        raise HTTPException(422, f"expected {len(qs)} answers")
    if body.department not in config.org()["departments"]:
        raise HTTPException(422, f"department must be one of {config.org()['departments']}")
    results = [{"question": q["question"], "chosen": a, "correct_index": q["answer_index"],
                "correct": a == q["answer_index"], "explanation": q["explanation"]}
               for a, q in zip(body.answers, qs)]
    score = sum(r["correct"] for r in results) / len(qs)
    memory.remember_quiz(body.department, d["request"]["topic"], score, len(qs))
    return {"score": score, "results": results}


# ---------------- phishing simulation (E2) ----------------
@app.get("/simulations", tags=["simulation"])
def simulations(approved_only: bool = True):
    """Phishing-simulation kits. Each has the training email, red flags and a debrief page."""
    folders = [APPROVED] if approved_only else [APPROVED, DRAFTS]
    out, seen = [], set()
    for f in folders:
        for p in f.glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            if d["content"].get("phishing_sim") and d["id"] not in seen:
                seen.add(d["id"])
                out.append({"id": d["id"], "title": d["content"]["title"], "topic": d["request"]["topic"],
                            "audience": d["request"]["audience"], "email": d["content"]["phishing_sim"],
                            "debrief_markdown": d["content"].get("body_markdown", ""),
                            "approved": f == APPROVED})
    return out


@app.post("/simulations/{draft_id}/events", tags=["simulation"])
def sim_event(draft_id: str, body: SimEventIn):
    """Record what a recipient did with a training email. Clicks feed the department's mistake profile."""
    d = _load(draft_id)
    if not d["content"].get("phishing_sim"):
        raise HTTPException(404, "not a phishing simulation")
    if body.department not in config.org()["departments"]:
        raise HTTPException(422, f"department must be one of {config.org()['departments']}")
    telemetry.record_sim_event(draft_id, body.department, body.user_id, body.action, d["request"]["topic"])
    return {"recorded": body.action}


@app.get("/simulations/{draft_id}/stats", tags=["simulation"])
def sim_stats(draft_id: str):
    if not telemetry.SIM_LOG.exists():
        return {"draft_id": draft_id, "by_department": {}}
    rows = [json.loads(l) for l in telemetry.SIM_LOG.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r["draft_id"] == draft_id]
    by = {}
    for r in rows:
        dep = by.setdefault(r["department"], {a: set() for a in telemetry.SIM_ACTIONS})
        dep[r["action"]].add(r["user_id"])
    return {"draft_id": draft_id,
            "by_department": {k: {a: len(u) for a, u in v.items()} for k, v in by.items()}}


# ---------------- org insights (E1) ----------------
@app.get("/profile", tags=["insights"])
def profile():
    return telemetry.profile()


@app.get("/profile/{department}", tags=["insights"])
def profile_dept(department: str, n: int = 10):
    _check_audience(department)
    return telemetry.mistakes_for(department, n)


@app.post("/profile/rebuild", tags=["insights"])
def rebuild_profile(bg: BackgroundTasks, seed_memory: bool = True):
    """Recompute mistakes from all telemetry (logs, NEST-Phish, quizzes, simulations)."""
    prof = telemetry.build_profile()
    if seed_memory:
        bg.add_task(memory.seed)          # Memento ingestion is slow; run after responding
    return {d: len(v) for d, v in prof.items()}


# ---------------- knowledge ----------------
@app.post("/digest", tags=["knowledge"])
def threat_digest(body: DigestIn):
    return _llm_guard(digest.digest, body.days)


@app.get("/kb/stats", tags=["knowledge"])
def kb_stats():
    return kb.stats()


@app.get("/kb/search", tags=["knowledge"])
def kb_search(q: str, k: int = 6):
    return [{key: h[key] for key in ("score", "title", "url", "source", "kind", "date", "age_days")}
            | {"excerpt": h["text"][:400]} for h in kb.retrieve(q, k=k)]


@app.post("/kb/refresh", tags=["knowledge"])
def kb_refresh(body: RefreshIn, bg: BackgroundTasks):
    """Re-pull feeds (and optionally crawl), then index new chunks. Runs in the background."""
    from . import ingest

    def job():
        ingest.build(do_crawl=body.crawl)
        kb.index()
    bg.add_task(job)
    return {"started": True, "crawl": body.crawl}


# ---------------- evaluation ----------------
@app.get("/eval/summary", tags=["evaluation"])
def eval_summary():
    res = config.ROOT / "eval" / "results"
    if not (res / "rows.jsonl").exists():
        return {"rows": [], "summary": {}}
    rows = [json.loads(l) for l in (res / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    import pandas as pd
    df = pd.DataFrame(rows)
    num = [c for c in ("factuality", "citation_cov", "freshness", "consistency", "relevance", "style", "clarity")
           if c in df]
    summ = df.groupby("setup")[num].mean().round(3)
    return {"n_topics": int(df.topic_id.nunique()), "rows": rows,
            "summary": json.loads(summ.to_json(orient="index"))}


# ---------------- simulation campaigns (local inbox) ----------------
@app.post("/campaigns", tags=["simulation"])
def create_campaign(body: CampaignIn, request: Request):
    """Send an approved simulation kit to N pseudonymous recipients (local inbox pages, no real email)."""
    d = _load(body.draft_id)
    if not d["content"].get("phishing_sim"):
        raise HTTPException(404, "not a phishing simulation")
    if not (APPROVED / f"{body.draft_id}.json").exists():
        raise HTTPException(409, "approve the simulation before launching it")
    if body.department not in config.org()["departments"]:
        raise HTTPException(422, f"department must be one of {config.org()['departments']}")
    return _campaign_out(campaign.create(d, body.department, body.recipients), request)


@app.get("/campaigns", tags=["simulation"])
def list_campaigns(request: Request):
    return [_campaign_out(c, request) for c in campaign.listing()]


def _campaign_out(c, request):
    base = str(request.base_url).rstrip("/")
    return {k: c[k] for k in ("id", "draft_id", "title", "topic", "department", "created")} | {
        "funnel": campaign.funnel(c),
        "inbox_links": [{"user": u, "url": f"{base}/inbox/{c['id']}/{t}"} for t, u in c["recipients"].items()]}


def _recipient(cid, token):
    c, user = campaign.resolve(cid, token)
    if not c:
        raise HTTPException(404, "unknown link")
    return c, user, _load(c["draft_id"]), f"/inbox/{cid}/{token}"


@app.get("/inbox/{cid}/{token}", response_class=HTMLResponse, include_in_schema=False)
def inbox(cid: str, token: str):
    c, user, d, base = _recipient(cid, token)
    campaign.record(c, user, "opened")
    return campaign.inbox_page(c, d, base)


@app.get("/inbox/{cid}/{token}/click", response_class=HTMLResponse, include_in_schema=False)
def inbox_click(cid: str, token: str):
    c, user, d, base = _recipient(cid, token)
    campaign.record(c, user, "clicked")
    return campaign.landing_page(base)


@app.post("/inbox/{cid}/{token}/submit", response_class=HTMLResponse, include_in_schema=False)
def inbox_submit(cid: str, token: str):
    c, user, d, _ = _recipient(cid, token)   # form fields are deliberately never read
    campaign.record(c, user, "submitted_data")
    return campaign.debrief_page(d, caught=False)


@app.post("/inbox/{cid}/{token}/report", response_class=HTMLResponse, include_in_schema=False)
def inbox_report(cid: str, token: str):
    c, user, d, _ = _recipient(cid, token)
    campaign.record(c, user, "reported")
    return campaign.debrief_page(d, caught=True)


# ---------------- web UI ----------------
app.mount("/ui", StaticFiles(directory=config.ROOT / "web", html=True), name="ui")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")
