// SecurityPolicy AI web UI. Plain JS, no build step. Talks to the FastAPI backend on the same origin.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let META = null;

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
  document.body.append(t); setTimeout(() => t.remove(), 4000);
}

async function busy(btn, label, fn) {
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spinner"></span>${label}`;
  try { return await fn(); } catch (e) { toast(e.message); } finally { btn.disabled = false; btn.innerHTML = old; }
}

const opts = (sel, items, labels) => { sel.innerHTML = items.map((v) => `<option value="${esc(v)}">${esc(labels ? labels[v] : v)}</option>`).join(""); };

// ---------- tiny markdown renderer (headings, lists, bold, italics, links, citations) ----------
function md(src, nSources = 0) {
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|\W)\*(.+?)\*(?=\W|$)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\[S(\d+)\]/g, (m, n) => (+n <= nSources ? `<a class="cite" href="#src-${n}">S${n}</a>` : m))
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
function quality(d) {
  const m = d.review?.metrics;
  if (!m) return { cls: "", label: "Not reviewed" };
  const vals = ["factuality", "citation_cov", "relevance"].map((k) => m[k]).filter((v) => typeof v === "number");
  const score = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  const cls = score >= 0.8 ? "good" : score >= 0.6 ? "warn" : "bad";
  return { cls, label: `Quality ${Math.round(score * 100)}%`, score };
}

function draftView(d, approved) {
  const c = d.content, src = d.sources || [];
  const q = quality(d);
  const claims = (d.review?.judge?.claims || []).filter((x) => x.verdict !== "supported");
  const bad = d.guardrails?.untrusted_links || [];
  const warns = [...bad.map((u) => `Untrusted link: ${u}`), ...claims.map((x) => `Check claim: “${x.claim}”`)];

  let extra = "";
  if (c.phishing_sim) {
    const s = c.phishing_sim;
    extra += `<h3>Training email</h3><div class="card mail"><div class="mail-head"><div><b>From:</b> ${esc(s.sender)}</div>
      <div><b>Subject:</b> ${esc(s.subject)}</div></div><div>${esc(s.body).replace(/\n/g, "<br>")}</div></div>`;
  }
  if (c.quiz?.length) {
    extra += "<h3>Quiz</h3><ol>" + c.quiz.map((x) => `<li>${esc(x.question)}<ul>${x.options.map((o, i) =>
      `<li>${i === x.answer_index ? "<b>" + esc(o) + "</b> ✓" : esc(o)}</li>`).join("")}</ul></li>`).join("") + "</ol>";
  }
  if (c.red_flags?.length && !c.phishing_sim) extra += `<h3>Red flags</h3><ul>${c.red_flags.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`;
  if (c.report_how && !/how to report/i.test(c.body_markdown || "")) extra += `<h3>How to report</h3><p>${esc(c.report_how)}</p>`;

  const m = d.review?.metrics || {};
  const metricRows = Object.entries(m).filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${typeof v === "number" ? Math.round(v * 100) / 100 : esc(v)}</td></tr>`).join("");

  return `<article class="card" data-id="${d.id}">
    <div class="row" style="margin-top:0;justify-content:space-between">
      <span class="muted small">${esc(d.request.format)} · ${esc(d.request.audience)} · ${esc(d.request.language)}</span>
      <span class="pill ${q.cls}">${q.label}</span>
    </div>
    <h2 style="margin-top:10px">${esc(c.title)}</h2>
    ${warns.length ? `<p class="small" style="color:var(--warn)">⚠ ${warns.length} item(s) to check before approving. See details below.</p>` : ""}
    <div class="doc">${md(c.body_markdown, src.length)}${extra}</div>
    <div class="row">
      ${approved ? '<span class="pill good">Approved</span>'
                 : `<button class="btn" data-act="approve" ${bad.length ? "disabled title='Remove untrusted links first'" : ""}>Approve</button>`}
      <a class="btn ghost" href="/drafts/${d.id}/export?fmt=docx">Word</a>
      <a class="btn ghost" href="/drafts/${d.id}/export?fmt=md">Markdown</a>
    </div>
    <details><summary>Details: sources, review, targeted mistakes</summary>
      ${warns.length ? `<h3>To check</h3><ul>${warns.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <h3>Sources</h3><ol>${src.map((s, i) => `<li id="src-${i + 1}"><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>
        <span class="muted small">${esc(s.source)}${s.date ? " · " + esc(s.date) : ""}</span></li>`).join("") || "<li class='muted'>none</li>"}</ol>
      ${(d.mistakes || []).length ? `<h3>Targets these mistakes</h3><ul>${d.mistakes.map((x) => `<li>${esc(x.behaviour)} <span class="muted small">${esc(x.evidence)}</span></li>`).join("")}</ul>` : ""}
      ${metricRows ? `<h3>Review scores</h3><table class="small">${metricRows}</table>` : ""}
    </details>
  </article>`;
}

function bindDraft(container) {
  container.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act=approve]");
    if (!b) return;
    const id = b.closest("[data-id]").dataset.id;
    await busy(b, "Approving", async () => {
      await api(`/drafts/${id}/approve`, { method: "POST" });
      b.outerHTML = '<span class="pill good">Approved</span>';
      toast("Approved and saved to memory");
    });
  });
}

// ---------- views ----------
async function initCreate() {
  opts($("#audience"), META.audiences);
  opts($("#format"), Object.keys(META.formats), Object.fromEntries(Object.keys(META.formats).map((k) => [k, k.replace("_", " ")])));
  opts($("#language"), META.languages);
  $("#format").onchange = () => $("#policy-box").classList.toggle("hidden", $("#format").value !== "policy_summary");
  bindDraft($("#create-out"));
  $("#gen-form").onsubmit = (e) => {
    e.preventDefault();
    busy($("#gen-btn"), "Generating", async () => {
      const d = await api("/generate", { method: "POST", body: {
        topic: $("#topic").value, audience: $("#audience").value, format: $("#format").value,
        language: $("#language").value, extra: $("#extra").value, policy_text: $("#policy").value } });
      $("#create-out").innerHTML = draftView(d, false);
      $("#create-out").scrollIntoView({ behavior: "smooth" });
    });
  };
}

async function loadLibrary() {
  const rows = await api("/drafts?limit=100");
  $("#drafts").innerHTML = rows.map((r) => {
    const q = r.metrics ? quality({ review: { metrics: r.metrics } }) : { cls: "", label: "" };
    return `<li data-open="${r.id}"><div class="grow"><div class="t">${esc(r.title || r.topic)}</div>
      <div class="muted small">${esc(r.format)} · ${esc(r.audience)}</div></div>
      ${r.approved ? '<span class="pill good">approved</span>' : '<span class="pill">draft</span>'}</li>`;
  }).join("") || "<li class='muted'>Nothing yet. Create something first.</li>";
}

async function initLibrary() {
  bindDraft($("#library-out"));
  $("#drafts").onclick = async (e) => {
    const li = e.target.closest("[data-open]");
    if (!li) return;
    const [d, list] = [await api(`/drafts/${li.dataset.open}`), await api("/drafts?limit=200")];
    const approved = list.find((x) => x.id === d.id)?.approved;
    $("#library-out").innerHTML = draftView(d, approved);
    $("#library-out").scrollIntoView({ behavior: "smooth" });
  };
}

async function loadSimulate() {
  const kits = await api("/simulations");
  opts($("#kit"), kits.map((k) => k.id), Object.fromEntries(kits.map((k) => [k.id, `${k.title} (${k.audience})`])));
  $("#kit-note").textContent = kits.length ? "" : "Approve a “phishing sim” draft first.";
  const camps = await api("/campaigns");
  $("#campaigns").innerHTML = camps.map((c) => {
    const n = c.inbox_links.length, f = c.funnel;
    const bars = ["opened", "clicked", "submitted_data", "reported"].map((a) =>
      `<span>${a.replace("_", " ")}</span><div class="bar"><i style="width:${(100 * f[a]) / n}%"></i></div><span>${f[a]}/${n}</span>`).join("");
    return `<div class="card"><div class="row" style="margin-top:0;justify-content:space-between">
        <b>${esc(c.title)}</b><span class="muted small">${esc(c.department)} · ${new Date(c.created).toLocaleString()}</span></div>
      <div class="funnel" style="margin-top:12px">${bars}</div>
      <details><summary>Recipient inbox links (open one to act as that employee)</summary>
        <ul class="small">${c.inbox_links.map((l) => `<li><a href="${esc(l.url)}" target="_blank">${esc(l.user)}</a></li>`).join("")}</ul>
      </details></div>`;
  }).join("");
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

async function loadMistakes() {
  const rows = await api(`/profile/${encodeURIComponent($("#ins-dept").value)}?n=8`);
  $("#mistakes").innerHTML = rows.map((m) => `<li style="cursor:default"><div class="grow"><div>${esc(m.behaviour)}</div>
      <div class="muted small">${esc(m.evidence)} · ${esc(m.source)}</div></div>
      ${m.rate != null ? `<span class="pill ${m.rate >= 0.4 ? "bad" : "warn"}">${Math.round(m.rate * 100)}%</span>` : ""}
      <button class="btn ghost small" data-teach="${esc(m.topic)}">Teach this</button></li>`).join("")
    || "<li class='muted'>No recurring mistakes above the threshold.</li>";
}

async function loadEval() {
  const e = await api("/eval/summary");
  const s = e.summary || {};
  const setups = Object.keys(s);
  if (!setups.length) { $("#eval-out").innerHTML = "<p class='muted'>No results yet.</p>"; return; }
  const cols = Object.keys(s[setups[0]]);
  $("#eval-out").innerHTML = `<p class="muted small">${e.n_topics} topic(s). A = LLM only, B = + retrieval, C = + memory, D = full system.</p>
    <div style="overflow-x:auto"><table class="small"><tr><th></th>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>
    ${setups.map((k) => `<tr><td><b>${esc(k)}</b></td>${cols.map((c) => `<td>${s[k][c] ?? "–"}</td>`).join("")}</tr>`).join("")}</table></div>`;
}

function initInsights() {
  opts($("#ins-dept"), META.departments);
  $("#ins-dept").onchange = loadMistakes;
  $("#rebuild").onclick = () => busy($("#rebuild"), "Refreshing", async () => { await api("/profile/rebuild?seed_memory=false", { method: "POST" }); await loadMistakes(); });
  $("#mistakes").onclick = (e) => {
    const b = e.target.closest("[data-teach]");
    if (!b) return;
    $("#topic").value = b.dataset.teach; $("#audience").value = $("#ins-dept").value;
    show("create"); $("#topic").focus();
  };
  $("#digest-btn").onclick = () => busy($("#digest-btn"), "Reading feeds", async () => {
    const d = await api("/digest", { method: "POST", body: { days: 14 } });
    $("#digest-out").innerHTML = `<ul class="list">${(d.topics || []).map((t) => `<li style="cursor:default"><div class="grow">
      <div class="t">${esc(t.topic)}</div><div class="muted small">${esc(t.why_now)}</div></div>
      <button class="btn ghost small" data-topic="${esc(t.topic)}">Use</button></li>`).join("")}</ul>`;
  });
  $("#digest-out").onclick = (e) => {
    const b = e.target.closest("[data-topic]");
    if (b) { $("#topic").value = b.dataset.topic; show("create"); }
  };
}

// ---------- navigation ----------
const loaders = { library: loadLibrary, simulate: loadSimulate, insights: () => { loadMistakes(); loadEval(); } };
function show(view) {
  document.querySelectorAll("main > section").forEach((s) => s.classList.toggle("hidden", s.id !== `v-${view}`));
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  location.hash = view;
  loaders[view]?.().catch((e) => toast(e.message));
}

(async function main() {
  try { META = await api("/meta"); } catch (e) { toast("Backend not reachable: " + e.message); return; }
  initCreate(); initLibrary(); initSimulate(); initInsights();
  $("#nav").onclick = (e) => e.target.dataset.view && show(e.target.dataset.view);
  show(location.hash.slice(1) || "create");
})();
