# Backend API guide (for the front end and the phishing-simulation module)

Start: `.venv\Scripts\uvicorn spai.api:app --port 8000`
Interactive docs with "Try it out": **http://localhost:8000/docs** (always matches the code).
CORS is open, so a dev server on any port can call it.

> **Latency:** endpoints marked 🐢 call Gemini and take **10–90 s**. Show a spinner and set the
> client timeout to at least 180 s. On the free tier each model allows ~20 requests/day; when
> they run out these endpoints return **503** with a message. Show it and let the user retry later.

## Endpoints

| Method | Path | Use |
|---|---|---|
| GET | `/health` | Up? KB chunk count, approved module count |
| GET | `/meta` | Dropdown options: audiences, departments, formats (with descriptions), languages, sim actions |
| POST 🐢 | `/generate` | Create a draft (+ judge review unless `review:false`) |
| GET | `/drafts?limit=50` | Recent drafts (id, title, topic, audience, format, approved, metrics) |
| GET | `/drafts/{id}` | Full draft |
| POST 🐢 | `/drafts/{id}/review` | Re-run the judge |
| POST | `/drafts/{id}/approve` | Approve → saved to memory (future content builds on it) |
| GET | `/drafts/{id}/export?fmt=md\|docx` | File download |
| GET | `/modules` | Approved-module history |
| GET | `/quizzes` | Approved quizzes **without answers** |
| POST | `/quizzes/{id}/submit` | `{department, answers:[int\|null], user_id?}` → score + per-question feedback |
| GET | `/simulations?approved_only=true` | Phishing-simulation kits: training email + debrief |
| POST | `/simulations/{id}/events` | `{department, user_id, action}` record a recipient action |
| GET | `/simulations/{id}/stats` | Unique users per action per department |
| POST | `/campaigns` | `{draft_id, department, recipients}` → pseudonymous inbox links (approved kits only) |
| GET | `/campaigns` | Campaigns with funnel counts and inbox links |
| GET | `/inbox/{cid}/{token}` | Recipient's training inbox (records opened; link → click → fake sign-in → debrief; report button) |
| POST 🐢 | `/check` | `{text}` → "Is this phishing?" verdict, warning signs, what to do (rules always; AI text when quota allows) |
| GET | `/progress/{user_id}?days=7` | One employee's weekly report: avoided, reported, clicked, quiz average, streak, tips |
| GET | `/reports/weekly` | Department totals for the week (no ranking of individuals) |
| POST | `/reports/snapshot` | Save this week's reports to `outputs/reports/<week>.json` (also automatic, hourly) |
| GET | `/trends/{dept}` | Weekly click rate / report rate / quiz average + before→after change |
| GET | `/modules/staleness` | Approved modules overtaken by newer guidance ("update suggested") |
| GET | `/profile` / `/profile/{dept}?n=10` | Recurring mistakes per department |
| POST | `/profile/rebuild` | Recompute mistakes from logs + NEST + quizzes + simulations |
| POST 🐢 | `/digest` | `{days}` → suggested new topics from recent feeds |
| GET | `/kb/stats`, `/kb/search?q=&k=6` | Knowledge-base size / search |
| POST | `/kb/refresh` | `{crawl:false}` re-pull feeds and re-index (background) |
| GET | `/eval/summary` | Ablation results (A/B/C/D) |

## Main flows

**1. Content studio**
```
GET  /meta                         → fill dropdowns
POST /generate {topic, audience, format, language}
     → show content.title, content.body_markdown, red_flags, actions, report_how,
       quiz[] or phishing_sim, sources[], review.metrics, review.judge.claims (non-"supported" = warnings),
       guardrails.untrusted_links (block approval if non-empty)
POST /drafts/{id}/approve          → "Approved"
GET  /drafts/{id}/export?fmt=docx  → download
```

**2. Phishing simulation**

Built in: the **Simulate** page (or `POST /campaigns`) creates recipients and local inbox pages that
record every action automatically. The manual event API below is for an external simulator.
```
GET  /simulations                         → pick a kit: email.sender / email.subject / email.body
                                            (always example.com; email.training_marker must stay
                                             in the message metadata)
(send the email in your simulator to pseudonymous users, e.g. "u017")
POST /simulations/{id}/events {department:"Finance", user_id:"u017", action:"opened"}
POST /simulations/{id}/events {..., action:"clicked"}          → landing page shows debrief_markdown
POST /simulations/{id}/events {..., action:"submitted_data"}   (never store what they typed)
POST /simulations/{id}/events {..., action:"reported"}         → "well done" page
GET  /simulations/{id}/stats              → dashboard
POST /profile/rebuild                     → a click rate ≥ 25% becomes a recurring mistake,
                                            so the next generated content targets it
```
Actions: `delivered`, `opened`, `clicked`, `submitted_data`, `reported`.

**Automatic jobs** (started with the API; `SPAI_AUTO_REFRESH=0` disables): feeds are refreshed and re-indexed
once a day, and the weekly report snapshot is kept up to date every hour.

**3. Quiz**
```
GET  /quizzes                       → questions + options (no answers)
POST /quizzes/{id}/submit {department, answers:[0,2,1,null,3]}
     → {score, results:[{correct, correct_index, explanation}]}
```

## Draft object (abridged)
```json
{
  "id": "2092fa0aac",
  "request": {"topic": "...", "audience": "Finance", "format": "phishing_sim", "language": "English", ...},
  "content": {
    "title": "...", "summary": "...", "body_markdown": "... [S1] ... [ORG] ...",
    "key_points": [], "red_flags": [], "actions": [], "report_how": "...",
    "quiz": [{"question": "...", "options": ["","","",""], "answer_index": 2, "explanation": "...", "targets_mistake": "..."}],
    "phishing_sim": {"sender": "...@x.example.com", "subject": "...", "body": "...", "red_flags": [], "training_marker": "SECURITY AWARENESS TRAINING SIMULATION - NOT A REAL EMAIL"},
    "citations": [{"id": "S1", "used_for": "..."}], "mitre": ["T1566"], "compliance": ["ISO/IEC 27001:2022 A.6.3"],
    "targets_mistakes": ["..."]
  },
  "sources": [{"title": "...", "url": "...", "source": "fbi_bec", "kind": "guidance", "date": "2026-11-22", "age_days": 1, "excerpt": "..."}],
  "mistakes": [{"behaviour": "...", "evidence": "...", "source": "nest-phish", "mitre": "T1566"}],
  "past_modules": [{"title": "...", "similarity": 0.73}],
  "guardrails": {"untrusted_links": [], "sim_rewritten": [], "citations": {"cited_ids": [1, 4], "invalid_ids": [], "n_org": 2}},
  "review": {"metrics": {"factuality": 0.86, "citation_cov": 1.0, "freshness": 0.0, "consistency": 1,
                         "relevance": 1.0, "style": 1.0, "clarity": 1.0, "novelty": null},
             "judge": {"claims": [{"claim": "...", "cited": ["S1"], "verdict": "supported"}], "contradictions": [], "fixes": []}}
}
```
Citation markers in `body_markdown`: `[S#]` → `sources[#-1]`; `[ORG]` → internal organisation data.

## Rules for the simulation module
- Never send to real external addresses or use real brand domains; kits are pre-defanged to `example.com`.
- Use pseudonymous `user_id`s only. Don't store anything a user types on a fake login page.
- Only run simulations on people who agreed to the training programme.
