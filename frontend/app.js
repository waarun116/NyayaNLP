/* eslint-disable no-undef */
const API_BASE = "http://localhost:8000";

const $ = (id) => document.getElementById(id);

let lastQuestion = "";
let lastResponse = "";
let lastVerification = null;

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setTheme(theme) {
  document.body.dataset.theme = theme;
  localStorage.setItem("nyaya_theme", theme);
  $("themeToggleLabel").textContent = theme === "light" ? "Light" : "Dark";
}

function initTheme() {
  const saved = localStorage.getItem("nyaya_theme");
  if (saved === "light" || saved === "dark") {
    setTheme(saved);
  } else {
    setTheme("dark");
  }
}

function donutHtml(percent, labelText) {
  const p = Math.max(0, Math.min(100, Number(percent)));
  const r = 32;
  const c = 2 * Math.PI * r;
  const dash = c * (p / 100);
  const gap = c - dash;
  const color = p < 5 ? "#4ecdc4" : p >= 95 ? "#ff6b6b" : "#ffa500";
  return `
    <div class="donut" style="display:flex;align-items:center;gap:12px;">
      <svg width="84" height="84" viewBox="0 0 84 84" aria-label="Hallucination donut chart">
        <circle cx="42" cy="42" r="${r}" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="10"/>
        <circle cx="42" cy="42" r="${r}"
          fill="none"
          stroke="${color}"
          stroke-width="10"
          stroke-linecap="round"
          stroke-dasharray="${dash} ${gap}"
          transform="rotate(-90 42 42)" />
        <text x="42" y="45" text-anchor="middle" font-size="14" font-weight="900" fill="currentColor" style="font-family: Inter, sans-serif;">${p.toFixed(0)}%</text>
      </svg>
      <div>
        <div style="font-weight:900;letter-spacing:-0.01em;">${escapeHtml(labelText)}</div>
        <div class="subtle">Estimated from automated claim checks (not a guarantee)</div>
      </div>
    </div>
  `;
}

function computeHallucination(verification) {
  const total = Number(verification?.total_claims || 0);
  const verified = Number(verification?.verified_claims || 0);
  if (verification?.hallucination_percent !== undefined && verification?.hallucination_label) {
    const hallucinationPercent = Number(verification.hallucination_percent || 0);
    const label = String(verification.hallucination_label || "");
    let chipClass = "ok";
    if (label.toLowerCase().includes("fully")) chipClass = "danger";
    else if (label.toLowerCase().includes("contains")) chipClass = "warn";
    else chipClass = "ok";
    return { hallucinationPercent, label, chipClass, total, verified };
  }

  const hallucinationPercent = total > 0 ? (1 - verified / total) * 100 : 0;
  let label = "No hallucination";
  let chipClass = "ok";
  if (total > 0) {
    if (hallucinationPercent >= 95) {
      label = "Fully hallucinated";
      chipClass = "danger";
    } else if (hallucinationPercent >= 5) {
      label = "Contains hallucinations";
      chipClass = "warn";
    }
  }
  return { hallucinationPercent, label, chipClass, total, verified };
}

function looksLikeSystemErrorResponse(text) {
  const s = String(text || "").trim().toLowerCase();
  if (!s) return true;
  if (s.startsWith("error:") || s.startsWith("traceback")) return true;
  if (s.includes("module not found") || s.includes("connection refused")) return true;
  if (s.includes("failed to generate") || s.includes("failed to verify")) return true;
  return false;
}

function formatNyayaLabel(rawVerdict) {
  const raw = String(rawVerdict || "").trim();
  if (!raw) return "";
  const cleaned = raw.replace(/[^\w\s+/-]/g, "").toLowerCase();
  const hasAnumana = cleaned.includes("anumana");
  if (cleaned.includes("pratyaksha")) {
    return hasAnumana
      ? "Pratyaksha + Anumana (प्रत्यक्ष + अनुमान)"
      : "Pratyaksha (प्रत्यक्ष)";
  }
  if (cleaned.includes("shabda")) {
    return hasAnumana
      ? "Shabda + Anumana (शब्द + अनुमान)"
      : "Shabda (शब्द)";
  }
  if (cleaned.includes("nigrahasthana")) {
    return hasAnumana
      ? "Nigrahasthana/Mithya + Anumana (निग्रहस्थान/मिथ्या + अनुमान)"
      : "Nigrahasthana/Mithya (निग्रहस्थान/मिथ्या)";
  }
  if (cleaned.includes("anumana")) {
    return "Anumana (अनुमान)";
  }
  return raw;
}

function nyayaChipHtml(nyayaObj) {
  if (!nyayaObj) return "";
  const readableNyaya = formatNyayaLabel(nyayaObj.sutra || "");
  return `
    <div class="source-chip neutral" style="border-color: rgba(255,255,255,0.12); background: rgba(255,255,255,0.04); color: var(--text); margin-top:8px;">
      ${escapeHtml(nyayaObj.icon || "")} ${escapeHtml(readableNyaya || nyayaObj.sutra || "")}
    </div>
    <div class="subtle" style="margin-top:6px; line-height:1.5;">
      <div style="color: var(--muted); font-weight:900;">${escapeHtml(nyayaObj.english || "")}</div>
      <div style="margin-top:6px;">${escapeHtml(nyayaObj.explanation || nyayaObj.description || "")}</div>
    </div>
  `;
}

function isExpertUi() {
  const el = $("expertUiToggle");
  return !!(el && el.checked);
}

function mapVerdictColor(verdict) {
  if (verdict === "✅ FULLY CORRECT") return "ok";
  if (verdict === "⚠️ PARTIALLY CORRECT") return "warn";
  return "danger";
}

function confidenceBarHtml(claim) {
  const w = Math.max(0, Math.min(100, Number(claim.confidence || 0)));
  let gradient = "";
  if (claim.verified) gradient = "linear-gradient(90deg, #4ecdc4, #44e5bb)";
  else gradient = "linear-gradient(90deg, #ff6b6b, #ffa500)";
  return `
    <div class="confidence-bar" aria-label="Claim confidence">
      <div class="confidence-fill" style="width:${w}%; background:${gradient};"></div>
    </div>
  `;
}

function renderClaimCard(claim) {
  const cls = claim.verified ? "verified" : "unverified";
  const nyayaVerdictRaw = String(claim?.verdict_secondary ? `${claim?.verdict_primary || ""} + ${claim?.verdict_secondary || ""}` : `${claim?.verdict_primary || claim?.nyaya?.sutra || ""}`);
  const nyayaVerdict = formatNyayaLabel(nyayaVerdictRaw);
  const sources = Array.isArray(claim.sources_used) && claim.sources_used.length ? claim.sources_used : ["unknown"];
  const primarySource = claim.primary_source ? `<span class="source-chip">primary: ${escapeHtml(claim.primary_source)}</span>` : "";
  const semanticPart = claim.semantic_score !== null && claim.semantic_score !== undefined
    ? `<span class="source-chip neutral">semantic ${Number(claim.semantic_score).toFixed(3)}</span>`
    : "";
  const wikidataPart =
    claim.wikidata_property_match && claim.wikidata_value
      ? `<span class="source-chip neutral">wikidata ${escapeHtml(claim.wikidata_property_match)}: ${escapeHtml(claim.wikidata_value)}</span>`
      : "";
  const semanticDetails =
    claim.semantic_score !== null && claim.semantic_score !== undefined
      ? `
        <div class="semantic-details">
          <div><b>Lexical:</b> ${Number(claim.lexical_score ?? claim.lexical_confidence ?? 0).toFixed(1)}% | <b>Semantic:</b> ${(Number(claim.semantic_score) * 100).toFixed(1)}% | <b>Final:</b> ${Number(claim.confidence || 0).toFixed(1)}%</div>
          <div style="margin-top:4px;"><b>Similarity:</b> ${(Number(claim.semantic_score) * 100).toFixed(1)}% | <b>Threshold:</b> ${(Number(claim.semantic_threshold ?? 0.25) * 100).toFixed(0)}% ${Number(claim.semantic_score) >= Number(claim.semantic_threshold ?? 0.25) ? " | ✅ Above" : " | ⚠️ Below"}</div>
          ${
            claim.semantic_matched_text
              ? `<div style="margin-top:4px;"><b>Matched:</b> ${escapeHtml(claim.semantic_matched_text)}</div>`
              : ""
          }
          ${
            claim.combined_confidence_breakdown
              ? `<div style="margin-top:4px;"><b>Contribution:</b> Lexical ${Number(claim.combined_confidence_breakdown.lexical_contribution || 0).toFixed(1)}% + Semantic ${Number(claim.combined_confidence_breakdown.semantic_contribution || 0).toFixed(1)}% (${escapeHtml(claim.combined_confidence_breakdown.weighting || "")} weighting)</div>`
              : ""
          }
        </div>
      `
      : "";
  const proofInfo = `
    <div class="subtle" style="margin-top:8px; line-height:1.55;">
      <div><b>Source:</b> ${escapeHtml(claim.source_name || "n/a")}</div>
      <div><b>Evidence:</b> ${escapeHtml(claim.evidence_sentence || claim.evidence_snippet || claim.reason || "Source checked; no textual snippet returned.")}</div>
      ${claim.match_category ? `<div><b>Match:</b> ${escapeHtml(claim.match_category)}</div>` : ""}
      ${claim.evidence_location ? `<div><b>Evidence location:</b> ${escapeHtml(claim.evidence_location)}</div>` : ""}
      ${
        claim.source_url
          ? `<div><b>Verification link:</b> <a href="${escapeHtml(claim.source_url)}" target="_blank" rel="noopener noreferrer">Click to verify</a></div>`
          : ""
      }
    </div>
  `;

  return `
    <div class="claim-card ${cls}">
      <div class="claim-top">
        <div class="claim-text">Claim: ${escapeHtml((claim.claim || "").slice(0, 140))}${(claim.claim || "").length > 140 ? "..." : ""}</div>
        <div class="subtle" style="text-align:right;">
          <div style="font-weight:900;">${claim.verified ? "Verified" : "Not verified"}</div>
          <div>Confidence ${Number(claim.confidence || 0).toFixed(1)}%</div>
          ${nyayaVerdict ? `<div class="chip neutral nyaya-verdict-chip" style="margin-top:6px;">Nyaya: ${escapeHtml(nyayaVerdict)}</div>` : ""}
        </div>
      </div>

      ${confidenceBarHtml(claim)}

      <div class="sources-row">
        ${primarySource}
        ${sources
          .map((s) => `<span class="source-chip${s === "unknown" ? " neutral" : ""}">${escapeHtml(s)}</span>`)
          .join("")}
        ${semanticPart}
        ${wikidataPart}
      </div>

      <div class="subtle" style="margin-top:10px; line-height:1.55;">
        <div style="font-weight:900; color: var(--text);">Why</div>
        <div style="color: var(--muted);">${escapeHtml(claim.reason || "")}</div>
        ${
          claim.lexical_matches !== null && claim.lexical_total_terms
            ? `<div style="margin-top:6px;">Lexical term match: ${Number(claim.lexical_matches).toFixed(1)}/${Number(claim.lexical_total_terms).toFixed(0)}</div>`
            : ""
        }
      </div>
      ${semanticDetails}
      ${proofInfo}

      ${claim.nyaya ? nyayaChipHtml(claim.nyaya) : ""}
    </div>
  `;
}

async function fetchGenerate(question, model) {
  const res = await fetch(`${API_BASE}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, model }),
  });
  if (!res.ok) throw new Error("Failed to generate response");
  return res.json();
}

async function fetchVerify(question, response, model) {
  const res = await fetch(`${API_BASE}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, response, model_used: model }),
  });
  if (!res.ok) throw new Error("Failed to verify response");
  return res.json();
}

function renderVerificationBlock(verification) {
  const chatArea = $("chatArea");
  const halluc = computeHallucination(verification);
  const verdictColorChip = mapVerdictColor(verification.verdict);
  const expert = isExpertUi();

  const nyayaVerdict = verification.nyaya_verdict || null;
  const nyayaVerdictPretty = formatNyayaLabel(nyayaVerdict?.verdict || "");
  const nyayaInner = nyayaVerdict
    ? `<div class="subtle" style="margin-top:10px; line-height:1.5;">
        <div style="font-weight:900; color: var(--text);">Nyaya verdict</div>
        <div class="nyaya-verdict-main">
          <b>${escapeHtml(nyayaVerdict.icon || "")} ${escapeHtml(nyayaVerdictPretty || nyayaVerdict.verdict || "")}</b>
          <div class="subtle" style="margin-top:6px;">${escapeHtml(nyayaVerdict.description || "")}</div>
          <details style="margin-top:6px;">
            <summary style="cursor:pointer;">Explainability</summary>
            <div class="subtle" style="margin-top:6px; line-height:1.6;">${escapeHtml(nyayaVerdict.explanation || "")}</div>
          </details>
        </div>
      </div>`
    : "";

  const claimsHtml = (verification.claims || []).map(renderClaimCard).join("");
  const nClaims = (verification.claims || []).length;

  const donut = donutHtml(halluc.hallucinationPercent, `Hallucination: ${halluc.label}`);
  const chipsRow = expert
    ? `<div class="chips-row">
        <span class="chip">Accuracy ${Number(verification.accuracy || 0).toFixed(1)}%</span>
        <span class="chip">Model ${escapeHtml(verification.model_used || "")}</span>
        <span class="chip">Semantic fusion ON</span>
      </div>`
    : `<div class="subtle" style="margin-top:8px;">${escapeHtml(verification.model_used || "")} · ${verification.verified_claims}/${verification.total_claims} claims checked</div>`;

  const nyayaBlock =
    expert || !nyayaInner
      ? ""
      : `<details class="detail-block" style="margin-top:12px;">
          <summary style="cursor:pointer; font-weight:900;">Nyaya & explainability</summary>
          ${nyayaInner}
        </details>`;

  const nyayaExplainability = verification?.nyaya_explainability;
  const nyayaXai = nyayaExplainability
    ? `<div class="subtle" style="margin-top:10px; line-height:1.55;">
        <div><b>Confidence profile:</b> ${escapeHtml(nyayaExplainability.dominant_level || "none")}</div>
        <div><b>Trust index:</b> ${Number(nyayaExplainability.trust_index || 0).toFixed(1)}/100</div>
      </div>`
    : "";

  const claimsBlock = expert
    ? `<div class="claims-grid">${claimsHtml}</div>`
    : `<details class="detail-block" style="margin-top:12px;">
        <summary style="cursor:pointer; font-weight:900;">Claim breakdown (${nClaims})</summary>
        <div class="claims-grid" style="margin-top:10px;">${claimsHtml}</div>
      </details>`;

  const cardClass = expert ? "verification-card" : "verification-card verification-card--simple";

  const block = document.createElement("div");
  block.className = "message";
  block.innerHTML = `
    <div class="${cardClass}">
      <div class="verification-header">
        <div class="verdict">
          <div>
            <div class="verdict-title">Factual check</div>
            <div style="margin-top:6px;">
              <span class="chip ${verdictColorChip}">${escapeHtml(verification.verdict || "")}</span>
              <span class="chip neutral" style="margin-left:8px;">${verification.verified_claims}/${verification.total_claims} verified</span>
            </div>
          </div>
        </div>
        ${donut}
      </div>

      ${chipsRow}

      ${expert ? nyayaInner : ""}

      ${claimsBlock}
      ${expert ? "" : nyayaBlock}
      ${nyayaXai}
    </div>
  `;
  chatArea.appendChild(block);

  chatArea.scrollTop = chatArea.scrollHeight;
}

function addMessageBubble(type, content) {
  const chatArea = $("chatArea");
  const m = document.createElement("div");
  m.className = "message";
  if (type === "question") {
    m.innerHTML = `<div class="bubble-question">${escapeHtml(content).replace(/\\n/g, "<br/>")}</div>`;
  } else {
    m.innerHTML = `<div class="bubble-answer">${escapeHtml(content).replace(/\\n/g, "<br/>")}</div>`;
  }
  chatArea.appendChild(m);
  chatArea.scrollTop = chatArea.scrollHeight;
  return m;
}

async function handleSubmit() {
  const question = $("questionInput").value.trim();
  const model = $("modelSelect").value;

  if (!question) return;
  $("questionInput").value = "";
  $("questionInput").disabled = true;
  $("sendBtn").disabled = true;

  // Add question + loading answer
  addMessageBubble("question", question);
  addMessageBubble("answer", "Generating answer... (Ollama)");

  try {
    const gen = await fetchGenerate(question, model);
    lastQuestion = question;
    lastResponse = gen.response || "";

    if (looksLikeSystemErrorResponse(lastResponse)) {
      const chatAreaErr = $("chatArea");
      const errBubbles = chatAreaErr.getElementsByClassName("bubble-answer");
      if (errBubbles.length) {
        errBubbles[errBubbles.length - 1].innerHTML = `<span style="color: var(--danger); font-weight:900;">${escapeHtml(lastResponse)}</span>`;
      }
      return;
    }

    // Replace the last answer bubble with the real answer.
    const chatArea = $("chatArea");
    const lastBubble = chatArea.lastElementChild; // might be answer bubble
    // Safer: update by searching for last "bubble-answer"
    const bubbles = chatArea.getElementsByClassName("bubble-answer");
    if (bubbles.length) {
      bubbles[bubbles.length - 1].innerHTML = escapeHtml(lastResponse).replace(/\n/g, "<br/>");
    }

    const verification = await fetchVerify(question, lastResponse, model);

    lastVerification = verification;

    const exportBtn = $("exportLastBtn");
    if (exportBtn) exportBtn.disabled = false;

    renderVerificationBlock(verification);

  } catch (e) {
    const chatArea = $("chatArea");
    const bubbles = chatArea.getElementsByClassName("bubble-answer");
    if (bubbles.length) {
      bubbles[bubbles.length - 1].innerHTML = `<span style="color: var(--danger); font-weight:900;">Error: ${escapeHtml(e.message || String(e))}</span>`;
    }
  } finally {
    $("questionInput").disabled = false;
    $("sendBtn").disabled = false;
    $("questionInput").focus();
  }
}

function downloadLast() {
  const btn = $("exportLastBtn");
  if (!btn || btn.disabled) return;
  const payload = { verification: lastVerification };
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `nyaya_export_${ts}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function init() {
  initTheme();

  $("themeToggleBtn")?.addEventListener("click", () => {
    const theme = document.body.dataset.theme === "light" ? "dark" : "light";
    setTheme(theme);
  });

  $("sendBtn")?.addEventListener("click", handleSubmit);
  $("questionInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleSubmit();
  });

  $("exportLastBtn")?.addEventListener("click", downloadLast);

  const ex = $("expertUiToggle");
  if (ex) {
    ex.checked = localStorage.getItem("nyaya_expert_ui") === "1";
    ex.addEventListener("change", () => {
      localStorage.setItem("nyaya_expert_ui", ex.checked ? "1" : "0");
    });
  }

  // default initial content
  $("chatArea").innerHTML = `
    <div class="message">
      <div class="bubble-answer">
        <div style="font-weight:900; margin-bottom:6px;">Welcome to NyayaNLP</div>
        <div class="subtle" style="line-height:1.6;">
          Ask a question to get an answer and a factual check against Wikipedia and other sources. Enable <b>Detailed verification</b> for claim-level detail.
        </div>
      </div>
    </div>
  `;
}

document.addEventListener("DOMContentLoaded", init);

