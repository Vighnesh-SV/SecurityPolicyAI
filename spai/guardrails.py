"""E4: deterministic checks that don't need an LLM."""
import re
from urllib.parse import urlparse

from . import config

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
SAFE_SIM_DOMAINS = {"example.com", "example.org", "example.net"}
CITE_RE = re.compile(r"\[S(\d+)\]")
ORG_RE = re.compile(r"\[ORG\]")


def _dom(u):
    return urlparse(u).netloc.lower().removeprefix("www.")


def _trusted(d):
    return any(d == t or d.endswith("." + t) for t in config.trusted_domains())


def check_links(text: str) -> list[str]:
    """Links in staff-facing content must point to trusted sources."""
    return [u for u in URL_RE.findall(text) if not _trusted(_dom(u))]


def defang_sim(sim: dict) -> tuple[dict, list[str]]:
    """Phishing simulations may only use reserved example domains. Rewrite anything else."""
    fixed = []

    def fix_url(m):
        u = m.group(0)
        d = _dom(u)
        if d in SAFE_SIM_DOMAINS or any(d.endswith("." + s) for s in SAFE_SIM_DOMAINS):
            return u
        fixed.append(u)
        return "https://training-sim.example.com/" + re.sub(r"[^a-z0-9]+", "-", d)[:30]

    def fix_addr(s):
        return re.sub(r"@([A-Za-z0-9.-]+)",
                      lambda m: m.group(0) if m.group(1).lower().endswith(tuple(SAFE_SIM_DOMAINS))
                      else "@" + m.group(1).split(".")[0] + ".example.com", s)

    out = dict(sim)
    for k in ("body", "subject"):
        if k in out and isinstance(out[k], str):
            out[k] = URL_RE.sub(fix_url, out[k])
    if isinstance(out.get("sender"), str):
        before = out["sender"]
        out["sender"] = fix_addr(before)
        if out["sender"] != before:
            fixed.append(before)
    out["training_marker"] = "SECURITY AWARENESS TRAINING SIMULATION - NOT A REAL EMAIL"
    return out, fixed


def citation_stats(text: str, n_sources: int) -> dict:
    cited = {int(x) for x in CITE_RE.findall(text)}
    bad = sorted(c for c in cited if c < 1 or c > n_sources)
    return {"cited_ids": sorted(cited - set(bad)), "invalid_ids": bad,
            "n_citations": len(CITE_RE.findall(text)), "n_org": len(ORG_RE.findall(text))}
