// SecurityPolicy AI admin UI. Plain JS, no build step. Talks to the FastAPI backend on the same origin.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => (v == null ? "–" : Math.round(v * 100) + "%");
let META = null;
const FMT_ICON = { newsletter: "news", tip: "tip", quiz: "quiz", poster: "poster", phishing_sim: "hook", policy_summary: "doc" };
const FMT_NAME = { newsletter: "Newsletter", tip: "Quick tip", quiz: "Quiz", poster: "Poster", phishing_sim: "Phishing sim", policy_summary: "Policy summary" };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail; } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.append(t); setTimeout(() => t.remove(), 4500);
}

async function busy(btn, label, fn) {
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>${label}`;
  try { return await fn(); } catch (e) { toast(e.message); } finally { btn.disabled = false; btn.innerHTML = old; }
}

const opts = (sel, items, labels) => { sel.innerHTML = items.map((v) => `<option value="${esc(v)}">${esc(labels ? labels[v] : v)}</option>`).join(""); };
const empty = (ic, title, text) => `<div class="empty">${icon(ic)}<b>${esc(title)}</b>${esc(text)}</div>`;
const ago = (iso) => {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso)) / 1000;
  return s < 3600 ? `${Math.max(1, Math.round(s / 60))} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
};

// ---------- tiny markdown renderer (headings, lists, bold, italics, links, citations) ----------
function md(src, nSources = 0) {
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|\W)\*(.+?)\*(?=\W|$)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\[S(\d+)\]/g, (m, n) => (+n <= nSources ? `<a class="cite" data-src="${n}" href="#" title="Source ${n}">${n}</a>` : m))
    .replace(/\[ORG\]/g, '<span class="org" title="Internal organisation data">org</span>');
  let out = "", list = null;
  const close = () => { if (list) { out += `</${list}>`; list = null; } };
  for (const line of String(src || "").split("\n")) {
    const h = line.match(/^(#{1,4})\s+(.*)/), ul = line.match(/^\s*[-*]\s+(.*)/), ol = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (h) { close(); const l = Math.min(h[1].length + 1, 4); out += `<h${l}>${inline(h[2])}</h${l}>`; }
    else if (ul || ol) { const t = ul ? "ul" : "ol"; if (list !== t) { close(); out += `<${t}>`; list = t; } out += `<li>${inline((ul || ol)[1])}</li>`; }
    else if (!line.trim()) close();
    else { close(); out += `<p>${inline(line)}</p>`; }
  }
  close();
  return out;
}

// ---------- draft view (shared by Create and Library) ----------
function quality(metrics) {
  if (!metrics) return { cls: "", label: "Not reviewed", score: null };
  const vals = ["factuality", "citation_cov", "relevance"].map((k) => metrics[k]).filter((v) => typeof v === "number");
  const score = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  return { cls: score >= 0.8 ? "good" : score >= 0.6 ? "warn" : "bad", label: `Quality ${pct(score)}`, score };
}

const METRIC_NAMES = { factuality: "Facts supported", citation_cov: "Claims cited", relevance: "On target", style: "Style", clarity: "Clarity",
                       consistency: "Consistent", freshness: "Fresh sources", novelty: "Not repetitive" };

function draftView(d, approved) {
  const c = d.content, src = d.sources || [], q = quality(d.review?.metrics);
  const claims = (d.review?.judge?.claims || []).filter((x) => x.verdict !== "supported");
  const bad = d.guardrails?.untrusted_links || [];
  const warns = [...bad.map((u) => `Untrusted link: ${u}`), ...claims.map((x) => `Check claim: “${x.claim}”`)];

  let body = md(c.body_markdown, src.length);
  if (c.phishing_sim) {
    const s = c.phishing_sim;
    body += `<h3>Training email</h3><div class="mail"><div class="mail-head"><div><b>From</b> ${esc(s.sender)}</div>
      <div><b>Subject</b> ${esc(s.subject)}</div></div><div class="mail-body">${esc(s.body).replace(/\n/g, "<br>")}</div></div>`;
  }
  if (c.quiz?.length) {
    body += "<h3>Quiz</h3><ol>" + c.quiz.map((x) => `<li style="margin-bottom:8px">${esc(x.question)}<ul>${x.options.map((o, i) =>
      `<li>${i === x.answer_index ? `<b>${esc(o)}</b> <span class="pill good">answer</span>` : esc(o)}</li>`).join("")}</ul></li>`).join("") + "</ol>";
  }
  if (c.red_flags?.length && !c.phishing_sim && !/red flag/i.test(c.body_markdown || "")) body += `<h3>Red flags</h3><ul>${c.red_flags.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`;
  if (c.report_how && !/how to report/i.test(c.body_markdown || "")) body += `<h3>How to report</h3><p>${esc(c.report_how)}</p>`;

  const sources = src.map((s, i) => `<li id="src-${d.id}-${i + 1}"><span class="pill acc">${i + 1}</span><div class="grow">
      <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>
      <div class="small muted">${esc(s.source)}${s.date ? " · " + esc(s.date) : ""}${s.age_days != null ? ` · ${s.age_days} days old` : ""}</div></div></li>`).join("");

  const m = d.review?.metrics || {};
  const scores = Object.entries(METRIC_NAMES).filter(([k]) => typeof m[k] === "number").map(([k, n]) => {
    const v = m[k], cls = v >= 0.8 ? "good" : v >= 0.6 ? "warn" : "bad";
    return `<span>${n}</span><div class="bar ${cls}"><i style="width:${v * 100}%"></i></div><span>${pct(v)}</span>`;
  }).join("");
  const review = `${warns.length ? `<h3 style="margin-top:0">To check before approving</h3><ul>${warns.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    ${scores ? `<h3>Reviewer scores</h3><div class="scorebar">${scores}</div>` : "<p class='muted'>Not reviewed yet.</p>"}
    ${(d.mistakes || []).length ? `<h3>Targets these mistakes</h3><ul>${d.mistakes.map((x) => `<li>${esc(x.behaviour)} <span class="small muted">${esc(x.evidence)}</span></li>`).join("")}</ul>` : ""}
    ${(c.compliance || []).length || (c.mitre || []).length ? `<h3>Mapped to</h3><div class="chips">${[...(c.mitre || []), ...(c.compliance || [])].map((x) => `<span class="pill">${esc(x)}</span>`).join("")}</div>` : ""}`;

  return `<article class="card" data-id="${d.id}">
    <div class="row" style="justify-content:space-between">
      <div class="row" style="gap:6px"><span class="pill acc">${icon(FMT_ICON[d.request.format] || "doc")}${esc(FMT_NAME[d.request.format] || d.request.format)}</span>
        <span class="pill">${esc(d.request.audience)}</span><span class="pill">${esc(d.request.language)}</span></div>
      <span class="pill ${q.cls}">${q.label}</span>
    </div>
    <h2 class="doc-title">${esc(c.title)}</h2>
    ${c.summary ? `<p class="muted" style="margin:0">${esc(c.summary)}</p>` : ""}
    ${warns.length ? `<div class="notice">${icon("alert")}<span>${warns.length} item(s) to check before approving. See the Review tab.</span></div>` : ""}
    <div class="tabs" data-tabs>
      <button class="on" data-t="content">Content</button><button data-t="sources">Sources (${src.length})</button><button data-t="review">Review</button></div>
    <div data-pane="content" class="doc">${body}</div>
    <div data-pane="sources" class="hidden"><ul class="list">${sources || "<li class='muted'>No sources</li>"}</ul></div>
    <div data-pane="review" class="hidden">${review}</div>
    <div class="toolbar">
      ${approved ? `<span class="pill good">${icon("check")}Approved</span>`
                 : `<button class="btn" data-act="approve" ${bad.length ? "disabled title='Remove untrusted links first'" : ""}>${icon("check")}Approve</button>`}
      <a class="btn ghost" href="/drafts/${d.id}/export?fmt=docx">${icon("download")}Word</a>
      <a class="btn ghost" href="/drafts/${d.id}/export?fmt=md">${icon("download")}Markdown</a>
      <span class="small muted" style="margin-left:auto">${d.created ? new Date(d.created).toLocaleString() : ""}</span>
    </div>
  </article>`;
}

function bindDraft(container, after) {
  container.addEventListener("click", async (e) => {
    const tab = e.target.closest("[data-tabs] button");
    if (tab) {
      const card = tab.closest("article");
      $$("[data-tabs] button", card).forEach((b) => b.classList.toggle("on", b === tab));
      $$("[data-pane]", card).forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== tab.dataset.t));
      return;
    }
    const cite = e.target.closest("[data-src]");
    if (cite) {
      e.preventDefault();
      const card = cite.closest("article");
      $("[data-tabs] button[data-t=sources]", card).click();
      const li = $(`#src-${card.dataset.id}-${cite.dataset.src}`);
      li?.classList.add("on"); li?.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(() => li?.classList.remove("on"), 1600);
      return;
    }
    const b = e.target.closest("[data-act=approve]");
    if (!b) return;
    const id = b.closest("[data-id]").dataset.id;
    await busy(b, "Approving", async () => {
      await api(`/drafts/${id}/approve`, { method: "POST" });
      b.outerHTML = `<span class="pill good">${icon("check")}Approved</span>`;
      toast("Approved. Saved to memory, so future content builds on it.");
      after?.();
    });
  });
}

// ---------- overview ----------
async function loadOverview() {
  const [health, drafts, camps, prof] = await Promise.all([api("/health"), api("/drafts?limit=200"), api("/campaigns"), api("/profile")]);
  const reviewed = drafts.map((d) => quality(d.metrics).score).filter((v) => v != null);
  const avgQ = reviewed.length ? reviewed.reduce((a, b) => a + b, 0) / reviewed.length : null;
  const sent = camps.reduce((a, c) => a + c.inbox_links.length, 0), clicked = camps.reduce((a, c) => a + c.funnel.clicked, 0);
  const reported = camps.reduce((a, c) => a + c.funnel.reported, 0);
  const kpi = (ic, lbl, val, hint) => `<div class="kpi"><div class="lbl"><span class="ico-bg">${icon(ic)}</span>${lbl}</div><div class="val">${val}</div><div class="hint">${hint}</div></div>`;
  $("#kpis").innerHTML = kpi("book", "Approved modules", health.approved_modules, `${drafts.length} drafts in total`)
    + kpi("check", "Average quality", pct(avgQ), `${reviewed.length} reviewed drafts`)
    + kpi("hook", "Simulation click rate", sent ? pct(clicked / sent) : "–", sent ? `${reported} of ${sent} reported it` : "no campaigns yet")
    + kpi("db", "Knowledge base", health.kb_chunks.toLocaleString(), "passages from trusted sources");

  const risks = Object.values(prof).flat().filter((m) => m.rate != null).sort((a, b) => b.rate - a.rate).slice(0, 5);
  $("#ov-risks").innerHTML = risks.map((m) => `<li><span class="ico-bg" style="background:var(--bad-soft);color:var(--bad)">${icon("target")}</span>
      <div class="grow"><div class="t">${esc(m.behaviour)}</div><div class="small muted">${esc(m.department)} · ${esc(m.evidence)}</div></div>
      <span class="pill ${m.rate >= 0.4 ? "bad" : "warn"}">${pct(m.rate)}</span>
      <button class="btn ghost sm" data-teach="${esc(m.topic)}" data-dept="${esc(m.department)}">Teach</button></li>`).join("")
    || `<li>${empty("target", "No recurring mistakes", "Run a simulation or quiz to collect data.")}</li>`;
  $("#ov-recent").innerHTML = drafts.slice(0, 5).map(draftRow).join("") || `<li>${empty("spark", "Nothing yet", "Create your first piece of content.")}</li>`;

  api("/modules/staleness").then((s) => {
    const st = s.modules.filter((m) => m.status !== "current");
    $("#ov-stale-card").classList.toggle("hidden", !st.length);
    $("#ov-stale").innerHTML = st.slice(0, 3).map((m) => `<li><div class="grow"><div class="t">${esc(m.title)}</div>
      <div class="small muted">${esc(m.reasons.join(" · "))}</div></div><button class="btn ghost sm" data-refresh="${esc(m.topic)}">Update</button></li>`).join("");
  }).catch(() => {});
}

function draftRow(r) {
  const q = quality(r.metrics);
  return `<li class="click" data-open="${r.id}"><span class="ico-bg">${icon(FMT_ICON[r.format] || "doc")}</span>
    <div class="grow"><div class="t">${esc(r.title || r.topic)}</div><div class="small muted">${esc(FMT_NAME[r.format] || r.format)} · ${esc(r.audience)}${r.created ? " · " + ago(r.created) : ""}</div></div>
    ${r.approved ? '<span class="pill good">Approved</span>' : q.score != null ? `<span class="pill ${q.cls}">${pct(q.score)}</span>` : '<span class="pill">Draft</span>'}</li>`;
}

// ---------- create ----------
let FORMAT = "newsletter";
function pickFormat(f) {
  FORMAT = f;
  $$(".fmt").forEach((b) => b.classList.toggle("on", b.dataset.f === f));
  $("#fmt-desc").textContent = (META.formats[f] || "").split(". ")[0].replace(/\.+$/, "") + ".";
  $("#policy-box").classList.toggle("hidden", f !== "policy_summary");
  if (f === "policy_summary") $("#policy-box").closest("details").open = true;
}

const STEPS = ["Searching trusted sources", "Checking your team's recurring mistakes", "Recalling earlier modules", "Writing the draft", "Fact-checking every claim"];
function progressCard() {
  return `<div class="card"><h2>Working on it…</h2><p class="small muted" style="margin:0">This takes 20–90 seconds on the free AI tier.</p>
    <ul class="steps">${STEPS.map((s, i) => `<li data-step="${i}"><span class="b"></span>${s}</li>`).join("")}</ul>
    <div class="skeleton" style="width:70%;margin-top:18px"></div><div class="skeleton"></div><div class="skeleton" style="width:85%"></div></div>`;
}

function initCreate() {
  $("#formats").innerHTML = Object.keys(META.formats).map((f) => `<button type="button" class="fmt" data-f="${f}">${icon(FMT_ICON[f] || "doc")}${FMT_NAME[f] || f}</button>`).join("");
  $("#formats").onclick = (e) => { const b = e.target.closest(".fmt"); if (b) pickFormat(b.dataset.f); };
  pickFormat("newsletter");
  opts($("#audience"), META.audiences);
  opts($("#language"), META.languages);
  bindDraft($("#create-out"));
  $("#gen-form").onsubmit = (e) => {
    e.preventDefault();
    const out = $("#create-out");
    out.innerHTML = progressCard();
    let i = 0;
    const tick = () => { $$("[data-step]", out).forEach((li) => { const n = +li.dataset.step; li.className = n < i ? "done" : n === i ? "on" : ""; }); };
    tick();
    const timer = setInterval(() => { if (i < STEPS.length - 1) { i++; tick(); } }, 7000);
    busy($("#gen-btn"), "Generating", async () => {
      try {
        const d = await api("/generate", { method: "POST", body: {
          topic: $("#topic").value, audience: $("#audience").value, format: FORMAT,
          language: $("#language").value, extra: $("#extra").value, policy_text: $("#policy").value } });
        out.innerHTML = draftView(d, false);
      } catch (err) {
        out.innerHTML = `<div class="card">${empty("alert", "Couldn't generate right now", err.message)}</div>`;
        throw err;
      } finally { clearInterval(timer); }
    });
  };
}

function prefill(topic, dept, extra = "") {
  $("#topic").value = topic;
  if (dept) $("#audience").value = dept;
  $("#extra").value = extra;
  show("create"); $("#topic").focus();
}

// ---------- library ----------
let LIB = [], LIB_FILTER = "all";
function renderLibrary() {
  const q = $("#lib-q").value.toLowerCase();
  const rows = LIB.filter((r) => (LIB_FILTER === "all" || (LIB_FILTER === "approved") === r.approved)
    && (!q || `${r.title} ${r.topic} ${r.audience} ${r.format}`.toLowerCase().includes(q)));
  $("#drafts").innerHTML = rows.map(draftRow).join("") || `<li>${empty("book", "Nothing here", "Try another filter.")}</li>`;
}
async function loadLibrary() {
  LIB = await api("/drafts?limit=200");
  renderLibrary();
  const s = await api("/modules/staleness").catch(() => ({ modules: [] }));
  const stale = s.modules.filter((m) => m.status !== "current");
  $("#stale-card").classList.toggle("hidden", !stale.length);
  $("#stale").innerHTML = stale.map((m) => `<li><div class="grow"><div class="t">${esc(m.title)}</div>
    <div class="small muted">${esc(m.reasons.join(" · "))}${m.newer_sources[0] ? ` · e.g. <a href="${esc(m.newer_sources[0].url)}" target="_blank" rel="noopener">${esc(m.newer_sources[0].title)}</a>` : ""}</div></div>
    <button class="btn ghost sm" data-refresh="${esc(m.topic)}">Update</button></li>`).join("");
}
async function openDraft(id) {
  show("library", false);
  $("#library-out").innerHTML = `<div class="card"><div class="skeleton" style="width:40%"></div><div class="skeleton"></div><div class="skeleton" style="width:80%"></div></div>`;
  const d = await api(`/drafts/${id}`);
  if (!LIB.length) LIB = await api("/drafts?limit=200");
  $$("#drafts li").forEach((li) => li.classList.toggle("on", li.dataset.open === id));
  $("#library-out").innerHTML = draftView(d, LIB.find((x) => x.id === id)?.approved);
}
function initLibrary() {
  bindDraft($("#library-out"), loadLibrary);
  $("#lib-q").oninput = renderLibrary;
  $("#lib-filter").onclick = (e) => {
    const b = e.target.closest("[data-f]"); if (!b) return;
    LIB_FILTER = b.dataset.f; $$("#lib-filter .chip").forEach((c) => c.classList.toggle("on", c === b)); renderLibrary();
  };
}

// ---------- simulate ----------
async function loadSimulate() {
  const [kits, camps] = await Promise.all([api("/simulations"), api("/campaigns")]);
  opts($("#kit"), kits.map((k) => k.id), Object.fromEntries(kits.map((k) => [k.id, `${k.title} (${k.audience})`])));
  $("#kit-note").textContent = kits.length ? "" : "No approved training emails yet. Create a “Phishing sim” and approve it first.";
  $("#camp-form .btn").disabled = !kits.length;
  $("#campaigns").innerHTML = camps.map((c) => {
    const n = c.inbox_links.length, f = c.funnel;
    const stat = (v, l) => `<div class="stat"><div class="val">${v}</div><div class="lbl">${l}</div></div>`;
    const rows = [["opened", "Opened", ""], ["clicked", "Clicked link", "bad"], ["submitted_data", "Entered data", "bad"], ["reported", "Reported", "good"]]
      .map(([k, l, cls]) => `<span>${l}</span><div class="bar ${cls}"><i style="width:${(100 * f[k]) / n}%"></i></div><span class="small muted">${f[k]}/${n}</span>`).join("");
    return `<div class="card"><div class="card-head"><div><h2 style="margin:0">${esc(c.title)}</h2>
        <div class="small muted">${esc(c.department)} · ${n} recipients · launched ${ago(c.created)}</div></div>
        <span class="pill ${f.clicked / n >= 0.25 ? "bad" : "good"}">${f.clicked / n >= 0.25 ? "Needs training" : "Looking good"}</span></div>
      <div class="stats3">${stat(pct(f.opened / n), "opened")}${stat(pct(f.clicked / n), "clicked")}${stat(pct(f.reported / n), "reported")}</div>
      <div class="funnel">${rows}</div>
      <details style="margin-top:14px"><summary>Recipient inbox links: open one to act as that employee</summary>
        <div class="chips" style="margin-top:10px">${c.inbox_links.map((l) => `<a class="chip" href="${esc(l.url)}" target="_blank">${esc(l.user)}</a>`).join("")}</div>
      </details></div>`;
  }).join("") || `<div class="card">${empty("mail", "No campaigns yet", "Launch one above to see who opens, clicks and reports it.")}</div>`;
}
function initSimulate() {
  opts($("#camp-dept"), META.departments);
  $("#camp-form").onsubmit = (e) => {
    e.preventDefault();
    busy($("#camp-form .btn"), "Launching", async () => {
      await api("/campaigns", { method: "POST", body: { draft_id: $("#kit").value, department: $("#camp-dept").value, recipients: +$("#camp-n").value } });
      toast("Campaign launched"); await loadSimulate();
    });
  };
}

// ---------- insights ----------
let DEPT = null;
async function loadMistakes() {
  const rows = await api(`/profile/${encodeURIComponent(DEPT)}?n=6`);
  $("#mistakes").innerHTML = rows.map((m) => `<li><div class="grow"><div>${esc(m.behaviour)}</div>
      <div class="small muted">${esc(m.evidence)} · ${esc(m.source)}</div>
      ${m.rate != null ? `<div class="bar ${m.rate >= 0.4 ? "bad" : "warn"}" style="margin-top:6px;max-width:240px"><i style="width:${m.rate * 100}%"></i></div>` : ""}</div>
      ${m.rate != null ? `<span class="pill ${m.rate >= 0.4 ? "bad" : "warn"}">${pct(m.rate)}</span>` : ""}
      <button class="btn ghost sm" data-teach="${esc(m.topic)}" data-dept="${esc(DEPT)}">Teach</button></li>`).join("")
    || `<li>${empty("check", "No recurring mistakes", "Nothing above the threshold for this team.")}</li>`;
}

function lineChart(weeks, series) {
  const W = 560, H = 190, P = 34, n = weeks.length;
  if (!n) return empty("chart", "No trend yet", "Appears after simulations or quizzes for this team.");
  const x = (i) => (n === 1 ? W / 2 : P + (i * (W - 2 * P)) / (n - 1)), y = (v) => H - P - v * (H - 2 * P);
  let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" role="img" aria-label="Weekly trend">`;
  for (const g of [0, 0.5, 1]) svg += `<line x1="${P}" x2="${W - 10}" y1="${y(g)}" y2="${y(g)}" stroke="var(--line)"/>
    <text x="0" y="${y(g) + 4}" font-size="11" fill="var(--muted)">${g * 100}%</text>`;
  weeks.forEach((w, i) => { svg += `<text x="${x(i)}" y="${H - 8}" font-size="11" fill="var(--muted)" text-anchor="middle">${esc(w.slice(5))}</text>`; });
  for (const s of series) {
    const pts = s.values.map((v, i) => (v == null ? null : [x(i), y(v)])).filter(Boolean);
    if (pts.length > 1) svg += `<polyline fill="none" stroke="${s.color}" stroke-width="2.5" stroke-linejoin="round" points="${pts.map((p) => p.join(",")).join(" ")}"/>`;
    pts.forEach(([a, b], k) => { svg += `<circle cx="${a}" cy="${b}" r="4" fill="var(--surface)" stroke="${s.color}" stroke-width="2.5"><title>${s.label}: ${pct(s.values.filter((v) => v != null)[k])}</title></circle>`; });
  }
  return svg + "</svg>" + `<div class="row small" style="margin-top:4px">${series.map((s) =>
    `<span class="muted"><span style="display:inline-block;width:10px;height:3px;border-radius:2px;background:${s.color};margin-right:6px;vertical-align:3px"></span>${s.label}</span>`).join("")}</div>`;
}

async function loadTrend() {
  const t = await api(`/trends/${encodeURIComponent(DEPT)}`);
  const ch = t.change, notes = [];
  if (ch.click_rate) notes.push(`click rate <b>${pct(ch.click_rate.before)} → ${pct(ch.click_rate.after)}</b>`);
  if (ch.quiz_avg) notes.push(`quiz score <b>${pct(ch.quiz_avg.before)} → ${pct(ch.quiz_avg.after)}</b>`);
  $("#trend-out").innerHTML = (notes.length ? `<p class="small" style="margin-top:0">Since the first week: ${notes.join(" · ")}</p>` : "") +
    lineChart(t.weeks.map((w) => w.week), [
      { label: "Clicked simulation", color: "var(--bad)", values: t.weeks.map((w) => w.click_rate) },
      { label: "Quiz score", color: "var(--accent)", values: t.weeks.map((w) => w.quiz_avg) }]);
}

async function loadWeek() {
  const r = await api("/reports/weekly");
  const rows = Object.entries(r.departments);
  $("#t-week").innerHTML = `<p class="small muted" style="margin-top:0">${r.period[0]} to ${r.period[1]} · team totals only; individuals are never ranked.</p>
    <div style="overflow-x:auto"><table><tr><th>Department</th><th>People</th><th>Avoided</th><th>Reported</th><th>Clicked</th><th>Quiz avg</th></tr>
    ${rows.map(([d, v]) => `<tr><td><b>${esc(d)}</b></td><td>${v.employees}</td><td>${v.avoided}</td><td>${v.reported}</td>
      <td>${v.clicked ? `<span class="pill bad">${v.clicked}</span>` : 0}</td><td>${pct(v.quiz_avg)}</td></tr>`).join("")}</table></div>`;
}

async function loadEval() {
  const e = await api("/eval/summary");
  const s = e.summary || {}, setups = Object.keys(s);
  if (!setups.length) { $("#t-eval").innerHTML = empty("chart", "No results yet", "Run python -m eval.run_eval"); return; }
  const cols = Object.keys(s[setups[0]]);
  $("#t-eval").innerHTML = `<p class="small muted" style="margin-top:0">${e.n_topics} topic(s). A = AI only · B = + sources · C = + memory · D = full system.</p>
    <div style="overflow-x:auto"><table><tr><th>Setup</th>${cols.map((c) => `<th>${esc(METRIC_NAMES[c] || c)}</th>`).join("")}</tr>
    ${setups.map((k) => `<tr><td><b>${esc(k)}</b></td>${cols.map((c) => `<td>${s[k][c] == null ? "–" : pct(s[k][c])}</td>`).join("")}</tr>`).join("")}</table></div>`;
}

function initInsights() {
  DEPT = META.departments[0];
  $("#ins-dept").innerHTML = META.departments.map((d) => `<button class="chip${d === DEPT ? " on" : ""}" data-d="${esc(d)}">${esc(d)}</button>`).join("");
  $("#ins-dept").onclick = (e) => {
    const b = e.target.closest("[data-d]"); if (!b) return;
    DEPT = b.dataset.d; $$("#ins-dept .chip").forEach((c) => c.classList.toggle("on", c === b));
    loadMistakes(); loadTrend();
  };
  $("#ins-tabs").onclick = (e) => {
    const b = e.target.closest("[data-t]"); if (!b) return;
    $$("#ins-tabs button").forEach((x) => x.classList.toggle("on", x === b));
    ["week", "digest", "eval"].forEach((t) => $(`#t-${t}`).classList.toggle("hidden", t !== b.dataset.t));
  };
  $("#rebuild").onclick = () => busy($("#rebuild"), "Recomputing", async () => {
    await api("/profile/rebuild?seed_memory=false", { method: "POST" }); await loadMistakes(); toast("Mistake profiles updated");
  });
  $("#digest-btn").onclick = () => busy($("#digest-btn"), "Reading feeds", async () => {
    const d = await api("/digest", { method: "POST", body: { days: 14 } });
    $("#digest-out").innerHTML = `<ul class="list" style="margin-top:10px">${(d.topics || []).map((t) => `<li><div class="grow">
      <div class="t">${esc(t.topic)}</div><div class="small muted">${esc(t.why_now)}</div></div>
      ${t.urgency ? `<span class="pill ${/high/i.test(t.urgency) ? "bad" : "warn"}">${esc(t.urgency)}</span>` : ""}
      <button class="btn ghost sm" data-teach="${esc(t.topic)}">Use</button></li>`).join("")}</ul>`;
  });
}

// ---------- navigation ----------
const loaders = { overview: loadOverview, library: loadLibrary, simulate: loadSimulate,
                  insights: () => Promise.all([loadMistakes(), loadTrend(), loadWeek(), loadEval()]) };
function show(view, load = true) {
  if (!document.getElementById(`v-${view}`)) view = "overview";
  $$("main > section").forEach((s) => s.classList.toggle("hidden", s.id !== `v-${view}`));
  $$("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  if (location.hash.slice(1) !== view) history.replaceState(null, "", `#${view}`);
  if (load) loaders[view]?.().catch((e) => toast(e.message));
  window.scrollTo(0, 0);
}

// global clicks: navigation, "Teach", "Update", open draft
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-teach]");
  if (t) return prefill(t.dataset.teach, t.dataset.dept);
  const u = e.target.closest("[data-refresh]");
  if (u) return prefill(u.dataset.refresh, null, "Update the earlier module with the newest guidance.");
  const o = e.target.closest("[data-open]");
  if (o) return openDraft(o.dataset.open).catch((err) => toast(err.message));
  const g = e.target.closest("[data-go]");
  if (g) return show(g.dataset.go);
});

async function sideStatus() {
  try {
    const [h, s] = await Promise.all([api("/health"), api("/modules/staleness").catch(() => ({}))]);
    $("#kb-status").innerHTML = `<span class="dot"></span>Online · ${h.kb_chunks.toLocaleString()} passages<br>
      <span>${s.last_refresh ? `Feeds refreshed ${ago(s.last_refresh)}` : "Feeds refresh daily"}</span>`;
  } catch { $("#kb-status").innerHTML = '<span class="dot" style="background:var(--bad)"></span>Backend offline'; }
}

(async function main() {
  try { META = await api("/meta"); } catch (e) { toast("Backend not reachable: " + e.message); return; }
  initCreate(); initLibrary(); initSimulate(); initInsights();
  $("#nav").onclick = (e) => { const b = e.target.closest("[data-view]"); if (b) show(b.dataset.view); };
  window.addEventListener("hashchange", () => show(location.hash.slice(1)));
  show(location.hash.slice(1) || "overview");
  sideStatus();
})();
