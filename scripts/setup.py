"""One-command setup for a fresh clone. Safe to re-run; every step skips work already done.

    python -m venv .venv
    .venv\\Scripts\\pip install -r requirements.txt
    copy .env.example .env        (then paste your own GEMINI_API_KEY and FIRECRAWL_API_KEY)
    .venv\\Scripts\\python scripts\\setup.py

Steps: download public resources → prepare MITRE/KEV/NIST tables → build documents from the
committed crawl cache (no Firecrawl credits) → build the local knowledge base → build telemetry
profiles → seed Memento memory (uses ~10 Gemini requests; skip with --no-memory).
"""
import argparse
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DOWNLOADS = {
    "resources/mitre/enterprise-attack.json":
        "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json",
    "resources/standards/NIST.SP.800-50r1.pdf":
        "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-50r1.pdf",
    "resources/standards/NIST.CSWP.29_CSF2.pdf":
        "https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf",
    "resources/feeds/cisa_kev.json":
        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
}


def step(msg):
    print(f"\n=== {msg}", flush=True)


def download():
    for rel, url in DOWNLOADS.items():
        p = ROOT / rel
        if p.exists() and p.stat().st_size > 1000:
            print(f"  have {rel}")
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        print(f"  downloading {rel}")
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=300)
        r.raise_for_status()
        p.write_bytes(r.content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-memory", action="store_true", help="skip Memento seeding (saves Gemini quota)")
    ap.add_argument("--crawl", action="store_true", help="crawl targets missing from the cache (Firecrawl credits)")
    a = ap.parse_args()

    if not (ROOT / ".env").exists():
        sys.exit("Create .env from .env.example and add GEMINI_API_KEY / FIRECRAWL_API_KEY first.")

    step("1/6 public resources")
    download()

    step("2/6 MITRE / KEV / NIST tables")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "prep_offline.py")], check=True, cwd=ROOT)

    from spai import ingest, kb, memory, telemetry
    step("3/6 documents (from committed crawl cache + live feeds)")
    ingest.build(do_crawl=a.crawl)

    step("4/6 knowledge base (local embeddings, ~2-5 min on CPU the first time)")
    kb.index()

    step("5/6 telemetry profiles")
    prof = telemetry.build_profile()
    print("  mistakes per department:", {k: len(v) for k, v in prof.items()})

    if a.no_memory:
        print("\n(skipped Memento seeding)")
    else:
        step("6/6 Memento memory (style guide + mistakes; uses Gemini)")
        memory.seed()

    print("\nDone. Start the API:  .venv\\Scripts\\uvicorn spai.api:app --port 8000   (docs at /docs)")
    print("      or the demo UI: .venv\\Scripts\\streamlit run app.py")


if __name__ == "__main__":
    main()
