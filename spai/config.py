"""Paths, settings and API keys, loaded once."""
import os
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# Windows consoles default to cp1252; model output contains arrows, quotes, Hindi, etc.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

CONFIG = ROOT / "config"
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
CACHE = DATA / "cache"
CHROMA = DATA / "chroma"
TELEMETRY = DATA / "telemetry"
MEMORY = ROOT / "memory"
OUTPUTS = ROOT / "outputs"
RESOURCES = ROOT / "resources"
for p in (RAW, PROCESSED, CACHE, CHROMA, MEMORY, OUTPUTS):
    p.mkdir(parents=True, exist_ok=True)


def _yaml(name):
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


@lru_cache
def models():
    return _yaml("models.yaml")


@lru_cache
def sources():
    return _yaml("sources.yaml")


@lru_cache
def org():
    return _yaml("org.yaml")


def style_guide() -> str:
    return (CONFIG / "style_guide.md").read_text(encoding="utf-8")


def key(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"{name} missing: add it to {ROOT / '.env'}")
    return v


@lru_cache
def trusted_domains() -> set[str]:
    """Domains content may cite or link to (guardrail E4)."""
    s = sources()
    urls = [t["url"] for t in s["firecrawl_targets"]] + [f["url"] for f in s["rss_feeds"]]
    doms = {urlparse(u).netloc.lower().removeprefix("www.") for u in urls}
    doms |= {"cisa.gov", "nist.gov", "nvlpubs.nist.gov", "attack.mitre.org", "thehackernews.com",
             "cert-in.org.in", "ncsc.gov.uk", "krebsonsecurity.com", "example.com", "example.org"}
    return doms
