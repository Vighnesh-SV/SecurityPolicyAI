"""M1 + M2: collect trusted content into data/processed/documents.jsonl.

python -m spai.ingest            # use cached crawl, refresh feeds
python -m spai.ingest --crawl    # also spend Firecrawl credits on targets not yet cached
python -m spai.ingest --crawl --refresh   # re-crawl everything
"""
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import pandas as pd
import requests
from pypdf import PdfReader

from . import config

UA = {"User-Agent": "Mozilla/5.0 (SecurityPolicyAI research project)"}
FC_DIR = config.RAW / "firecrawl"
SKIP_URL = re.compile(r"sitemap|EMPANEL|CNA\.jsp|PUBADVLIST|\.xml$", re.I)
DOCS = config.PROCESSED / "documents.jsonl"


def _id(*p):
    return hashlib.sha1("|".join(p).encode("utf-8")).hexdigest()[:16]


def _iso(s) -> str:
    """Best-effort date → YYYY-MM-DD, '' if unknown."""
    if not s:
        return ""
    s = str(s)
    for f in (parsedate_to_datetime, lambda x: datetime.fromisoformat(x.replace("Z", "+00:00"))):
        try:
            return f(s).date().isoformat()
        except (TypeError, ValueError, IndexError):
            pass
    try:
        return pd.to_datetime(s, utc=True).date().isoformat()
    except (ValueError, TypeError):
        return ""


def _clean_md(md: str) -> str:
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)                 # images
    md = re.sub(r"\[([^\]]+)\]\((?:https?://[^)]+)\)", r"\1", md)  # keep link text only
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


# ---------- Firecrawl (M1) ----------
def crawl(refresh=False):
    from firecrawl import Firecrawl
    fc = Firecrawl(api_key=config.key("FIRECRAWL_API_KEY"))
    for t in config.sources()["firecrawl_targets"]:
        out = FC_DIR / t["id"]
        if out.exists() and any(out.iterdir()) and not refresh:
            print(f"  cached  {t['id']}")
            continue
        pages = None
        for attempt in range(4):
            try:
                if t["mode"] == "crawl":
                    job = fc.crawl(t["url"], limit=t.get("limit", 10), only_main_content=True,
                                   formats=["markdown"], timeout=300)
                    pages = job.data or []
                else:
                    pages = [fc.scrape(t["url"], formats=["markdown"], only_main_content=True)]
                break
            except Exception as e:                  # one bad site must not stop the run
                if "rate limit" in str(e).lower() and attempt < 3:
                    print(f"  rate limited on {t['id']}, waiting 65s")
                    time.sleep(65)                  # free plan: 3 crawl starts per minute
                    continue
                print(f"  FAILED  {t['id']}: {str(e)[:150]}")
                break
        if not pages:
            print(f"  no pages {t['id']}")
            continue
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for p in pages:
            md = getattr(p, "markdown", "") or ""
            meta = p.metadata.model_dump() if getattr(p, "metadata", None) else {}
            url = meta.get("source_url") or meta.get("url") or t["url"]
            rec = {"url": url, "title": meta.get("title") or t["id"], "markdown": md,
                   "published": meta.get("published_time") or meta.get("modified_time") or "",
                   "fetched": datetime.now(timezone.utc).date().isoformat()}
            (out / f"{_id(url)}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            n += 1
        print(f"  crawled {t['id']}: {n} pages")
    try:
        u = fc.get_credit_usage()
        print(f"  Firecrawl credits left: {u.remaining_credits}/{u.plan_credits}")
    except Exception:
        pass


def firecrawl_docs():
    docs = []
    for f in FC_DIR.glob("*/*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        text = _clean_md(r["markdown"])
        if len(text) < 300 or SKIP_URL.search(r["url"]):   # menus, list pages, admin pages
            continue
        date = _iso(r.get("published"))
        docs.append({"id": _id(r["url"]), "source": f.parent.name, "kind": "guidance",
                     "title": r["title"], "url": r["url"], "date": date or r["fetched"],
                     "date_known": bool(date), "text": text})
    return docs


# ---------- feeds (M2) ----------
def rss_docs():
    docs = []
    for f in config.sources()["rss_feeds"]:
        try:
            feed = feedparser.parse(requests.get(f["url"], headers=UA, timeout=30).content)
        except requests.RequestException as e:
            print(f"  feed failed {f['id']}: {e}")
            continue
        for e in feed.entries:
            summary = re.sub(r"<[^>]+>", " ", e.get("summary", ""))
            summary = re.sub(r"\s+", " ", summary).strip()
            if not e.get("link"):
                continue
            docs.append({"id": _id(e.link), "source": f["id"], "kind": "news",
                         "title": e.get("title", ""), "url": e.link,
                         "date": _iso(e.get("published") or e.get("updated")), "date_known": True,
                         "text": f"{e.get('title', '')}\n\n{summary}"})
    return docs


def refresh_kev():
    p = config.RESOURCES / "feeds" / "cisa_kev.json"
    try:
        r = requests.get("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
                         headers=UA, timeout=60)
        r.raise_for_status()
        p.write_bytes(r.content)
    except requests.RequestException as e:
        print(f"  KEV refresh failed, using cached copy: {e}")
    return json.loads(p.read_text(encoding="utf-8"))


def kev_docs(days):
    d = refresh_kev()
    df = pd.DataFrame(d["vulnerabilities"])
    df["dateAdded"] = pd.to_datetime(df["dateAdded"])
    df = df[df["dateAdded"] >= df["dateAdded"].max() - pd.Timedelta(days=days)]
    docs = []
    for _, v in df.iterrows():
        text = (f"{v.cveID}: {v.vulnerabilityName}\nVendor/product: {v["vendorProject"]} {v["product"]}\n"
                f"{v.shortDescription}\nRequired action: {v.requiredAction}\n"
                f"Known ransomware use: {v.get('knownRansomwareCampaignUse', 'Unknown')}")
        docs.append({"id": _id(v.cveID), "source": "cisa_kev", "kind": "vulnerability",
                     "title": f"{v.cveID} {v["vendorProject"]} {v["product"]}",
                     "url": f"https://nvd.nist.gov/vuln/detail/{v.cveID}",
                     "date": v.dateAdded.date().isoformat(), "date_known": True, "text": text})
    return docs


# ---------- static references ----------
def pdf_docs():
    docs = []
    titles = {"nist_50r1": "NIST SP 800-50 Rev. 1: Building a Cybersecurity and Privacy Learning Program",
              "nist_csf2": "NIST Cybersecurity Framework (CSF) 2.0"}
    urls = {"nist_50r1": "https://doi.org/10.6028/NIST.SP.800-50r1",
            "nist_csf2": "https://doi.org/10.6028/NIST.CSWP.29"}
    for s in config.sources()["static"]:
        if not s["path"].endswith(".pdf"):
            continue
        for i, p in enumerate(PdfReader(config.ROOT / s["path"]).pages, 1):
            text = re.sub(r"[ \t]+", " ", p.extract_text() or "").strip()
            if len(text) < 200:
                continue
            docs.append({"id": _id(s["id"], str(i)), "source": s["id"], "kind": "standard",
                         "title": f"{titles[s['id']]} (p. {i})", "url": f"{urls[s['id']]}#page={i}",
                         "date": "", "date_known": False, "text": text})
    return docs


def mitre_docs():
    """Only the techniques our behaviour map links to employee training."""
    bm = pd.read_csv(config.CONFIG / "behaviour_map.csv")
    wanted = {t.strip() for m in bm["mitre"].dropna() for t in m.split(";")}
    wanted |= {"T1566", "T1566.001", "T1566.002", "T1566.004", "T1621", "T1534", "T1656"}
    tech = pd.read_csv(config.PROCESSED / "mitre_techniques.csv")
    docs = []
    for _, t in tech[tech.technique_id.isin(wanted)].iterrows():
        docs.append({"id": _id("mitre", t.technique_id), "source": "mitre_attack", "kind": "technique",
                     "title": f"MITRE ATT&CK {t.technique_id}: {t['name']}", "url": t.url,
                     "date": "", "date_known": False,
                     "text": f"{t.technique_id} {t['name']} (tactics: {t.tactics})\n{t.description}"})
    return docs


def build(do_crawl=False, refresh=False):
    if do_crawl:
        print("Firecrawl:")
        crawl(refresh)
    days = config.sources()["freshness_days"]
    parts = {"firecrawl": firecrawl_docs(), "rss": rss_docs(), "kev": kev_docs(days),
             "pdf": pdf_docs(), "mitre": mitre_docs()}
    seen, docs = set(), []
    for v in parts.values():
        for d in v:
            if d["id"] not in seen:
                seen.add(d["id"])
                docs.append(d)
    with DOCS.open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print("Documents:", {k: len(v) for k, v in parts.items()}, "→ total", len(docs))
    return docs


def load_docs():
    return [json.loads(l) for l in DOCS.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawl", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    build(a.crawl, a.refresh)
