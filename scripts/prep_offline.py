"""Key-free data preparation. Produces data/processed/* from resources/ and the RSS feeds.

Run:  .venv/Scripts/python scripts/prep_offline.py
"""
import json
import re
from pathlib import Path

import feedparser
import pandas as pd
import requests
import yaml
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)
CFG = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))


def mitre_table():
    d = json.loads((ROOT / "resources/mitre/enterprise-attack.json").read_text(encoding="utf-8"))
    rows = []
    for o in d["objects"]:
        if o.get("type") != "attack-pattern" or o.get("revoked") or o.get("x_mitre_deprecated"):
            continue
        ext = next((r for r in o.get("external_references", []) if r.get("source_name") == "mitre-attack"), None)
        if not ext:
            continue
        rows.append({
            "technique_id": ext["external_id"],
            "name": o["name"],
            "tactics": ";".join(p["phase_name"] for p in o.get("kill_chain_phases", [])),
            "url": ext.get("url", ""),
            "description": re.sub(r"\s+", " ", o.get("description", ""))[:1500],
        })
    df = pd.DataFrame(rows).sort_values("technique_id")
    df.to_csv(OUT / "mitre_techniques.csv", index=False, encoding="utf-8")
    return len(df)


def kev_table():
    d = json.loads((ROOT / "resources/feeds/cisa_kev.json").read_text(encoding="utf-8"))
    df = pd.DataFrame(d["vulnerabilities"])
    df["dateAdded"] = pd.to_datetime(df["dateAdded"])
    df = df.sort_values("dateAdded", ascending=False)
    df.to_csv(OUT / "kev_all.csv", index=False, encoding="utf-8")
    cutoff = df["dateAdded"].max() - pd.Timedelta(days=CFG["freshness_days"])
    recent = df[df["dateAdded"] >= cutoff]
    recent.to_csv(OUT / "kev_recent.csv", index=False, encoding="utf-8")
    return len(df), len(recent)


def pdf_text():
    n = {}
    for s in CFG["static"]:
        if not s["path"].endswith(".pdf"):
            continue
        pages = PdfReader(ROOT / s["path"]).pages
        text = "\n\n".join(f"[page {i + 1}]\n{p.extract_text() or ''}" for i, p in enumerate(pages))
        (OUT / f"{s['id']}.md").write_text(text, encoding="utf-8")
        n[s["id"]] = len(pages)
    return n


def rss_snapshot():
    items = []
    for f in CFG["rss_feeds"]:
        try:
            raw = requests.get(f["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=30).content
        except requests.RequestException as ex:
            print("  feed failed:", f["id"], ex)
            continue
        feed = feedparser.parse(raw)
        for e in feed.entries:
            items.append({
                "feed": f["id"],
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "published": e.get("published", e.get("updated", "")),
                "summary": re.sub(r"<[^>]+>|\s+", " ", e.get("summary", "")).strip()[:1000],
            })
    df = pd.DataFrame(items).drop_duplicates("link")
    df.to_csv(OUT / "rss_snapshot.csv", index=False, encoding="utf-8")
    return df["feed"].value_counts().to_dict()


if __name__ == "__main__":
    print("MITRE techniques:", mitre_table())
    print("KEV all / recent:", kev_table())
    print("PDF pages:", pdf_text())
    print("RSS items per feed:", rss_snapshot())
