# SecurityPolicy AI: Security Awareness Content Assistant

Keeps security awareness content **current** (Firecrawl + live feeds), **consistent** (Memento memory),
and **targeted** (real behaviour telemetry). Gemini writes it, and a judge model checks it before review.

## Run it locally (Windows)
Double-click **`start.bat`**. The first run installs everything, asks for your Gemini key in `.env`,
builds the knowledge base (~5-10 min), then opens **http://localhost:8000**.

| Page | For |
|---|---|
| **Create** | Topic + audience + format → grounded draft with citations, quality score, approve, Word/Markdown export |
| **Library** | All drafts and approved modules |
| **Simulate** | Launch an approved phishing-simulation email to pseudonymous recipients; live funnel (opened → clicked → entered data → reported) |
| **Insights** | Recurring mistakes per department ("Teach this" pre-fills Create), threat-feed digest, evaluation results |
| `/ui/learn.html` | Employee quiz page |
| `/docs` | API reference |

Docker instead: `docker compose up --build` (needs `.env`).

## Manual setup (fresh clone, Windows)
```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env            # paste your own GEMINI_API_KEY and FIRECRAWL_API_KEY
.venv\Scripts\python scripts\setup.py          # downloads, builds KB + profiles + memory (~5-10 min)
.venv\Scripts\python -m pytest                 # 13 offline tests, no API quota used
.venv\Scripts\uvicorn spai.api:app --port 8000 # backend API → http://localhost:8000/docs
.venv\Scripts\streamlit run app.py             # older Streamlit demo (optional)
```
- Free Gemini key: https://aistudio.google.com/app/apikey. Free Firecrawl key: https://www.firecrawl.dev/signin
  (only needed for `--crawl`; the crawl cache is committed).
- **Front-end / simulation developers: read [docs/API.md](docs/API.md).**

## Maintenance commands
```powershell
.venv\Scripts\python -m spai.ingest --crawl    # crawl new targets in config/sources.yaml + refresh feeds
.venv\Scripts\python -m spai.kb                # index new chunks
.venv\Scripts\python -m spai.telemetry         # rebuild department mistake profiles
.venv\Scripts\python -m eval.run_eval --n 5    # ablation study → eval/results/ (resumes; waits out quota)
```

## Modules (`spai/`)
| File | Feature |
|---|---|
| `ingest.py` | M1 Firecrawl crawl of whitelisted sites (cached), M2 RSS + CISA KEV, NIST PDFs, MITRE techniques |
| `kb.py` | M3 chunk → Gemini embeddings → ChromaDB; retrieval with freshness boost and source diversity |
| `telemetry.py` | E1 APT-Hunter detections + NEST-Phish responses + quiz scores → per-department mistakes |
| `memory.py` | M4/M7 Memento knowledge graph + approved-module registry (non-repetition) |
| `generate.py` | M5/M6 grounded generation with [S#] citations; formats: newsletter, tip, quiz (E3), poster, phishing_sim (E2), policy_summary (S4); audiences (S1); languages (S5); compliance tags (S6) |
| `guardrails.py` | E4 trusted-link check, simulation defanging (example.com only), citation validity |
| `judge.py` | E4/E5/S3 LLM judge: claim-by-claim fact check, contradictions, relevance/style/clarity; computed freshness + novelty |
| `digest.py` | S2 what's new in the feeds that we haven't covered |
| `export.py` | Markdown / Word export |
| `llm.py` | Gemini model fallback chain, retries, disk cache, free-tier-aware embedding throttle |
| `api.py` | FastAPI backend: content, review, approve, export, quizzes, phishing-simulation events, profiles, digest, KB, eval |
| `campaign.py` | E2 local phishing-simulation campaigns: inbox, landing and debrief pages, funnel |
| `web/` | Web UI (plain HTML/JS, served by the API at `/ui/`) |
| `app.py` | Streamlit demo UI: generate → review → approve, quiz, insights, digest, KB search, history, evaluation |

## Data
| Path | What |
|---|---|
| `config/sources.yaml` | Trusted sources (only these can be cited) |
| `config/behaviour_map.csv` | APT-Hunter rule → employee behaviour → MITRE → training topic |
| `config/org.yaml` | **Simulated** org: departments, host owners, thresholds |
| `config/style_guide.md` | Org messaging rules (seeded into memory) |
| `resources/` | CISA KEV, MITRE ATT&CK, NIST SP 800-50r1 + CSF 2.0, NEST-Phish (CC BY-SA 4.0), phishing corpus, APT-Hunter fork |

## Data notes
- `data/raw/firecrawl/` is committed so a clone needs no Firecrawl credits.
- `data/telemetry/apt_hunter_summary.csv` is an **anonymised aggregate** of APT-Hunter output. The raw report
  (real machine and user names) is never committed. To use your own logs, run APT-Hunter and put the report in
  `data/telemetry/sample_org/`.
- `resources/datasets/nest_phish/`: NEST-Phish, Nebulon Synthetic Enterprise Phishing Email Dataset,
  CC BY-SA 4.0 (see its README for citation).

## Honest limitations
- Department assignment is simulated; the mistakes themselves come from real data (one Windows host, 30 NEST-Phish participants → ~4 per department, so rates are noisy).
- The judge is itself an LLM; scores are indicative. Validate with a small human rating.
- Free-tier quotas: embeddings 100 texts / 30k tokens per minute; everything is cached so reruns cost nothing.
