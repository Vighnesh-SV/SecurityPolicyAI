# SecurityPolicy AI — Security Awareness Content Assistant

## 1. The brief (what is asked)
Security awareness teams must keep training material aligned with current threats and
organisational messaging.
- **Firecrawl** gathers current public security guidance.
- **Memento** stores previous training content and recurring employee mistakes.
- **LLM** creates updated awareness material.
- **Outcome:** awareness content stays current and consistent.

## 2. Our one-line pitch
An adaptive, telemetry-grounded RAG + memory system that writes cited, consistent security
awareness content targeted at an organisation's real weak spots, and measures how much each
component helps.

## 3. Features

### 3.1 Minimum (must have, covers the brief)
| # | Feature | Brief part |
|---|---|---|
| M1 | Source crawler: Firecrawl scrapes a whitelist of trusted sites (CISA, CERT-In, NCSC, OWASP…) and caches the markdown | Firecrawl |
| M2 | Feed ingest: CISA KEV JSON + RSS news feeds | Current threats |
| M3 | Knowledge base: chunk, embed (Gemini embeddings), store in ChromaDB with source/date metadata | RAG |
| M4 | Memento memory: past modules, org style guide, recurring mistakes per department | Memento |
| M5 | Content generator: topic + audience + format → newsletter / quiz / tip / poster text, written with Gemini | LLM |
| M6 | Citations: every claim links to a retrieved source | Consistency/trust |
| M7 | Review and approve: approved content is saved back into Memento | Consistency |
| M8 | Streamlit UI: generate, review, history, export (MD/DOCX/PDF) | Usability |

### 3.2 Extras, core (planned, these make the project stand out)
| # | Feature |
|---|---|
| E1 | **Telemetry-driven mistakes:** APT-Hunter detections → behaviour categories (MITRE-tagged) → Memento |
| E2 | **Phishing simulation kit:** safe, clearly marked training phish + "red flags" debrief |
| E3 | **Adaptive quizzes:** questions weighted to each department's mistake history; scores feed back to memory |
| E4 | **Guardrails:** source whitelist, mandatory citations, LLM-judge factuality check |
| E5 | **Evaluation + ablation:** LLM-only vs +Firecrawl vs +Memento vs +Telemetry; metrics in §6 |
| E6 | **MITRE ATT&CK tagging:** threats, mistakes and content share technique IDs |

### 3.3 Extras, stretch (only if time allows)
| # | Feature |
|---|---|
| S1 | Role-based variants (Finance / HR / Dev / Exec) |
| S2 | Weekly threat-digest agent: flags new topics not yet covered |
| S3 | Consistency checker: catches contradictions with earlier modules or policy |
| S4 | Policy explainer: upload a policy PDF → plain-English summary + FAQ |
| S5 | Multilingual output (English / Hindi / Telugu) |
| S6 | Compliance tags (ISO 27001 A.6.3, NIST CSF PR.AT, CERT-In) |

Out of scope: employee chatbot, gamification, Teams/Slack delivery.

## 4. Architecture
```
Trusted URLs ─Firecrawl─┐
CISA KEV / RSS ─────────┼─► clean + chunk ─► Gemini embeddings ─► ChromaDB
                        │
APT-Hunter CSV output ─► behaviour mapper (MITRE) ─┐
Past modules, style guide ─────────────────────────┼─► Memento memory
Quiz results / approvals (feedback) ───────────────┘
                                   │
User request (topic, audience, format)
        ▼
Orchestrator: retrieve threats (Chroma) + memories (Memento) → prompt
        ▼
Gemini Flash → draft ─► Judge (Gemini Flash): citations, facts, consistency
        ▼
Streamlit review → approve → export + write back to Memento
```

## 5. Tech stack
| Layer | Choice |
|---|---|
| Language | Python 3.12 (venv in `.venv`) |
| LLM | Gemini 3.x Flash (generator + judge, fallback list in `config/models.yaml`), via `google-genai`, free key from aistudio.google.com |
| Embeddings | Gemini embedding model |
| Scraping | `firecrawl-py` (free credits; cache everything to `data/raw`) |
| Memory | `memento-memory` (Python, local). Fallback/upgrade: gannonh/memento-mcp (Node + Neo4j), cloned in `resources/repos` |
| Vector DB | ChromaDB (local) |
| UI | Streamlit |
| Other | pypdf, feedparser, pandas, langchain-text-splitters, python-docx, reportlab, APScheduler |

## 6. Evaluation plan
| Metric | How |
|---|---|
| Freshness | % of cited sources from the last 90 days |
| Factuality | Judge checks each claim against its cited chunk |
| Consistency | Contradictions with past modules/policy (judge) |
| Relevance | Overlap between content topics and the org's top mistakes |
| Non-repetition | Similarity to previous modules (embedding cosine) |
| Human rating | 5–10 people score drafts 1–5 on clarity/usefulness |

Ablation: A = LLM only, B = A + Firecrawl RAG, C = B + Memento, D = C + Telemetry.
Same 20 topic prompts for every setup.

## 7. Phases
| Phase | Deliverable |
|---|---|
| 0 | Setup: folders, venv, resources, API keys **(done except keys)** |
| 1 | Ingest: Firecrawl + KEV + RSS → ChromaDB (M1–M3) |
| 2 | Generator with citations + basic Streamlit (M5, M6, M8) |
| 3 | Memento memory + approve/write-back loop (M4, M7) |
| 4 | Telemetry from APT-Hunter + MITRE tagging (E1, E6) |
| 5 | Phishing kit + adaptive quiz + guardrails (E2–E4) |
| 6 | Evaluation + ablation + report (E5) |
| 7 | Stretch features if time allows (S1–S6) |

## 8. Ready-made resources (in `resources/`)
| Path | What |
|---|---|
| `feeds/cisa_kev.json` | CISA Known Exploited Vulnerabilities (1,790 entries) |
| `mitre/enterprise-attack.json` | MITRE ATT&CK Enterprise STIX (867 techniques) |
| `standards/NIST.SP.800-50r1.pdf` | NIST guide to building an awareness/training program |
| `standards/NIST.CSWP.29_CSF2.pdf` | NIST Cybersecurity Framework 2.0 |
| `datasets/phishing_email_hf.csv` | ~18.6k labelled emails (safe/phishing) for examples and evaluation |
| `repos/APT-Hunter-CSV` | Our fork, the telemetry source (GPL-3.0: run it separately, read its CSV output, don't copy its code) |
| `repos/memento-mcp` | Neo4j Memento (reference / optional upgrade) |

## 9. Crawl whitelist (Firecrawl targets)
- CISA: cisa.gov/secure-our-world, cisa.gov/news-events/cybersecurity-advisories
- CERT-In: cert-in.org.in (advisories)
- NCSC UK: ncsc.gov.uk/collection/top-tips-for-staff
- ENISA: enisa.europa.eu (threat landscape)
- OWASP: owasp.org (Top 10)
- Anti-Phishing Working Group: apwg.org (trends reports)
- News RSS: BleepingComputer, KrebsOnSecurity, The Hacker News

## 9b. Key-free prep (done)
| Output | What |
|---|---|
| `config/sources.yaml` | Crawl whitelist + 4 working RSS feeds (BleepingComputer blocks scripts, so it's dropped) |
| `config/behaviour_map.csv` | APT-Hunter rule → behaviour → MITRE → training topic; noise rules filtered first |
| `config/style_guide.md` | Org tone/format rules (Memento seed) |
| `eval/topics.csv` | 20 fixed evaluation topics (topic, audience, format) |
| `scripts/prep_offline.py` | Builds `data/processed/`: 706 active MITRE techniques, KEV (1,790 entries, 116 from the last 90 days), NIST 800-50r1 + CSF 2.0 text, RSS snapshot (110 items) |
| `data/telemetry/sample_org/` | APT-Hunter run on the sample logs (separate venv, ~35 s) |

Telemetry findings on the sample logs, after noise filtering: 41 suspicious PowerShell runs, 7 Defender
real-time protection changes, 2 malware detections, 1 password spray; 6,657 noise or SOC-only events ignored.
Limitation: logs come from a single machine, so per-department mistake profiles (E3) will need a
synthetic org layer (users → departments) on top. Plan that in Phase 4.

## 10. Pending from the team
1. ~~Gemini API key~~ done, tested
2. ~~Firecrawl API key~~ done, tested (1,000 credits per month)
3. ~~NEST-Phish~~ done: `resources/datasets/nest_phish` (146 emails + human responses, CC BY-SA 4.0)
4. Confirm the feature list above before Phase 1

## 11. Implementation status
| Phase | Status |
|---|---|
| 1 Ingest + KB | Done: 38 crawled pages (16 targets, ~55 Firecrawl credits), 110 RSS, 116 KEV, 118 NIST pages, 26 MITRE → 955 chunks |
| 2 Generator + UI | Done: 6 formats, 3 languages, 8 audiences; Streamlit app with 7 tabs |
| 3 Memento + approve loop | Done: style + mistake profiles seeded; approvals and quiz scores write back |
| 4 Telemetry + MITRE | Done: APT-Hunter + NEST-Phish → per-department profiles (simulated org layer) |
| 5 Phishing kit, quiz, guardrails | Done: example.com-only sims, trusted-link check, citation validity |
| 6 Evaluation | Ablation script done; first 5-topic run in `eval/results/` |
| 7 Stretch | S1 audiences, S2 digest, S3 consistency (judge), S4 policy explainer, S5 languages, S6 compliance tags: all in |

### Decisions made during the build
- **Embeddings are local** (`BAAI/bge-small-en-v1.5`). The Gemini free tier allows only 1,000 embedding
  requests per day (queries included) plus 30k tokens/min; the first index used the whole day's quota.
  `gemini-embedding-2` was also unusable for batches (it merges a batch into one vector).
- **Model fallback with benching.** gemini-3.8/3.7-flash are often "high demand" (503). The SDK's internal
  retries were disabled; a busy model is skipped for 10 minutes and the next one in `config/models.yaml` is used.
- Generator prompt forbids mentioning earlier training unless it is in the approved-module registry
  (a test draft invented "last month we covered…").
- Dropped sources: BleepingComputer RSS (403 to scripts), NCSC small-business guide (returns no pages).
