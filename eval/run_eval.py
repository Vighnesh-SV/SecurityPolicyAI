"""E5: ablation study.

A = LLM only            (no sources, no memory, no telemetry)
B = A + Firecrawl RAG   (current trusted sources)
C = B + Memento memory  (style + past modules + knowledge graph)
D = C + telemetry       (department mistakes) = full system

Same topics for every setup; every draft is scored by the judge.
python -m eval.run_eval              # all topics in eval/topics.csv
python -m eval.run_eval --n 5        # first 5 topics (quick run, saves free-tier quota)
Results are cached, so a run that stops on quota can simply be restarted later.
"""
import argparse
import json
import time
from dataclasses import asdict

import pandas as pd

from spai import config, generate, judge

SETUPS = {
    "A_llm_only":  dict(use_rag=False, use_memory=False, use_telemetry=False),
    "B_+rag":      dict(use_rag=True,  use_memory=False, use_telemetry=False),
    "C_+memory":   dict(use_rag=True,  use_memory=True,  use_telemetry=False),
    "D_full":      dict(use_rag=True,  use_memory=True,  use_telemetry=True),
}
METRICS = ["factuality", "citation_cov", "freshness", "consistency", "relevance", "style", "clarity"]
OUT = config.ROOT / "eval" / "results"
WAIT_SECONDS = 900        # free tier: daily quotas reset once a day, 503 "busy" spells pass in minutes
WAIT_ROUNDS = 20          # up to ~5 hours of waiting before giving up


def run(n=None):
    OUT.mkdir(parents=True, exist_ok=True)
    topics = pd.read_csv(config.ROOT / "eval" / "topics.csv")
    if n:
        topics = topics.head(n)
    rows_path = OUT / "rows.jsonl"
    done = set()
    if rows_path.exists():
        done = {(r["topic_id"], r["setup"]) for r in map(json.loads, rows_path.read_text(encoding="utf-8").splitlines())}
    for _, t in topics.iterrows():
        aud = t.audience if t.audience in generate.AUDIENCES else "All staff"
        for name, flags in SETUPS.items():
            if (int(t.id), name) in done:
                continue
            req = generate.Request(topic=t.topic, audience=aud, format=t.format, **flags)
            for attempt in range(WAIT_ROUNDS + 1):
                try:
                    d = asdict(generate.generate(req))
                    r = judge.judge(d)
                    break
                except Exception as e:                # noqa: BLE001 - busy / quota
                    if attempt == WAIT_ROUNDS:
                        print(f"stopped at topic {t.id} {name}: {str(e)[:160]}")
                        return summarise()
                    print(f"waiting {WAIT_SECONDS // 60} min (models busy or out of quota): {str(e)[:80]}",
                          flush=True)
                    time.sleep(WAIT_SECONDS)
            row = {"topic_id": int(t.id), "topic": t.topic, "setup": name, "model": d["model"],
                   **r["metrics"], "n_sources": len(d["sources"])}
            with rows_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            (OUT / "drafts").mkdir(exist_ok=True)
            (OUT / "drafts" / f"{t.id}_{name}.json").write_text(
                json.dumps({**d, "review": r}, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"topic {t.id:>2} {name:<11} " + " ".join(
                f"{k[:5]}={row[k]:.2f}" if row[k] is not None else f"{k[:5]}=n/a" for k in METRICS), flush=True)
    return summarise()


def summarise():
    rows_path = OUT / "rows.jsonl"
    if not rows_path.exists():
        return None
    df = pd.DataFrame(map(json.loads, rows_path.read_text(encoding="utf-8").splitlines()))
    s = df.groupby("setup")[METRICS].mean().reindex(list(SETUPS)).dropna(how="all")
    s.to_csv(OUT / "summary.csv")
    print("\n", s.round(3).to_string(), f"\n\n({df.topic_id.nunique()} topics)")
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int)
    run(ap.parse_args().n)
