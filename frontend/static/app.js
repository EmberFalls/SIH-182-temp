const state = { cases: [], selected: null, trace: null, activeTab: "transactions" };
const $ = selector => document.querySelector(selector);
const money = value => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 6 }).format(Number(value || 0));
const short = value => value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "—";
const dateText = value => value ? new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
const escapeAttr = escapeHtml;

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.headers.get("content-type")?.includes("application/json") ? response.json() : response;
}

function message(text, error = false) {
  const element = $("#notice");
  element.hidden = !text;
  element.textContent = text;
  element.className = `notice${error ? " error" : ""}`;
}

function safeLink(url, label) {
  if (!url || !url.startsWith("https://")) return escapeHtml(label);
  return `<a href="${escapeAttr(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)} ↗</a>`;
}

async function loadCases() {
  try {
    state.cases = await api("/cases");
    renderCases();
    if (state.selected) {
      const refreshed = state.cases.find(item => item.id === state.selected.id);
      if (refreshed) renderCase(refreshed, false);
    }
  } catch (error) {
    $("#caseList").innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`;
  }
}

function renderCases() {
  const list = $("#caseList");
  if (!state.cases.length) {
    list.innerHTML = '<p class="empty">No investigations yet.</p>';
    return;
  }
  list.innerHTML = state.cases.map(caseData => `
    <button class="case-item ${state.selected?.id === caseData.id ? "active" : ""}" data-id="${escapeAttr(caseData.id)}">
      <span class="case-state ${caseData.case_status.toLowerCase()}">${escapeHtml(caseData.case_status.replaceAll("_", " "))}</span>
      <strong>${escapeHtml(caseData.title)}</strong>
      <small>${escapeHtml(caseData.chain)} · ${escapeHtml(caseData.token_symbol)} · ${caseData.disputed_amount ? money(caseData.disputed_amount) : "Amount not set"}</small>
    </button>`).join("");
  list.querySelectorAll("button").forEach(button => {
    button.onclick = () => renderCase(state.cases.find(item => item.id === button.dataset.id), true);
  });
}

function renderCase(caseData, resetTrace) {
  state.selected = caseData;
  if (resetTrace) state.trace = null;
  $("#emptyState").hidden = true;
  $("#caseView").hidden = false;
  $("#caseMeta").textContent = `${caseData.id} · ${caseData.chain} · ${caseData.token_symbol} · ${caseData.case_status.replaceAll("_", " ")}`;
  $("#caseTitle").textContent = caseData.title;
  $("#caseWallet").textContent = caseData.suspect_wallet;
  $("#resultView").hidden = !state.trace;
  $("#preTrace").hidden = Boolean(state.trace);
  message("");
  clearInspector();
  renderCases();
}

function renderTrace(trace) {
  state.trace = trace;
  $("#preTrace").hidden = true;
  $("#resultView").hidden = false;
  const flow = trace.flow_analysis || {};
  const events = trace.provenance?.events || [];
  const failed = events.filter(event => event.status === "FAILED" || event.status === "LIMIT_REACHED").length;
  const nearest = [...trace.candidates].sort((a, b) => a.hop - b.hop || b.priority_score - a.priority_score)[0];
  $("#traceStatus").textContent = trace.status;
  $("#traceRun").textContent = `${trace.provenance?.data_mode || "LIVE_CONFIRMED"} · ${trace.run_id}`;
  $("#attributedValue").textContent = `${money(flow.allocated_amount)} ${state.selected.token_symbol}`;
  $("#flowMethod").textContent = flow.method_note?.startsWith("Conservative") ? "Case-fund allocation applied" : "Observed root outflow";
  $("#candidateCount").textContent = trace.candidates.length;
  $("#nearestHop").textContent = nearest ? `Nearest at hop ${nearest.hop}` : "No supported endpoint";
  $("#coverageValue").textContent = failed ? "Partial" : "Confirmed";
  $("#coverageDetail").textContent = `${events.filter(event => event.status === "CONFIRMED").length} wallet queries · ${failed} gaps`;
  renderScope(trace);
  renderCandidates(trace);
  renderActionChecklist(trace);
  renderEvidenceTab();
  clearInspector();
  const rendered = window.TraceGraph?.render(trace, { onSelect: renderInspector, onClear: clearInspector });
  if (!rendered) message("The interactive graph library did not load. The evidence tables remain available.", true);
  $("#challengeButton").disabled = !trace.candidates.length;
  $("#verifyButton").disabled = !trace.manifest_payload;
  $("#reportButton").disabled = false;
  $("#draftButton").disabled = !isActionReady(trace);
}

function renderScope(trace) {
  const flow = trace.flow_analysis || {};
  const entries = [
    ["Network", state.selected.chain], ["Asset", state.selected.token_symbol], ["Root", short(state.selected.suspect_wallet)],
    ["Case amount", state.selected.disputed_amount ? `${money(state.selected.disputed_amount)} ${state.selected.token_symbol}` : "Observed outflow basis"],
    ["Depth", `${trace.provenance?.max_hops || "—"} hops`], ["Trace run", trace.run_id]
  ];
  $("#scopeList").innerHTML = entries.map(([term, value]) => `<div><dt>${escapeHtml(term)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
}

function renderCandidates(trace) {
  const candidates = [...trace.candidates].sort((a, b) => a.hop - b.hop || b.priority_score - a.priority_score);
  $("#candidateBadge").textContent = candidates.length;
  $("#candidateList").innerHTML = candidates.length ? candidates.map((candidate, index) => `
    <button class="candidate-card" data-label="${escapeAttr(candidate.label_id)}" data-address="${escapeAttr(candidate.address)}">
      <span class="candidate-rank">${index + 1}</span><span class="candidate-body"><strong>${escapeHtml(candidate.vasp_name)}</strong><small>Hop ${candidate.hop} · ${candidate.evidence_grade} evidence</small><em>${money(candidate.attributed_amount)} ${escapeHtml(state.selected.token_symbol)} · ${candidate.priority_score}/100</em></span>
    </button>`).join("") : '<p class="empty compact">No reviewed VASP received case-attributed funds in this trace.</p>';
  $("#candidateList").querySelectorAll("button").forEach(button => {
    button.onclick = () => {
      const candidate = candidates.find(item => item.label_id === button.dataset.label && item.address === button.dataset.address);
      window.TraceGraph?.highlightCandidate(candidate);
      const node = state.trace.nodes.find(item => item.address === candidate.address);
      if (node) renderInspector({ type: "node", data: node });
    };
  });
}

function isActionReady(trace) {
  const failed = (trace.provenance?.events || []).some(event => event.status === "FAILED");
  return Boolean(trace.provenance?.data_mode === "LIVE_CONFIRMED" && trace.candidates.length && trace.manifest_sha256 && !failed);
}

function renderActionChecklist(trace) {
  const checks = [
    [trace.provenance?.data_mode === "LIVE_CONFIRMED", "Trace was retrieved from live confirmed-chain evidence"],
    [trace.candidates.length > 0, "A reviewed VASP endpoint received case-attributed funds"],
    [Boolean(trace.manifest_sha256), "Trace manifest and integrity hash were saved"],
    [!(trace.provenance?.events || []).some(event => event.status === "FAILED"), "No provider retrieval failure affects this run"],
    [state.selected.case_status === "UNDER_REVIEW" || state.selected.case_status === "ACTION_READY", "Investigator review recorded"]
  ];
  $("#actionChecklist").innerHTML = checks.map(([passed, text]) => `<span class="check ${passed ? "pass" : "pending"}"><i>${passed ? "✓" : "○"}</i>${escapeHtml(text)}</span>`).join("");
}

function clearInspector() {
  $("#inspectorType").textContent = "None";
  $("#inspectorContent").innerHTML = '<div class="inspector-empty"><span>⌁</span><p>Select a wallet, transfer, VASP, or evidence gap in the graph.</p></div>';
}

function infoRows(rows) {
  return `<dl class="inspector-list">${rows.map(([term, value]) => `<div><dt>${escapeHtml(term)}</dt><dd>${value}</dd></div>`).join("")}</dl>`;
}

function renderInspector(selection) {
  const { type, data } = selection;
  if (type === "edge") {
    $("#inspectorType").textContent = "Transfer";
    $("#inspectorContent").innerHTML = `<div class="inspector-title"><strong>${money(data.attributed_amount)} ${escapeHtml(data.token_symbol)}</strong><span>Case-attributed of ${money(data.transfer_amount)}</span></div>${infoRows([
      ["Transaction", safeLink(data.explorer_url, short(data.transaction_hash))], ["From", `<code>${escapeHtml(short(data.source))}</code>`], ["To", `<code>${escapeHtml(short(data.target))}</code>`],
      ["Hop", String(data.hop)], ["Confirmed", data.confirmed ? "Yes" : "No"], ["Block", data.block_number ?? "Not supplied"], ["Timestamp", escapeHtml(dateText(data.timestamp))], ["Provider", escapeHtml(data.provider)], ["Retrieved", escapeHtml(dateText(data.retrieved_at))]
    ])}`;
    return;
  }
  if (type === "frontier") {
    $("#inspectorType").textContent = "Evidence gap";
    $("#inspectorContent").innerHTML = `<div class="inspector-title warning"><strong>Trace stopped here</strong><span>${escapeHtml(data.reason.replaceAll("_", " "))}</span></div>${infoRows([["Wallet", safeLink(data.explorer_url, short(data.address))], ["Hop", String(data.hop)], ["Detail", escapeHtml(data.detail)]])}<p class="inspector-note">This is a coverage boundary, not proof that funds stopped or that no VASP exists.</p>`;
    return;
  }
  const label = data.label_evidence;
  $("#inspectorType").textContent = data.role === "vasp" ? "VASP endpoint" : data.role === "suspect" ? "Suspect wallet" : "Wallet";
  const source = label?.source;
  $("#inspectorContent").innerHTML = `<div class="inspector-title"><strong>${escapeHtml(data.label || short(data.address))}</strong><span>${escapeHtml(data.role)} · hop ${data.hop}</span></div>${infoRows([
    ["Address", safeLink(data.explorer_url, short(data.address))], ["Case inflow", `${money(data.case_inflow)} ${escapeHtml(state.selected.token_symbol)}`], ["Case outflow", `${money(data.case_outflow)} ${escapeHtml(state.selected.token_symbol)}`],
    ["Entity evidence", label ? `${escapeHtml(label.confidence)} · ${escapeHtml(label.review_status)}` : "No reviewed entity label"],
    ["Label source", source ? safeLink(source.url, source.source_name) : "Not available"], ["Observed", source ? escapeHtml(dateText(source.observed_at)) : "—"], ["Reviewer", label ? escapeHtml(label.reviewer) : "—"], ["Expires", label?.expires_at ? escapeHtml(dateText(label.expires_at)) : "No expiry recorded"]
  ])}${label ? `<button id="inspectChallenge" class="button secondary full">Challenge this label</button>` : ""}`;
  const button = $("#inspectChallenge");
  if (button) button.onclick = () => challengeEvidence("label", label.id);
}

function renderEvidenceTab() {
  const trace = state.trace;
  if (!trace) return;
  document.querySelectorAll(".tab").forEach(button => button.classList.toggle("active", button.dataset.tab === state.activeTab));
  const target = $("#evidenceTabContent");
  if (state.activeTab === "transactions") {
    const edges = trace.graph?.edges || [];
    target.innerHTML = edges.length ? `<div class="transaction-table">${edges.map(edge => `<button class="transaction-row" data-edge="${escapeAttr(edge.id)}"><span><b>${money(edge.attributed_amount)} ${escapeHtml(edge.token_symbol)}</b><small>of ${money(edge.transfer_amount)} transferred</small></span><span><code>${escapeHtml(short(edge.source))}</code> → <code>${escapeHtml(short(edge.target))}</code></span><span><small>Hop ${edge.hop} · ${escapeHtml(dateText(edge.timestamp))}</small></span></button>`).join("")}</div>` : '<p class="empty">No confirmed matching transactions were retrieved.</p>';
    target.querySelectorAll("[data-edge]").forEach(button => button.onclick = () => renderInspector({ type: "edge", data: edges.find(edge => edge.id === button.dataset.edge) }));
    return;
  }
  if (state.activeTab === "risks") {
    target.innerHTML = trace.risk_alerts.length ? trace.risk_alerts.map(risk => `<article class="evidence-card risk ${escapeAttr(risk.severity)}"><strong>${escapeHtml(risk.severity.toUpperCase())} · ${escapeHtml(risk.code.replaceAll("_", " "))}</strong><p>${escapeHtml(risk.description)}</p><small>${risk.supporting_transactions.map(short).map(escapeHtml).join(" · ")}</small></article>`).join("") : '<p class="empty">No rule-based risk patterns were triggered in this trace.</p>';
    return;
  }
  if (state.activeTab === "coverage") {
    const frontiers = trace.graph?.frontiers || [];
    const events = trace.provenance?.events || [];
    target.innerHTML = `<div class="coverage-grid"><article class="evidence-card"><strong>Retrieval summary</strong><p>${events.filter(event => event.status === "CONFIRMED").length} confirmed wallet retrievals; ${events.filter(event => event.status !== "CONFIRMED").length} bounded gaps.</p></article>${frontiers.map(frontier => `<button class="evidence-card frontier-card" data-frontier="${escapeAttr(`${frontier.address}:${frontier.reason}`)}"><strong>${escapeHtml(frontier.reason.replaceAll("_", " "))}</strong><p><code>${escapeHtml(short(frontier.address))}</code> at hop ${frontier.hop}</p><small>${escapeHtml(frontier.detail)}</small></button>`).join("")}</div>${trace.limitations.length ? `<div class="limitations">${trace.limitations.map(item => `<p>${escapeHtml(item)}</p>`).join("")}</div>` : ""}`;
    target.querySelectorAll("[data-frontier]").forEach(button => { const [address, reason] = button.dataset.frontier.split(":"); const frontier = frontiers.find(item => item.address === address && item.reason === reason); button.onclick = () => renderInspector({ type: "frontier", data: frontier }); });
    return;
  }
  target.innerHTML = trace.cross_case_alerts.length ? trace.cross_case_alerts.map(alert => `<article class="evidence-card"><strong>${escapeHtml(alert.severity.toUpperCase())} · Related case ${escapeHtml(alert.related_case_id)}</strong><p>${escapeHtml(alert.description)}</p><small>Shared wallets: ${alert.shared_addresses.map(short).map(escapeHtml).join(" · ")}</small></article>`).join("") : '<p class="empty">No shared-wallet match was found among the stored investigation runs.</p>';
}

async function traceCase() {
  if (!state.selected) return;
  const button = $("#traceButton");
  button.disabled = true;
  message("Retrieving confirmed on-chain transfers and preserving the evidence record…");
  try {
    const trace = await api(`/cases/${state.selected.id}/trace`, { method: "POST", body: JSON.stringify({ max_hops: Number($("#traceDepth").value), max_transfers_per_wallet: 100 }) });
    renderTrace(trace);
    message(trace.status === "COMPLETED" ? "Trace completed. Select a VASP or transaction to review its evidence." : "Trace returned confirmed partial or unresolved evidence. Review the coverage gaps before acting.");
  } catch (error) {
    message(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function createCase(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  if (!data.disputed_amount) delete data.disputed_amount;
  ["fir_number", "notes"].forEach(key => { if (!data[key]) delete data[key]; });
  try {
    const created = await api("/cases", { method: "POST", body: JSON.stringify(data) });
    $("#caseDialog").close();
    event.target.reset();
    await loadCases();
    renderCase(created, true);
  } catch (error) {
    message(error.message, true);
  }
}

async function markReview() {
  if (!state.selected) return;
  try {
    const updated = await api(`/cases/${state.selected.id}`, { method: "PATCH", body: JSON.stringify({ case_status: "UNDER_REVIEW" }) });
    state.selected = updated;
    await loadCases();
    if (state.trace) renderActionChecklist(state.trace);
    message("Investigator review status recorded.");
  } catch (error) { message(error.message, true); }
}

async function challengeEvidence(evidenceType, evidenceId) {
  if (!state.trace) return;
  try {
    const result = await api(`/trace-runs/${state.trace.run_id}/challenge`, { method: "POST", body: JSON.stringify({ evidence_type: evidenceType, evidence_id: evidenceId }) });
    const remaining = result.remaining_candidates.map(candidate => candidate.vasp_name).join(", ") || "no supported VASP";
    message(result.conclusion === "NOW_UNRESOLVED" ? "Challenge complete: without this evidence, no supported VASP candidate remains." : `Challenge complete: other independent evidence still supports ${remaining}.`);
  } catch (error) { message(error.message, true); }
}

async function draft() {
  if (!state.trace) return;
  try {
    const result = await api(`/trace-runs/${state.trace.run_id}/sahyog-drafts`, { method: "POST" });
    message(`Draft ${result.draft_id} created for ${result.vasp_name}. Status: ${result.status.replaceAll("_", " ")}.`);
  } catch (error) { message(error.message, true); }
}

async function verifyReceipt() {
  if (!state.trace) return;
  try {
    const result = await api(`/trace-runs/${state.trace.run_id}/verify`);
    message(result.verified ? "Trace receipt verified: the saved manifest matches its SHA-256 integrity hash." : `Trace receipt could not be verified: ${result.reason || "hash mismatch"}.`, !result.verified);
  } catch (error) { message(error.message, true); }
}

async function loadGuidedDemo() {
  try {
    const result = await api("/demo/scenarios/multihop-deposit-sweep", { method: "POST" });
    await loadCases();
    renderCase(result.case, false);
    renderTrace(result.trace);
    message("Loaded SIMULATED_DEMO. The path is useful for training and presentation, but cannot create an operational request draft.");
  } catch (error) { message(error.message, true); }
}

function bindEvents() {
  $("#newCaseButton").onclick = () => $("#caseDialog").showModal();
  $("#demoCaseButton").onclick = loadGuidedDemo;
  $("#refreshCases").onclick = loadCases;
  $("#caseForm").addEventListener("submit", createCase);
  $("#traceButton").onclick = traceCase;
  $("#reviewButton").onclick = markReview;
  $("#challengeButton").onclick = () => { const top = state.trace?.candidates?.[0]; if (top) challengeEvidence("label", top.label_id); };
  $("#verifyButton").onclick = verifyReceipt;
  $("#draftButton").onclick = draft;
  $("#reportButton").onclick = () => { if (state.trace) window.open(`/trace-runs/${state.trace.run_id}/report.pdf`, "_blank", "noopener"); };
  $("#resetGraphButton").onclick = () => { window.TraceGraph?.reset(); clearInspector(); };
  $("#fitGraphButton").onclick = () => window.TraceGraph?.reset();
  $("#zoomInButton").onclick = () => window.TraceGraph?.zoom(0.2);
  $("#zoomOutButton").onclick = () => window.TraceGraph?.zoom(-0.2);
  document.querySelectorAll(".tab").forEach(button => button.onclick = () => { state.activeTab = button.dataset.tab; renderEvidenceTab(); });
}

async function health() {
  try {
    const result = await api("/health");
    $("#apiStatus").textContent = "Service online";
    $("#apiStatus").className = "status good";
    const active = Object.entries(result.live_sources || {}).filter(([, configured]) => configured).map(([name]) => name === "etherscan" ? "Etherscan" : "TronGrid");
    $("#liveSources").textContent = active.length ? `${active.join(" + ")} connected` : "No live provider configured";
  } catch {
    $("#apiStatus").textContent = "Service unavailable";
    $("#apiStatus").className = "status bad";
    $("#liveSources").textContent = "Provider status unavailable";
  }
}

bindEvents();
health();
loadCases();
