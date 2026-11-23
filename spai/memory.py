"""M4 + M7: organisational memory.

- Memento (temporal knowledge graph, SQLite at memory/memento.db) holds facts: the style guide,
  each department's recurring mistakes, every approved module and quiz result.
- memory/modules.jsonl is a plain registry of approved modules (with embeddings) used for
  exact non-repetition checks and the history view.
"""
import hashlib
import json
import math
import os
import time
from datetime import date

from . import config, llm, telemetry

REGISTRY = config.MEMORY / "modules.jsonl"
SEED_STATE = config.MEMORY / "seed_state.json"


def _configure_memento():
    m = config.models()["memento"]
    os.environ.update(
        MEMENTO_LLM_PROVIDER="gemini", MEMENTO_LLM_API_KEY=config.key("GEMINI_API_KEY"),
        MEMENTO_EXTRACTION_MODEL=m["extraction"], MEMENTO_TIEBREAKER_MODEL=m["extraction"],
        MEMENTO_CHAT_MODEL=m["chat"], MEMENTO_DB_PATH=str(config.MEMORY / "memento.db"),
        HF_HUB_DISABLE_SYMLINKS_WARNING="1")


_store = None


def store():
    global _store
    if _store is None:
        _configure_memento()
        from memento import MemoryStore
        _store = MemoryStore()
    return _store


def _ingest(text: str, tries: int = 4):
    """Memento calls Gemini to extract entities; the free tier can return 429/503."""
    for i in range(tries):
        try:
            return store().ingest(text)
        except Exception as e:                       # noqa: BLE001 - provider errors vary
            if i == tries - 1:
                print(f"  [memory] ingest failed: {str(e)[:120]}")
                return None
            time.sleep(20 * (i + 1))


# ---------------- seeding ----------------
def _state():
    return json.loads(SEED_STATE.read_text()) if SEED_STATE.exists() else {}


def seed(force=False):
    """Load style guide + mistake profiles into Memento. Re-ingests only what changed."""
    st = _state()
    org = config.org()["name"]
    sg = config.style_guide()
    h = hashlib.md5(sg.encode()).hexdigest()
    if force or st.get("style") != h:
        _ingest(f"{org} security awareness messaging rules: {sg}")
        st["style"] = h
    prof = telemetry.build_profile()
    for dept, items in prof.items():
        top = items[:6]
        if not top:
            continue
        lines = "; ".join(f"{it['behaviour']} ({it['evidence']}, source {it['source']}"
                          f"{', MITRE ' + it['mitre'] if it['mitre'] else ''})" for it in top)
        text = f"As of {date.today().isoformat()}, the {dept} department at {org} has these recurring security mistakes: {lines}."
        hh = hashlib.md5(lines.encode()).hexdigest()
        if force or st.get(f"dept:{dept}") != hh:
            _ingest(text)
            st[f"dept:{dept}"] = hh
            print(f"  [memory] stored mistakes for {dept}")
    SEED_STATE.write_text(json.dumps(st, indent=1))


# ---------------- recall ----------------
def recall(query: str, budget_chars: int = 3000) -> str:
    try:
        txt = store().recall(query).text or ""
    except Exception as e:                           # noqa: BLE001
        return f"(memory unavailable: {str(e)[:80]})"
    return txt[:budget_chars]


def _cos(a, b):
    num = sum(x * y for x, y in zip(a, b))
    return num / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def modules() -> list[dict]:
    if not REGISTRY.exists():
        return []
    by_id = {}
    for l in REGISTRY.read_text(encoding="utf-8").splitlines():
        if l.strip():
            m = json.loads(l)
            by_id[m["id"]] = m          # last entry wins, so a re-approval never duplicates
    return list(by_id.values())


def similar_modules(text: str, k: int = 3, min_sim: float = 0.55) -> list[dict]:
    mods = modules()
    if not mods:
        return []
    q = llm.embed([text[:2000]])[0]
    scored = [(_cos(q, m["embedding"]), m) for m in mods]
    scored.sort(key=lambda x: -x[0])
    return [{**{k2: v for k2, v in m.items() if k2 != "embedding"}, "similarity": round(s, 3)}
            for s, m in scored[:k] if s >= min_sim]


# ---------------- write-back ----------------
def remember_module(draft: dict):
    """Called when a reviewer approves a draft (M7)."""
    c = draft["content"]
    req = draft["request"]
    summary = c.get("summary") or c.get("title", "")
    entry = {"id": draft["id"], "date": date.today().isoformat(), "title": c.get("title", ""),
             "topic": req["topic"], "audience": req["audience"], "format": req["format"],
             "language": req.get("language", "English"), "summary": summary,
             "key_points": c.get("key_points", []), "mitre": c.get("mitre", []),
             "embedding": llm.embed([f"{c.get('title', '')}\n{summary}\n" + " ".join(c.get("key_points", []))])[0]}
    with REGISTRY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _ingest(f"On {entry['date']} {config.org()['name']} approved the awareness {req['format']} "
            f"'{entry['title']}' for {req['audience']} about {req['topic']}. "
            f"Key points: {'; '.join(entry['key_points'][:5])}. MITRE: {', '.join(entry['mitre'])}.")
    return entry


def remember_quiz(department: str, topic: str, score: float, n: int, user_id=None, missed=None):
    telemetry.record_quiz(department, topic, score, n, user_id, missed)
    _ingest(f"On {date.today().isoformat()} the {department} department scored {score:.0%} "
            f"on a {n}-question security quiz about {topic}.")
