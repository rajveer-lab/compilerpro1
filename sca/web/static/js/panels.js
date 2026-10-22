/**
 * Panels and Results View Module (Tabs, Output, Recommendations, Score, Metrics, AST).
 */

import { jumpToLine, getActiveTab } from "./editor.js";
import { renderDiffPreview } from "./diff.js";
import { renderAstTree } from "./ast_viewer.js";

let currentDiagnostics = [];
let currentMisconceptions = {};
let currentRecommendations = [];
let currentScore = null;
let currentMetrics = [];
let currentFilter = "all";
let currentSource = "";

let applyFixHandler = null;
let applyAllSafeHandler = null;

export function initPanels(onApplyFix, onApplyAllSafe) {
  applyFixHandler = onApplyFix;
  applyAllSafeHandler = onApplyAllSafe;

  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const targetPanelId = tab.getAttribute("data-tab");
      switchTab(targetPanelId);
    });
  });

  // Filter chips on Output tab
  const filterChips = document.querySelectorAll(".chip-filter");
  filterChips.forEach(chip => {
    chip.addEventListener("click", () => {
      filterChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      currentFilter = chip.getAttribute("data-filter");
      renderDiagnosticsList();
    });
  });
}

export function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    if (btn.getAttribute("data-tab") === tabId) {
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
    } else {
      btn.classList.remove("active");
      btn.setAttribute("aria-selected", "false");
    }
  });

  document.querySelectorAll(".tab-panel").forEach(panel => {
    if (panel.id === `panel-${tabId}`) {
      panel.classList.add("active");
    } else {
      panel.classList.remove("active");
    }
  });
}

export function renderResults(result, sourceCode) {
  currentSource = sourceCode || "";

  if (result.parse_errors && result.parse_errors.length > 0) {
    currentDiagnostics = [];
    currentRecommendations = [];
    currentScore = null;
    currentMetrics = [];
    updateTabBadges(result);
    renderSyntaxErrors(result.parse_errors);
    renderRecommendationsEmpty("Cannot generate recommendations due to syntax errors.");
    renderScoreEmpty("Quality score unavailable due to syntax errors.");
    renderMetricsEmpty("Metrics unavailable due to syntax errors.");
    renderAstEmpty("AST unavailable due to syntax errors.");
    return;
  }

  currentDiagnostics = result.diagnostics || [];
  currentMisconceptions = Object.fromEntries((result.misconceptions || []).map(m => [m.id, m]));
  currentRecommendations = result.recommendations || [];
  currentScore = result.score;
  currentMetrics = result.metrics || [];

  updateTabBadges(result);
  renderDiagnosticsList();
  renderRecommendations(currentRecommendations, currentScore, result.projected_score);
  renderScore(currentScore, result.projected_score);
  renderMetrics(currentMetrics);
}

function updateTabBadges(result) {
  const outputBadge = document.getElementById("badge-output");
  if (outputBadge) {
    const total = (result.parse_errors && result.parse_errors.length > 0)
      ? result.parse_errors.length
      : (result.diagnostics ? result.diagnostics.length : 0);
    outputBadge.textContent = total;
  }

  const recBadge = document.getElementById("badge-recommendations");
  if (recBadge) {
    recBadge.textContent = (result.recommendations ? result.recommendations.length : 0);
  }

  const summary = result.summary || { error: 0, warning: 0, info: 0 };
  const totalDiags = (result.diagnostics || []).length;

  const countAll = document.getElementById("count-filter-all");
  const countErr = document.getElementById("count-filter-error");
  const countWarn = document.getElementById("count-filter-warning");
  const countInfo = document.getElementById("count-filter-info");

  if (countAll) countAll.textContent = totalDiags;
  if (countErr) countErr.textContent = summary.error || 0;
  if (countWarn) countWarn.textContent = summary.warning || 0;
  if (countInfo) countInfo.textContent = summary.info || 0;
}

function renderSyntaxErrors(errors) {
  const container = document.getElementById("output-diagnostics-container");
  let html = `<div class="syntax-error-banner">
    <div class="syntax-error-title">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
      Syntax / Parser Error (${errors.length})
    </div>
    <p style="font-size: 13px; margin-bottom: 8px;">The C parser encountered errors and could not generate an AST:</p>`;

  for (const err of errors) {
    html += `<div style="font-family: var(--font-mono); font-size: 12px; margin-top: 4px; padding: 4px 8px; background: rgba(0,0,0,0.2); border-radius: 4px;">
      Line ${err.line}, Col ${err.col}: ${escapeHtml(err.message)}
    </div>`;
  }
  html += `</div>`;
  container.innerHTML = html;
}

function renderDiagnosticsList() {
  const container = document.getElementById("output-diagnostics-container");
  if (!container) return;

  const lines = currentSource.split("\n");

  const filtered = currentDiagnostics.filter(d => {
    if (currentFilter === "all") return true;
    return d.severity === currentFilter;
  });

  if (filtered.length === 0) {
    if (currentDiagnostics.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
          <h3 style="font-weight: 600;">No Issues Detected</h3>
          <p style="font-size: 13px;">Your C code passed all quality checks with a perfect 100/100 score.</p>
        </div>`;
    } else {
      container.innerHTML = `
        <div class="empty-state">
          <p style="font-size: 13px;">No diagnostics matching filter "${currentFilter}".</p>
        </div>`;
    }
    return;
  }

  let html = `<div class="diagnostics-list">`;
  for (const d of filtered) {
    const sev = d.severity || "warning";
    const lineNum = d.line;
    const colNum = d.col || 1;
    const lineSnippet = (lines[lineNum - 1] !== undefined) ? lines[lineNum - 1].trim() : "";
    const misconception = d.misconception ? currentMisconceptions[d.misconception] : null;

    html += `
      <div class="diag-card ${sev}" data-line="${lineNum}" data-col="${colNum}">
        <div class="diag-header">
          <span class="diag-rule">${escapeHtml(d.rule_id)}</span>
          <span class="diag-loc">Ln ${lineNum}, Col ${colNum}</span>
        </div>
        <div class="diag-msg">${escapeHtml(d.message)}</div>
        ${lineSnippet ? `<div class="diag-snippet">${escapeHtml(lineSnippet)}</div>` : ""}
        ${misconception ? `<div class="diag-misconception" title="${escapeHtml(misconception.explanation)}">Misconception: "${escapeHtml(misconception.title)}" (see Learning tab)</div>` : ""}
      </div>
    `;
  }
  html += `</div>`;

  container.innerHTML = html;

  container.querySelectorAll(".diag-card").forEach(card => {
    card.addEventListener("click", () => {
      const line = parseInt(card.getAttribute("data-line"), 10);
      const col = parseInt(card.getAttribute("data-col"), 10);
      jumpToLine(line, col);
    });
  });
}

function renderRecommendations(recommendations, scoreObj, projectedScore) {
  const container = document.getElementById("recommendations-container");
  if (!container) return;

  if (!recommendations || recommendations.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
        <h3 style="font-weight: 600;">Code is in Great Shape</h3>
        <p style="font-size: 13px;">No active recommendations. All analyzer rules are satisfied.</p>
      </div>`;
    return;
  }

  const lines = currentSource.split("\n");
  const safeRecs = recommendations.filter(r => r.safety === "safe" && r.edits && r.edits.length > 0);
  const currentVal = scoreObj ? scoreObj.value : 100;
  const projectedVal = projectedScore !== undefined ? projectedScore : currentVal;

  let html = "";

  if (safeRecs.length > 0 && projectedVal > currentVal) {
    html += `
      <div class="rec-global-banner">
        <div class="rec-global-info">
          <span class="rec-global-title">Applying all safe fixes would raise your score from ${currentVal} to ${projectedVal} (+${projectedVal - currentVal} pts)</span>
          <span class="rec-global-sub">Harmless automated fixes with zero behavioral impact.</span>
        </div>
        <button id="btn-apply-all-safe" class="btn-apply-all">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
          <span>Apply all safe fixes (${safeRecs.length})</span>
        </button>
      </div>
    `;
  }

  html += `<div class="rec-cards-list">`;

  for (const rec of recommendations) {
    const isSafe = rec.safety === "safe";
    const isReview = rec.safety === "review";
    const hasEdits = rec.edits && rec.edits.length > 0;

    let isStale = false;
    if (hasEdits) {
      for (const edit of rec.edits) {
        if (edit.expected_old && edit.expected_old.length > 0) {
          const actualLines = lines.slice(edit.line_start - 1, edit.line_end);
          if (JSON.stringify(actualLines) !== JSON.stringify(edit.expected_old)) {
            isStale = true;
            break;
          }
        }
      }
    }

    const safetyClass = `safety-${rec.safety}`;
    const safetyLabel = isSafe ? "Safe fix" : (isReview ? "Review fix" : "Manual advice");

    html += `
      <div class="rec-card ${safetyClass}" data-id="${rec.id}">
        <div class="rec-card-header">
          <div class="rec-card-title-group">
            <span class="rec-safety-badge ${safetyClass}">${safetyLabel}</span>
            <span class="rec-rule-badge">${escapeHtml(rec.rule_id)}</span>
            <span class="rec-card-loc">Line ${rec.line}</span>
          </div>
          <span class="rec-gain-badge">+${rec.score_gain} pts</span>
        </div>

        <h4 class="rec-title">${escapeHtml(rec.title)}</h4>
        <p class="rec-explanation">${escapeHtml(rec.explanation)}</p>

        ${hasEdits ? renderDiffPreview(rec.edits) : ""}

        <div class="rec-card-actions">
          ${hasEdits ? `
            <button class="btn-apply-fix" data-rec-id="${rec.id}" ${isStale ? "disabled title='Code in editor has changed'" : ""}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
              <span>${isStale ? "Stale (code changed)" : "Apply fix"}</span>
            </button>
          ` : `
            <span class="rec-manual-note">Manual guidance — apply change directly in editor</span>
          `}
          <button class="btn-jump-loc" data-line="${rec.line}" data-col="${rec.col}">
            Jump to line
          </button>
        </div>
      </div>
    `;
  }

  html += `</div>`;
  container.innerHTML = html;

  const applyAllBtn = document.getElementById("btn-apply-all-safe");
  if (applyAllBtn && applyAllSafeHandler) {
    applyAllBtn.addEventListener("click", () => {
      const allEdits = [];
      for (const r of safeRecs) {
        allEdits.push(...r.edits);
      }
      applyAllSafeHandler(allEdits);
    });
  }

  container.querySelectorAll(".btn-apply-fix").forEach(btn => {
    btn.addEventListener("click", () => {
      const recId = btn.getAttribute("data-rec-id");
      const rec = recommendations.find(r => r.id === recId);
      if (rec && applyFixHandler) {
        applyFixHandler(rec);
      }
    });
  });

  container.querySelectorAll(".btn-jump-loc").forEach(btn => {
    btn.addEventListener("click", () => {
      const line = parseInt(btn.getAttribute("data-line"), 10);
      const col = parseInt(btn.getAttribute("data-col"), 10);
      jumpToLine(line, col);
    });
  });
}

function renderRecommendationsEmpty(msg) {
  const container = document.getElementById("recommendations-container");
  if (container) {
    container.innerHTML = `<div class="empty-state"><p style="font-size:13px;">${msg}</p></div>`;
  }
}

function renderScore(scoreObj, projectedScore) {
  const container = document.getElementById("score-container");
  if (!container) return;

  if (!scoreObj) {
    renderScoreEmpty("Run analysis to view code quality score.");
    return;
  }

  const score = scoreObj.value;
  const grade = scoreObj.grade;
  const issuesCount = scoreObj.total_issues;
  const deductions = scoreObj.deductions || {};

  let gradeColor = "#2ea043";
  if (score < 60) gradeColor = "#f85149";
  else if (score < 70) gradeColor = "#db6d28";
  else if (score < 80) gradeColor = "#d29922";
  else if (score < 90) gradeColor = "#388bfd";

  const radius = 65;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;

  let html = `
    <div class="score-card-hero">
      <div class="score-gauge-wrapper">
        <svg class="score-gauge" width="160" height="160" viewBox="0 0 160 160">
          <circle cx="80" cy="80" r="${radius}" fill="none" stroke="var(--border-color)" stroke-width="12"></circle>
          <circle cx="80" cy="80" r="${radius}" fill="none" stroke="${gradeColor}" stroke-width="12"
            stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
            stroke-linecap="round" transform="rotate(-90 80 80)"
            style="transition: stroke-dashoffset 0.8s ease;"></circle>
          <text x="80" y="76" text-anchor="middle" font-size="34" font-weight="700" fill="var(--text-main)" font-family="var(--font-sans)">${score}</text>
          <text x="80" y="98" text-anchor="middle" font-size="12" font-weight="600" fill="var(--text-secondary)">/ 100</text>
        </svg>
      </div>
      <div class="score-summary-details">
        <div class="grade-pill" style="background-color: ${gradeColor}22; border: 1px solid ${gradeColor}55; color: ${gradeColor};">
          Grade: ${escapeHtml(grade)}
        </div>
        <div class="score-stat-line">
          <span>Total Issues Found:</span>
          <strong>${issuesCount}</strong>
        </div>
      </div>
    </div>

    ${renderScoreComparison(scoreObj, projectedScore)}

    <div class="deductions-section">
      <h4 class="section-title">Score Deductions by Rule</h4>
  `;

  const deductionEntries = Object.entries(deductions);
  if (deductionEntries.length === 0) {
    html += `
      <div class="perfect-code-callout">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2ea043" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
        <span>Perfect code! No score deductions.</span>
      </div>
    `;
  } else {
    const maxPenalty = Math.max(...deductionEntries.map(e => e[1]));
    html += `<div class="deduction-bars-list">`;
    for (const [ruleId, penalty] of deductionEntries) {
      const barPct = Math.round((penalty / maxPenalty) * 100);
      html += `
        <div class="deduction-row">
          <div class="deduction-label">
            <span class="deduction-rule">${escapeHtml(ruleId)}</span>
            <span class="deduction-penalty">-${penalty} pts</span>
          </div>
          <div class="deduction-track">
            <div class="deduction-fill" style="width: ${barPct}%;"></div>
          </div>
        </div>
      `;
    }
    html += `</div>`;
  }

  html += `</div>`;
  container.innerHTML = html;

  const resetBtn = document.getElementById("btn-score-baseline");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      setBaseline(snapshotScore(scoreObj, currentDiagnostics));
      renderScore(scoreObj, projectedScore);
    });
  }
}

// ---------------------------------------------------------------------------
// Before / after comparison. The baseline is the score when the user started fixing:
// taken on the first successful run, and again after Upload, Reset, or the
// "Start new comparison" button. Fixes applied from Recommendations and manual edits
// both count, so the "Now" column shows the total effect of everything changed since.
// ---------------------------------------------------------------------------

// Kept per editor tab (tab.state.scoreBaseline), so each open file has its own comparison.
function getBaseline() {
  const tab = getActiveTab();
  return tab ? tab.state.scoreBaseline || null : null;
}

function setBaseline(baseline) {
  const tab = getActiveTab();
  if (tab) tab.state.scoreBaseline = baseline;
}

function snapshotScore(scoreObj, diagnostics) {
  const byRule = {};
  for (const d of diagnostics) byRule[d.rule_id] = (byRule[d.rule_id] || 0) + 1;
  return {
    value: scoreObj.value,
    grade: scoreObj.grade,
    issues: diagnostics.length,
    byRule,
    functions: currentMetrics.map(m => m.function),
    time: new Date(),
  };
}

/**
 * True when the analyzed code looks like a different program from the baseline's,
 * e.g. new code pasted over the old and Run clicked. Fixes and edits keep (almost)
 * the same functions; a different program shares few or none.
 */
function isDifferentProgram(baseline) {
  const before = new Set(baseline.functions || []);
  const now = new Set(currentMetrics.map(m => m.function));
  if (before.size === 0 && now.size === 0) return false;
  const shared = [...now].filter(f => before.has(f)).length;
  return shared / Math.max(before.size, now.size) < 0.5;
}

/** Forget the baseline; the next successful run becomes the new "before". */
export function resetScoreBaseline() {
  setBaseline(null);
}

function scoreColor(score) {
  if (score < 60) return "#f85149";
  if (score < 70) return "#db6d28";
  if (score < 80) return "#d29922";
  if (score < 90) return "#388bfd";
  return "#2ea043";
}

function renderScoreComparison(scoreObj, projectedScore) {
  if (!getBaseline() || isDifferentProgram(getBaseline())) {
    setBaseline(snapshotScore(scoreObj, currentDiagnostics));
  }
  const before = getBaseline();
  const now = scoreObj.value;
  const delta = now - before.value;
  const issueDelta = currentDiagnostics.length - before.issues;

  // Estimate for the fixes still on offer: every recommendation with an edit that
  // still matches the code. Counted once per edited line; one edit can fix more than
  // one issue (e.g. an off-by-one loop), so this errs low.
  const lines = currentSource.split("\n");
  const seen = new Set();
  let autoGain = 0;
  let autoCount = 0;
  for (const rec of currentRecommendations) {
    if (!rec.edits || rec.edits.length === 0) continue;
    const stale = rec.edits.some(e => e.expected_old && e.expected_old.length > 0 &&
      JSON.stringify(lines.slice(e.line_start - 1, e.line_end)) !== JSON.stringify(e.expected_old));
    const key = rec.edits.map(e => `${e.line_start}:${e.line_end}`).join(",");
    if (stale || seen.has(key)) continue;
    seen.add(key);
    autoGain += rec.score_gain;
    autoCount++;
  }
  const afterAll = Math.min(100, now + autoGain);
  const afterSafe = (projectedScore !== undefined) ? projectedScore : now;

  const card = (label, value, sub, extraClass = "") => `
    <div class="score-compare-card ${extraClass}">
      <span class="score-compare-label">${label}</span>
      <span class="score-compare-value" style="color: ${scoreColor(value)};">${value}<small>/100</small></span>
      <span class="score-compare-sub">${sub}</span>
    </div>`;
  const signed = (n) => (n > 0 ? `+${n}` : `${n}`);
  const deltaClass = delta > 0 ? "up" : (delta < 0 ? "down" : "same");

  let html = `
    <div class="score-compare-section">
      <div class="score-compare-header">
        <h4 class="section-title">Before vs After Fixes</h4>
        <button class="btn-ast-tool" id="btn-score-baseline" title="Use the current score as the new 'before'">Start new comparison</button>
      </div>
      <div class="score-compare-row">
        ${card("Before", before.value, `${before.issues} issues · ${escapeHtml(before.grade)}`)}
        <span class="score-compare-arrow" aria-hidden="true">&rarr;</span>
        ${card("Now", now, `${currentDiagnostics.length} issues · <span class="score-delta ${deltaClass}">${signed(delta)} pts</span>`, "current")}
        <span class="score-compare-arrow" aria-hidden="true">&rarr;</span>
        ${card(autoCount ? `After ${autoCount} remaining fix${autoCount === 1 ? "" : "es"}` : "After fixes",
               afterAll,
               autoCount ? `≈ estimate · safe fixes only: ${afterSafe}` : "no automatic fixes left", "projected")}
      </div>`;

  // Which issue types changed since the baseline
  const rules = new Set([...Object.keys(before.byRule), ...currentDiagnostics.map(d => d.rule_id)]);
  const nowByRule = {};
  for (const d of currentDiagnostics) nowByRule[d.rule_id] = (nowByRule[d.rule_id] || 0) + 1;
  const changed = [...rules]
    .map(r => ({ rule: r, before: before.byRule[r] || 0, now: nowByRule[r] || 0 }))
    .filter(r => r.before !== r.now)
    .sort((a, b) => (a.now - a.before) - (b.now - b.before));

  if (changed.length === 0) {
    html += `<p class="score-compare-hint">Apply fixes from the Recommendations tab, or edit the code and run again: the change shows up here.</p>`;
  } else {
    html += `
      <table class="score-compare-table">
        <thead><tr><th>Issue type</th><th>Before</th><th>Now</th><th>Change</th></tr></thead>
        <tbody>
          ${changed.map(r => {
            const d = r.now - r.before;
            return `<tr>
              <td><code>${escapeHtml(r.rule)}</code></td>
              <td>${r.before}</td><td>${r.now}</td>
              <td class="score-delta ${d < 0 ? "up" : "down"}">${d < 0 ? `${d} fixed` : `+${d} new`}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
      <p class="score-compare-hint">Issues ${before.issues} &rarr; ${currentDiagnostics.length} (${signed(issueDelta)}) since ${before.time.toLocaleTimeString()}.</p>`;
  }
  html += `</div>`;
  return html;
}

function renderScoreEmpty(msg) {
  const container = document.getElementById("score-container");
  if (container) {
    container.innerHTML = `<div class="empty-state"><p style="font-size:13px;">${msg}</p></div>`;
  }
}

function renderMetrics(metrics) {
  const container = document.getElementById("metrics-container");
  if (!container) return;

  if (!metrics || metrics.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p style="font-size: 13px;">No function definitions detected in source file.</p>
      </div>`;
    return;
  }

  let html = `
    <div class="metrics-wrapper">
      <div class="metrics-legend">
        <span>Limits: LOC &le; 50 &bull; Params &le; 5 &bull; Nesting &le; 4 &bull; Complexity &le; 10</span>
      </div>
      <div class="table-responsive">
        <table class="metrics-table">
          <thead>
            <tr>
              <th>Function</th>
              <th>LOC</th>
              <th>Params</th>
              <th>Max Nesting</th>
              <th>Cyclomatic Complexity</th>
            </tr>
          </thead>
          <tbody>
  `;

  for (const m of metrics) {
    const locWarn = m.loc > 50;
    const paramsWarn = m.params > 5;
    const nestingWarn = m.max_nesting > 4;
    const complexityWarn = m.cyclomatic > 10;

    html += `
      <tr>
        <td class="font-mono" style="font-weight: 600;">${escapeHtml(m.function)}</td>
        <td><span class="metric-val ${locWarn ? 'val-warn' : ''}">${m.loc}${locWarn ? ' (!)' : ''}</span></td>
        <td><span class="metric-val ${paramsWarn ? 'val-warn' : ''}">${m.params}${paramsWarn ? ' (!)' : ''}</span></td>
        <td><span class="metric-val ${nestingWarn ? 'val-warn' : ''}">${m.max_nesting}${nestingWarn ? ' (!)' : ''}</span></td>
        <td><span class="metric-val ${complexityWarn ? 'val-warn' : ''}">${m.cyclomatic}${complexityWarn ? ' (!)' : ''}</span></td>
      </tr>
    `;
  }

  html += `
          </tbody>
        </table>
      </div>
    </div>
  `;

  container.innerHTML = html;
}

function renderMetricsEmpty(msg) {
  const container = document.getElementById("metrics-container");
  if (container) {
    container.innerHTML = `<div class="empty-state"><p style="font-size:13px;">${msg}</p></div>`;
  }
}

export function renderAst(astData) {
  const container = document.getElementById("ast-container");
  if (!container) return;
  renderAstTree(container, astData);
}

function renderAstEmpty(msg) {
  const container = document.getElementById("ast-container");
  if (container) {
    container.innerHTML = `<div class="empty-state"><p style="font-size:13px;">${msg}</p></div>`;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
