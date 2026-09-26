(() => {
  const q = selector => document.querySelector(selector);
  const money = value => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 6 }).format(Number(value || 0));
  const short = value => value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "—";
  const dateText = value => value ? new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
  const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
  let resultState = null;

  async function request(path, options = {}) {
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, ...options });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${response.status})`);
    }
    return response.json();
  }

  function rows(items) {
    return `<dl class="inspector-list">${items.map(([term, value]) => `<div><dt>${escapeHtml(term)}</dt><dd>${value}</dd></div>`).join("")}</dl>`;
  }

  function showCandidate(candidate, asset) {
    if (!candidate) return;
    q("#v2EvidenceType").textContent = candidate.status.replaceAll("_", " ");
    const components = Object.entries(candidate.attribution_evidence || {}).map(([name, score]) => [name.replaceAll("_", " "), `${score} points`]);
    const mlEvidence = (candidate.evidence_ids || []).filter(id => String(id).startsWith("MLINF-"));
    const mlNote = mlEvidence.length ? `<p class="inspector-note ml-evidence">ML INFERRED evidence: ${escapeHtml(mlEvidence.join(", "))}. It is machine-generated evidence, requires review, and cannot become a verified label.</p>` : `<p class="inspector-note">No ML evidence is included in this claim.</p>`;
    q("#v2Evidence").innerHTML = `<div class="inspector-title"><strong>${escapeHtml(candidate.entity_name)}</strong><span>${escapeHtml(candidate.status.replaceAll("_", " "))} · ${candidate.attribution_evidence_score}/100 identity evidence</span></div>${rows([["Terminal addresses", candidate.terminal_addresses.map(short).map(escapeHtml).join(" · ")], ["Endpoint role", escapeHtml(candidate.terminal_roles.map(role => role.replaceAll("_", " ")).join(", "))], ["Attributed disputed flow", `${money(candidate.attributed_amount)} ${escapeHtml(asset)} (${(Number(candidate.disputed_share) * 100).toFixed(1)}%)`], ["Minimum hops", String(candidate.min_hops)], ["First endpoint arrival", escapeHtml(dateText(candidate.first_arrival))], ["Supporting paths", escapeHtml(candidate.path_ids.join(", "))], ["Evidence records", escapeHtml(candidate.evidence_ids.join(", "))], ...components.map(([term, value]) => [term, escapeHtml(value)])])}<p class="inspector-note">Identity evidence measures support for the entity relationship. It is separate from flow materiality and is not a probability.</p>${mlNote}`;
  }

  function showInference(inference) {
    if (!inference) return;
    q("#v2EvidenceType").textContent = "Rule inference";
    const components = Object.entries(inference.evidence_components || {}).filter(([, score]) => score > 0).map(([name, score]) => [name.replaceAll("_", " "), `${score} points`]);
    const features = inference.feature_snapshot || {};
    q("#v2Evidence").innerHTML = `<div class="inspector-title warning"><strong>Probable ${escapeHtml(inference.candidate_entity_name)} deposit endpoint</strong><span>RULE INFERRED · investigator review required</span></div>${rows([["Address", `<code>${escapeHtml(short(inference.address))}</code>`], ["Role", escapeHtml(inference.inferred_role.replaceAll("_", " "))], ["Rule evidence score", `${inference.evidence_score}/100`], ["Outflow concentration", `${escapeHtml(features.outflow_concentration || "—")} toward verified entity`], ["Median receipt-to-sweep delay", features.median_receipt_to_sweep_delay_seconds == null ? "Not available" : `${escapeHtml(String(features.median_receipt_to_sweep_delay_seconds))} seconds`], ["Evidence lineage", escapeHtml(inference.evidence_lineage_ids.join(", "))], ...components.map(([term, value]) => [term, escapeHtml(value)])])}<div class="reason-list">${inference.reasons.map(reason => `<p>• ${escapeHtml(reason)}</p>`).join("")}</div><p class="inspector-note">This hypothesis used only verified target evidence. It stays unreviewed and cannot be used for a request draft.</p>`;
  }

  function render(result) {
    resultState = result;
    q("#emptyState").hidden = true;
    q("#caseView").hidden = true;
    q("#v2Workbench").hidden = false;
    const context = result.case.context;
    const asset = context.asset.symbol;
    const flow = result.flow;
    const attribution = result.attribution;
    q("#v2CaseTitle").textContent = result.case.title;
    q("#v2CaseMeta").textContent = `${result.case.id} · ${context.chain} · ${asset} · ${context.seed_type.replaceAll("_", " ")} seed`;
    q("#v2DataMode").textContent = result.data_mode === "LIVE" ? "LIVE BLOCKCHAIN DATA" : result.data_mode === "RECORDED_REAL" ? "RECORDED REAL BLOCKCHAIN SNAPSHOT" : "SYNTHETIC DEMO — NOT A REAL ATTRIBUTION";
    q("#v2DataMode").className = `data-mode ${String(result.data_mode || "SYNTHETIC").toLowerCase()}`;
    q("#v2Limitation").textContent = (result.limitations || []).join(" ");
    q("#v2Disputed").textContent = `${money(flow.seed_amount)} ${asset}`;
    q("#v2Accounted").textContent = `${money(flow.terminal_amount)} ${asset}`;
    q("#v2Unresolved").textContent = `${money(flow.unresolved_amount)} ${asset}`;
    q("#v2Retained").textContent = `${money(flow.retained_amount)} ${asset} retained in observed wallets`;
    q("#v2EndpointCount").textContent = attribution.candidates.length;
    const nearest = attribution.candidates.find(item => item.id === attribution.nearest_actionable_candidate_id);
    const largest = attribution.candidates.find(item => item.id === attribution.largest_material_candidate_id);
    q("#v2EndpointSummary").textContent = nearest ? `Nearest: ${nearest.min_hops} hop${nearest.min_hops === 1 ? "" : "s"}${largest && largest.id !== nearest.id ? ` · Largest: ${money(largest.attributed_amount)} ${asset}` : ""}` : "No supported endpoint";
    q("#v2Candidates").innerHTML = attribution.candidates.length ? attribution.candidates.map(candidate => {
      const marker = [candidate.id === attribution.nearest_actionable_candidate_id ? "Nearest by hops" : "", candidate.id === attribution.largest_material_candidate_id ? "Largest by value" : ""].filter(Boolean).join(" · ");
      return `<button class="v2-candidate-card" data-candidate="${escapeHtml(candidate.id)}"><div class="v2-card-top"><span class="claim-state ${escapeHtml(candidate.status.toLowerCase())}">${escapeHtml(candidate.status.replaceAll("_", " "))}</span><span>${escapeHtml(marker)}</span></div><strong>${escapeHtml(candidate.entity_name)}</strong><p>${escapeHtml(candidate.terminal_roles.map(role => role.replaceAll("_", " ").toLowerCase()).join(", "))}</p><div class="v2-metrics"><span><b>${money(candidate.attributed_amount)} ${escapeHtml(asset)}</b>Attributable flow</span><span><b>${(Number(candidate.disputed_share) * 100).toFixed(1)}%</b>Of disputed value</span><span><b>${candidate.min_hops}</b>Minimum hops</span><span><b>${candidate.attribution_evidence_score} / 100</b>Identity evidence</span></div><small>${candidate.path_ids.length} supporting path${candidate.path_ids.length === 1 ? "" : "s"} · ${escapeHtml(candidate.attribution_band.toLowerCase())} evidence band</small></button>`;
    }).join("") : '<p class="empty">No VASP candidate meets the configured evidence threshold. The unresolved outcome is retained.</p>';
    q("#v2Candidates").querySelectorAll("[data-candidate]").forEach(button => button.onclick = () => showCandidate(attribution.candidates.find(item => item.id === button.dataset.candidate), asset));
    const transferById = Object.fromEntries((result.transfers || []).map(item => [item.id, item]));
    q("#v2Transfers").innerHTML = flow.allocations.length ? flow.allocations.map(allocation => {
      const transfer = transferById[allocation.transfer_id] || {};
      return `<div class="v2-transfer-row"><span><b>${money(allocation.attributed_disputed_amount)} ${escapeHtml(asset)}</b><small>case-attributed of ${money(allocation.transfer_amount)} transferred</small></span><span><code>${escapeHtml(short(allocation.source_address))}</code> → <code>${escapeHtml(short(allocation.destination_address))}</code></span><span>Hop ${allocation.depth} · ${escapeHtml(dateText(allocation.timestamp || transfer.timestamp))}</span></div>`;
    }).join("") : '<p class="empty">No case-attributed transfers were recorded.</p>';
    const inferences = result.deposit_inferences || [];
    q("#v2Inferences").innerHTML = inferences.length ? inferences.map(inference => `<button class="v2-inference-card" data-inference="${escapeHtml(inference.id)}"><span class="claim-state inferred">Rule inferred · awaiting review</span><strong>Probable ${escapeHtml(inference.candidate_entity_name)} deposit endpoint</strong><p><code>${escapeHtml(short(inference.address))}</code> · ${inference.evidence_score}/100 rule evidence</p><small>${escapeHtml(inference.reasons[0] || "No explanation recorded.")}</small></button>`).join("") : '<p class="empty">No deposit-pattern hypothesis was generated.</p>';
    q("#v2Inferences").querySelectorAll("[data-inference]").forEach(button => button.onclick = () => showInference(inferences.find(item => item.id === button.dataset.inference)));
    renderActionability(result.id, asset);
    q("#v2EvidenceType").textContent = "None";
    q("#v2Evidence").innerHTML = '<p class="empty">Select an endpoint or deposit inference to inspect its evidence.</p>';
  }

  async function renderActionability(resultId, asset) {
    const target = q("#v2Actionability");
    if (!target || !resultId) return;
    target.innerHTML = '<p class="empty">Checking route readiness and evidence challenges…</p>';
    try {
      const assessment = await request(`/v2/results/${resultId}/actionability`, { method: "GET" });
      if (resultState?.id !== resultId) return;
      target.innerHTML = assessment.candidates.length ? assessment.candidates.map(item => {
        const amount = `${money(item.envelope.maximum_request_amount)} ${escapeHtml(asset)}`;
        const status = item.recommendation.replaceAll("_", " ");
        const challenges = item.challenges.length ? item.challenges.map(challenge => `<li><b>${escapeHtml(challenge.severity)}</b> · ${escapeHtml(challenge.claim)}<small>${escapeHtml(challenge.resolution)}</small></li>`).join("") : '<li>No unresolved challenge was found.</li>';
        const next = item.next_best_evidence.length ? item.next_best_evidence.map(step => `<li>${escapeHtml(step.action)}</li>`).join("") : '<li>Proceed to investigator and legal review.</li>';
        return `<article class="v2-inference-card actionability-card"><span class="claim-state ${escapeHtml(item.recommendation.toLowerCase())}">${escapeHtml(status)}</span><strong>${escapeHtml(item.entity_name)}</strong><p><b>${amount}</b> maximum local request amount · ${escapeHtml(item.route_state.replaceAll("_", " "))} routing profile</p><small>Confirmed: ${money(item.envelope.confirmed_attributed_amount)} · Model estimate: ${money(item.envelope.model_attributed_amount)} · Unresolved case value: ${money(item.envelope.unresolved_case_amount)}</small><details><summary>Challenge the conclusion (${item.challenges.length})</summary><ul class="actionability-list">${challenges}</ul></details><details open><summary>Next best evidence</summary><ol class="actionability-list">${next}</ol></details></article>`;
      }).join("") : '<p class="empty">No VASP candidate is eligible for an actionability assessment.</p>';
    } catch (error) {
      target.innerHTML = `<p class="empty">Actionability assessment unavailable: ${escapeHtml(error.message)}</p>`;
    }
  }
  async function load() {
    try {
      render(await request("/demo/scenarios/v2-deposit-inference"));
    } catch (error) {
      const notice = q("#notice");
      if (notice) { notice.hidden = false; notice.className = "notice error"; notice.textContent = error.message; }
    }
  }

  async function importRecordedPackage(event) {
    event.preventDefault();
    const form = event.target;
    const submit = q("#recordedImportForm button[value='default']");
    submit.disabled = true;
    try {
      const values = Object.fromEntries(new FormData(form));
      const payload = JSON.parse(values.package_json);
      const result = await request("/v2/imports/recorded-trace", { body: JSON.stringify(payload) });
      const caseRecord = await request(`/v2/cases/${result.case_id}`, { method: "GET" });
      q("#recordedImportDialog").close();
      form.reset();
      render({ ...result, case: caseRecord });
    } catch (error) {
      const notice = q("#notice");
      if (notice) { notice.hidden = false; notice.className = "notice error"; notice.textContent = `Recorded package was not imported: ${error.message}`; }
    } finally {
      submit.disabled = false;
    }
  }
  async function importRecordedCsv(event) {
    event.preventDefault();
    const form = event.target;
    const submit = q("#csvImportForm button[value='default']");
    submit.disabled = true;
    try {
      const values = Object.fromEntries(new FormData(form));
      const payload = { case: JSON.parse(values.case_json), transfers_csv: values.transfers_csv };
      const result = await request("/v2/imports/recorded-trace/csv", { body: JSON.stringify(payload) });
      const caseRecord = await request(`/v2/cases/${result.case_id}`, { method: "GET" });
      q("#csvImportDialog").close();
      form.reset();
      render({ ...result, case: caseRecord });
    } catch (error) {
      const notice = q("#notice");
      if (notice) { notice.hidden = false; notice.className = "notice error"; notice.textContent = `Trace CSV was not imported: ${error.message}`; }
    } finally {
      submit.disabled = false;
    }
  }

  async function importIntelligenceCsv(event) {
    event.preventDefault();
    const form = event.target;
    const submit = q("#intelligenceImportForm button[value='default']");
    submit.disabled = true;
    try {
      const values = Object.fromEntries(new FormData(form));
      const outcome = await request("/v2/intelligence/import/assertions/csv", { body: JSON.stringify({ csv_text: values.csv_text }) });
      q("#intelligenceImportDialog").close();
      form.reset();
      const notice = q("#notice");
      if (notice) { notice.hidden = false; notice.className = outcome.rejected?.length ? "notice error" : "notice success"; notice.textContent = `Imported ${outcome.imported} intelligence assertion${outcome.imported === 1 ? "" : "s"}${outcome.rejected?.length ? `; ${outcome.rejected.length} row(s) need correction.` : "."}`; }
    } catch (error) {
      const notice = q("#notice");
      if (notice) { notice.hidden = false; notice.className = "notice error"; notice.textContent = `Intelligence CSV was not imported: ${error.message}`; }
    } finally {
      submit.disabled = false;
    }
  }
  function notice(text, type = "success") {
    const target = q("#notice");
    if (target) { target.hidden = false; target.className = `notice ${type}`; target.textContent = text; }
  }

  async function lookupIntelligence(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.target));
    const target = q("#intelligenceReviewResults");
    target.innerHTML = '<p class="empty">Loading assertions…</p>';
    try {
      const entries = await request(`/v2/intelligence/assertions?address=${encodeURIComponent(values.address.trim())}&chain=${encodeURIComponent(values.chain)}`, { method: "GET" });
      target.innerHTML = entries.length ? entries.map(item => `<article class="v2-inference-card"><span class="claim-state ${escapeHtml(item.effective_review_state.toLowerCase())}">${escapeHtml(item.effective_review_state)}</span><strong>${escapeHtml(item.entity.canonical_name)}</strong><p><code>${escapeHtml(short(item.assertion.address))}</code> · ${escapeHtml(item.assertion.role.replaceAll("_", " "))}</p><small>${escapeHtml(item.source.name)} · ${escapeHtml(item.source.trust_tier)} tier · ${escapeHtml(item.assertion.assertion_type)}</small><div class="dialog-actions"><button class="button secondary small" data-review-assertion="${escapeHtml(item.assertion.id)}" data-review-state="REVIEWED">Approve</button><button class="button secondary small" data-review-assertion="${escapeHtml(item.assertion.id)}" data-review-state="REJECTED">Reject</button></div></article>`).join("") : '<p class="empty">No assertions exist for this address and chain.</p>';
      target.querySelectorAll("[data-review-assertion]").forEach(button => button.onclick = async () => {
        const rationale = window.prompt(`${button.dataset.reviewState === "REVIEWED" ? "Approve" : "Reject"} rationale (minimum 3 characters):`);
        if (!rationale) return;
        try {
          await request(`/v2/intelligence/assertions/${button.dataset.reviewAssertion}/reviews`, { body: JSON.stringify({ review_state: button.dataset.reviewState, rationale }) });
          notice(`Assertion ${button.dataset.reviewState.toLowerCase()} and review history saved.`);
          event.target.requestSubmit();
        } catch (error) { notice(error.message, "error"); }
      });
    } catch (error) { target.innerHTML = `<p class="empty">Could not load assertions: ${escapeHtml(error.message)}</p>`; }
  }

  async function extractBridgeEvent(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.target));
    const target = q("#bridgeWorkflowResults");
    try {
      const transfer = JSON.parse(values.transfer_json);
      let result;
      if (values.mode === "wormhole") {
        result = await request("/v2/bridges/wormhole/evm-extract", { body: JSON.stringify({ raw_evidence_id: values.raw_evidence_id, transfer, wormhole_chain_id: Number(values.protocol), core_contract: values.core_contract }) });
      } else {
        result = await request("/v2/bridges/events/extract", { body: JSON.stringify({ protocol: values.protocol, direction: values.direction, raw_evidence_id: values.raw_evidence_id, transfer }) });
      }
      target.innerHTML = `<article class="v2-inference-card"><span class="claim-state verified">Exact event retained</span><strong>${escapeHtml(result.protocol)} · ${escapeHtml(result.direction)}</strong><p>Message ID: <code>${escapeHtml(result.message_id)}</code></p><small>Saved event ID: ${escapeHtml(result.id)}. Use this ID in the exact-event resolution form.</small></article>`;
      notice("Bridge event extracted from retained evidence.");
    } catch (error) { target.innerHTML = `<p class="empty">Bridge extraction failed: ${escapeHtml(error.message)}</p>`; }
  }

  async function resolveBridgeEvents(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.target));
    const target = q("#bridgeWorkflowResults");
    try {
      const link = await request("/v2/cross-chain/links/resolve-events", { body: JSON.stringify(values) });
      target.innerHTML = `<article class="v2-inference-card"><span class="claim-state verified">Verified cross-chain link</span><strong>${escapeHtml(link.protocol)} route resolved</strong><p>${escapeHtml(link.source_chain)} → ${escapeHtml(link.destination_chain)} · message <code>${escapeHtml(link.message_id)}</code></p><small>Destination continuation is now evidence-bound. Link ID: ${escapeHtml(link.id)}</small></article>`;
      notice("Exact bridge-event pair verified.");
    } catch (error) { target.innerHTML = `<p class="empty">Bridge resolution failed: ${escapeHtml(error.message)}</p>`; }
  }

  async function loadCaseHistory() {
    const target = q("#caseHistoryResults");
    target.innerHTML = '<p class="empty">Loading saved investigation history…</p>';
    try {
      const cases = await request("/v2/cases", { method: "GET" });
      const rows = await Promise.all(cases.map(async item => ({ item, results: await request(`/v2/cases/${item.id}/results`, { method: "GET" }), jobs: await request(`/v2/trace-jobs?case_id=${encodeURIComponent(item.id)}`, { method: "GET" }) })));
      target.innerHTML = rows.length ? rows.map(({ item, results, jobs }) => `<div class="v2-transfer-row"><span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.status)} · ${escapeHtml(item.context.data_mode)}</small></span><span>${results.length} saved result${results.length === 1 ? "" : "s"} · ${jobs.length} trace job${jobs.length === 1 ? "" : "s"}</span><span>${results.map(result => `<button class="button secondary small" data-open-result="${escapeHtml(result.id)}" data-case-id="${escapeHtml(item.id)}">Open v${result.version}</button>`).join(" ") || "No result yet"}</span></div>`).join("") : '<p class="empty">No v2 investigations have been saved yet.</p>';
      target.querySelectorAll("[data-open-result]").forEach(button => button.onclick = async () => {
        const [result, caseRecord] = await Promise.all([request(`/v2/results/${button.dataset.openResult}`, { method: "GET" }), request(`/v2/cases/${button.dataset.caseId}`, { method: "GET" })]);
        q("#caseHistoryDialog").close(); render({ ...result, case: caseRecord });
      });
    } catch (error) { target.innerHTML = `<p class="empty">Could not load case history: ${escapeHtml(error.message)}</p>`; }
  }
  async function createLiveCase(event) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.target));
    const asset = {
      chain: values.chain,
      symbol: values.symbol.toUpperCase(),
      decimals: Number(values.decimals),
    };
    if (values.contract_address.trim()) asset.contract_address = values.contract_address.trim();
    const incident = new Date(values.incident_time);
    if (Number.isNaN(incident.getTime())) throw new Error("Provide a valid incident time.");
    const body = {
      title: values.title,
      context: {
        seed_type: "wallet_context", chain: values.chain, asset,
        disputed_amount: values.disputed_amount, incident_time: incident.toISOString(),
        seed_wallet: values.wallet.trim(), data_mode: "LIVE",
      },
    };
    const submit = q("#v2CaseForm button[value='default']");
    submit.disabled = true;
    try {
      const caseRecord = await request("/v2/cases", { body: JSON.stringify(body) });
      const result = await request(`/v2/cases/${caseRecord.id}/trace`, { body: "{}" });
      q("#v2CaseDialog").close();
      event.target.reset();
      render({ ...result, case: caseRecord });
    } catch (error) {
      const notice = q("#notice");
      if (notice) { notice.hidden = false; notice.className = "notice error"; notice.textContent = error.message; }
    } finally {
      submit.disabled = false;
    }
  }

  async function createDraft() {
    if (!resultState?.id) return;
    try {
      const draft = await request(`/v2/results/${resultState.id}/request-drafts`);
      q("#v2Limitation").textContent = `Local request draft ${draft.id} created. ${draft.boundary_notice}`;
    } catch (error) {
      q("#v2Limitation").textContent = error.message;
    }
  }
  function close() {
    q("#v2Workbench").hidden = true;
    q("#emptyState").hidden = false;
  }

  q("#importRecordedButton")?.addEventListener("click", () => q("#recordedImportDialog").showModal());
  q("#reviewIntelligenceButton")?.addEventListener("click", () => q("#intelligenceReviewDialog").showModal());
  q("#bridgeWorkflowButton")?.addEventListener("click", () => q("#bridgeWorkflowDialog").showModal());
  q("#caseHistoryButton")?.addEventListener("click", () => { q("#caseHistoryDialog").showModal(); loadCaseHistory(); });
  q("#intelligenceLookupForm")?.addEventListener("submit", lookupIntelligence);
  q("#bridgeExtractForm")?.addEventListener("submit", extractBridgeEvent);
  q("#bridgeResolveForm")?.addEventListener("submit", resolveBridgeEvents);
  q("#importCsvButton")?.addEventListener("click", () => q("#csvImportDialog").showModal());
  q("#intelligenceImportButton")?.addEventListener("click", () => q("#intelligenceImportDialog").showModal());
  q("#recordedImportForm")?.addEventListener("submit", importRecordedPackage);
  q("#csvImportForm")?.addEventListener("submit", importRecordedCsv);
  q("#intelligenceImportForm")?.addEventListener("submit", importIntelligenceCsv);
  q("#v2DemoButton")?.addEventListener("click", load);
  q("#newV2CaseButton")?.addEventListener("click", () => q("#v2CaseDialog").showModal());
  q("#v2CaseForm")?.addEventListener("submit", createLiveCase);
  q("#v2ReportButton")?.addEventListener("click", () => { if (resultState?.id) window.open(`/v2/results/${resultState.id}/report.pdf`, "_blank", "noopener"); });
  q("#v2DraftButton")?.addEventListener("click", createDraft);
  q("#closeV2Button")?.addEventListener("click", close);
  window.VaspTraceV2 = { load, render, get result() { return resultState; } };
})();
