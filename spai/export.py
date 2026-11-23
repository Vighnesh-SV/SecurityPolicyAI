"""M8: export a draft as Markdown or Word."""
import io
import re

from docx import Document
from docx.shared import Pt


def to_markdown(d: dict) -> str:
    c = d["content"]
    r = d["request"]
    out = [f"# {c.get('title', '')}", f"*{r['format']} · {r['audience']} · {r['language']}*", "",
           c.get("body_markdown", "")]
    if c.get("red_flags"):
        out += ["", "## Red flags"] + [f"- {x}" for x in c["red_flags"]]
    if c.get("actions"):
        out += ["", "## What to do"] + [f"- {x}" for x in c["actions"]]
    if c.get("report_how"):
        out += ["", f"**How to report:** {c['report_how']}"]
    for i, q in enumerate(c.get("quiz") or [], 1):
        out += ["", f"**Q{i}. {q['question']}**"]
        out += [f"{'ABCD'[j]}. {o}" for j, o in enumerate(q["options"])]
        out += [f"*Answer: {'ABCD'[q['answer_index']]}. {q['explanation']}*"]
    sim = c.get("phishing_sim")
    if sim:
        out += ["", f"## Training email ({sim.get('training_marker', 'SIMULATION')})",
                f"**From:** {sim['sender']}  ", f"**Subject:** {sim['subject']}", "", sim["body"],
                "", "### Red flags in this email"] + [f"- {x}" for x in sim.get("red_flags", [])]
    if d["sources"]:
        out += ["", "## Sources"]
        out += [f"[S{i}] {s['title']} ({s['date'] or 'reference'}) {s['url']}"
                for i, s in enumerate(d["sources"], 1)]
    tags = (c.get("mitre") or []) + (c.get("compliance") or [])
    if tags:
        out += ["", "*Tags: " + ", ".join(tags) + "*"]
    return "\n".join(out)


def to_docx(d: dict) -> bytes:
    doc = Document()
    doc.styles["Normal"].font.size = Pt(11)
    for line in to_markdown(d).splitlines():
        if line.startswith("# "):
            doc.add_heading(line[2:], 0)
        elif line.startswith("## "):
            doc.add_heading(line[3:], 1)
        elif line.startswith("### "):
            doc.add_heading(line[4:], 2)
        elif line.startswith("- "):
            doc.add_paragraph(re.sub(r"\*\*", "", line[2:]), style="List Bullet")
        elif line.strip():
            doc.add_paragraph(re.sub(r"\*\*|\*", "", line))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
