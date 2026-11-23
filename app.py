"""SecurityPolicy AI: Streamlit app (M8).   Run:  .venv/Scripts/streamlit run app.py"""
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

from spai import config, digest, export, generate, judge, kb, memory, telemetry

st.set_page_config(page_title="SecurityPolicy AI", page_icon="🛡️", layout="wide")
st.title("🛡️ SecurityPolicy AI")
st.caption("Security awareness content that stays current (Firecrawl), consistent (Memento) and targeted "
           "(telemetry), written by Gemini and checked before anyone sees it.")

tabs = st.tabs(["✍️ Generate", "📝 Take a quiz", "📊 Org insights", "📰 Threat digest",
                "📚 Knowledge base", "🗂️ History", "🧪 Evaluation"])


def show_metrics(m):
    cols = st.columns(8)
    labels = [("factuality", "Factuality"), ("citation_cov", "Cited"), ("freshness", "Fresh"),
              ("consistency", "Consistent"), ("relevance", "Relevance"), ("style", "Style"),
              ("clarity", "Clarity"), ("novelty", "Novelty")]
    for col, (k, lab) in zip(cols, labels):
        v = m.get(k)
        col.metric(lab, "n/a" if v is None else f"{v:.0%}")


def show_draft(d):
    c = d["content"]
    st.subheader(c.get("title", ""))
    st.caption(f"{d['request']['format']} · {d['request']['audience']} · {d['request']['language']} · "
               f"model {d['model']}")
    g = d.get("guardrails", {})
    if g.get("untrusted_links"):
        st.error("Links to untrusted domains: " + ", ".join(g["untrusted_links"]))
    if g.get("citations", {}).get("invalid_ids"):
        st.warning(f"Citations to missing sources: {g['citations']['invalid_ids']}")
    if g.get("sim_rewritten"):
        st.info("Simulation links/senders rewritten to example.com: " + ", ".join(g["sim_rewritten"]))

    sim = c.get("phishing_sim")
    if sim:
        st.warning(sim.get("training_marker", "TRAINING SIMULATION"))
        with st.container(border=True):
            st.markdown(f"**From:** {sim['sender']}  \n**Subject:** {sim['subject']}")
            st.text(sim["body"])
        st.markdown("**Red flags:**\n" + "\n".join(f"- {x}" for x in sim.get("red_flags", [])))
        st.divider()
    st.markdown(c.get("body_markdown", ""))
    if c.get("red_flags") and not sim:
        st.markdown("**Red flags**\n" + "\n".join(f"- {x}" for x in c["red_flags"]))
    if c.get("actions"):
        st.markdown("**What to do**\n" + "\n".join(f"- {x}" for x in c["actions"]))
    if c.get("report_how"):
        st.success(f"**How to report:** {c['report_how']}")
    for i, q in enumerate(c.get("quiz") or [], 1):
        with st.expander(f"Q{i}. {q['question']}"):
            for j, o in enumerate(q["options"]):
                st.write(("✅ " if j == q["answer_index"] else "▫️ ") + o)
            st.caption(q["explanation"] + (f"  ·  targets: {q['targets_mistake']}" if q.get("targets_mistake") else ""))
    tags = (c.get("mitre") or []) + (c.get("compliance") or [])
    if tags:
        st.caption("Tags: " + " · ".join(tags))
    if c.get("targets_mistakes"):
        st.caption("Targets mistakes: " + " · ".join(c["targets_mistakes"]))

    with st.expander(f"Sources ({len(d['sources'])})"):
        for i, s in enumerate(d["sources"], 1):
            st.markdown(f"**[S{i}]** [{s['title']}]({s['url']}) · {s['source']} · {s['date'] or 'reference'}")
            st.caption(s["excerpt"][:300] + "…")
    if d.get("mistakes"):
        with st.expander("Recurring mistakes used"):
            st.dataframe(pd.DataFrame(d["mistakes"])[["behaviour", "evidence", "source", "mitre"]],
                         hide_index=True)
    if d.get("past_modules"):
        with st.expander("Similar past modules (avoid repeating)"):
            for p in d["past_modules"]:
                st.write(f"{p['date']} · {p['title']} · similarity {p['similarity']}")


# ---------------- Generate ----------------
with tabs[0]:
    left, right = st.columns([1, 2])
    with left:
        topic = st.text_input("Topic", "QR-code phishing (quishing)")
        audience = st.selectbox("Audience", generate.AUDIENCES)
        fmt = st.selectbox("Format", list(generate.FORMATS))
        language = st.selectbox("Language", generate.LANGUAGES)
        policy_text = ""
        if fmt == "policy_summary":
            up = st.file_uploader("Policy document (PDF or text)", type=["pdf", "txt", "md"])
            if up is not None:
                if up.name.endswith(".pdf"):
                    from pypdf import PdfReader
                    policy_text = "\n".join(p.extract_text() or "" for p in PdfReader(up).pages)
                else:
                    policy_text = up.read().decode("utf-8", "ignore")
        extra = st.text_area("Extra instructions (optional)", "")
        with st.expander("Pipeline switches (ablation)"):
            use_rag = st.checkbox("Retrieve current sources (Firecrawl + feeds)", True)
            use_mem = st.checkbox("Use Memento memory + past modules", True)
            use_tel = st.checkbox("Use telemetry mistakes", True)
        go = st.button("Generate", type="primary", width='stretch')

    if go:
        req = generate.Request(topic=topic, audience=audience, format=fmt, language=language,
                               use_rag=use_rag, use_memory=use_mem, use_telemetry=use_tel,
                               policy_text=policy_text, extra=extra)
        with st.spinner("Retrieving sources, recalling memory, writing…"):
            dr = generate.generate(req, use_cache=False)
            generate.save(dr)
            d = asdict(dr)
        with st.spinner("Judge is checking facts and consistency…"):
            d["review"] = judge.judge(d, use_cache=False)
        st.session_state["draft"] = d

    with right:
        d = st.session_state.get("draft")
        if d:
            show_metrics(d["review"]["metrics"])
            j = d["review"]["judge"]
            bad = [c for c in j.get("claims", []) if c.get("verdict") in ("unsupported", "partial")]
            if bad:
                with st.expander(f"⚠️ {len(bad)} claim(s) the judge could not fully verify"):
                    for c in bad:
                        st.write(f"**{c['verdict']}**: {c['claim']} {c.get('cited')}")
            if j.get("contradictions"):
                st.warning("Contradictions: " + "; ".join(j["contradictions"]))
            if j.get("fixes"):
                with st.expander("Judge's suggested fixes"):
                    for f in j["fixes"]:
                        st.write("- " + f)
            show_draft(d)
            st.divider()
            b1, b2, b3 = st.columns(3)
            if b1.button("✅ Approve & remember", width='stretch'):
                with st.spinner("Saving to memory…"):
                    memory.remember_module(d)
                    p = config.OUTPUTS / "approved"
                    p.mkdir(exist_ok=True)
                    (p / f"{d['id']}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
                st.success("Approved. Future content will build on this and avoid repeating it.")
            b2.download_button("⬇️ Markdown", export.to_markdown(d), f"{d['id']}.md", width='stretch')
            b3.download_button("⬇️ Word", export.to_docx(d), f"{d['id']}.docx", width='stretch')
        else:
            st.info("Pick a topic, audience and format, then press Generate.")

# ---------------- Quiz (E3 feedback loop) ----------------
with tabs[1]:
    approved = sorted((config.OUTPUTS / "approved").glob("*.json")) if (config.OUTPUTS / "approved").exists() else []
    quizzes = [json.loads(p.read_text(encoding="utf-8")) for p in approved]
    quizzes = [q for q in quizzes if q["content"].get("quiz")]
    if not quizzes:
        st.info("Approve a quiz in the Generate tab first.")
    else:
        pick = st.selectbox("Quiz", quizzes, format_func=lambda q: q["content"]["title"])
        dept = st.selectbox("Your department", config.org()["departments"], key="qdept")
        answers = []
        for i, q in enumerate(pick["content"]["quiz"]):
            answers.append(st.radio(q["question"], range(4), format_func=lambda j, q=q: q["options"][j],
                                    index=None, key=f"q{pick['id']}{i}"))
        if st.button("Submit answers"):
            right_n = sum(a == q["answer_index"] for a, q in zip(answers, pick["content"]["quiz"]))
            n = len(answers)
            st.metric("Score", f"{right_n}/{n}")
            for a, q in zip(answers, pick["content"]["quiz"]):
                if a != q["answer_index"]:
                    st.error(f"{q['question']}  →  {q['options'][q['answer_index']]}. {q['explanation']}")
            memory.remember_quiz(dept, pick["request"]["topic"], right_n / n, n)
            st.success("Result saved. Low scores become recurring mistakes in the next profile.")

# ---------------- Org insights (E1) ----------------
with tabs[2]:
    st.caption("Recurring mistakes per department, from APT-Hunter detections on real Windows logs, "
               "NEST-Phish human responses, and quiz results. Department assignment is simulated "
               "(see config/org.yaml).")
    if st.button("Rebuild profile from telemetry"):
        telemetry.build_profile()
    prof = telemetry.profile()
    rows = [{"department": d, **it} for d, items in prof.items() for it in items]
    if rows:
        df = pd.DataFrame(rows)
        st.bar_chart(df.groupby(["department", "source"]).size().unstack(fill_value=0))
        dept = st.selectbox("Department", list(prof))
        st.dataframe(pd.DataFrame(prof[dept])[["behaviour", "rate", "count", "evidence", "source", "mitre", "topic"]],
                     hide_index=True, width='stretch')

# ---------------- Digest (S2) ----------------
with tabs[3]:
    days = st.slider("Look back (days)", 3, 60, 14)
    if st.button("Find new topics"):
        with st.spinner("Reading recent feeds…"):
            st.session_state["digest"] = digest.digest(days)
    dg = st.session_state.get("digest")
    if dg:
        st.caption(f"{dg['n_items']} recent items analysed · model {dg['model']}")
        for t in dg.get("topics", []):
            with st.container(border=True):
                st.markdown(f"**{t['topic']}** · urgency {t['urgency']} · {t['audience']} · {t['format']}")
                st.write(t["why_now"])
                for s in t["sources"][:4]:
                    st.caption(f"[{s['date']}] [{s['title']}]({s['url']})")

# ---------------- KB ----------------
with tabs[4]:
    try:
        s = kb.stats()
        c1, c2 = st.columns(2)
        c1.metric("Chunks indexed", s["chunks"])
        c1.json(s["by_kind"])
        c2.bar_chart(pd.Series(s["by_source"]).sort_values(ascending=False))
    except Exception as e:  # noqa: BLE001
        st.error(f"Knowledge base not ready: {e}")
    q = st.text_input("Search the knowledge base", "MFA fatigue push notifications")
    if q:
        for h in kb.retrieve(q, k=6):
            st.markdown(f"**{h['score']:.3f}** · [{h['title']}]({h['url']}) · {h['source']} · {h['date'] or 'reference'}")
            st.caption(h["text"][:300] + "…")

# ---------------- History ----------------
with tabs[5]:
    mods = memory.modules()
    if mods:
        st.dataframe(pd.DataFrame(mods).drop(columns=["embedding"]), hide_index=True, width='stretch')
    else:
        st.info("No approved modules yet.")

# ---------------- Evaluation ----------------
with tabs[6]:
    res = config.ROOT / "eval" / "results"
    summ = res / "summary.csv"
    if summ.exists():
        df = pd.read_csv(summ, index_col=0)
        st.dataframe(df.style.format("{:.2f}"), width='stretch')
        st.bar_chart(df.T)
        st.caption("A = LLM only · B = + Firecrawl RAG · C = + Memento memory · D = + telemetry (full system)")
    else:
        st.info("Run  python -m eval.run_eval  to produce the ablation results.")
