/**
 * Contracts tab: the input ranges each function is proven safe for
 * (inferred by sca/analysis/contracts.py), with "Insert as comment".
 */

import { jumpToLine } from "./editor.js";

const COMMENT_PREFIX = "/* sca: requires";

/**
 * @param {Array} contracts  result.contracts from /api/analyze
 * @param {string} source    the analyzed code
 * @param {Function} onInsertComment  called with an edit list to apply
 */
export function renderContracts(contracts, source, onInsertComment) {
  const container = document.getElementById("contracts-container");
  const badge = document.getElementById("badge-contracts");
  if (!container) return;

  const withContracts = (contracts || []).filter(fc => fc.contracts.length > 0);
  const without = (contracts || []).filter(fc => fc.contracts.length === 0);
  if (badge) badge.textContent = withContracts.length;

  if (contracts === null) {
    container.innerHTML = `
      <div class="empty-state">
        <p style="font-size: 13px;">Contracts unavailable due to syntax errors.</p>
      </div>`;
    return;
  }
  if (contracts.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <h3 style="font-weight: 600;">Input Contracts</h3>
        <p style="font-size: 13px; max-width: 380px;">No function definitions found. Contracts appear here after running analysis.</p>
      </div>`;
    return;
  }

  const lines = source.split("\n");
  let html = `
    <p class="contracts-intro">
      Input ranges each function is <strong>proven safe</strong> for, inferred by interval analysis.
      Calls in this file that break a contract are reported as <code>contract-violation</code>.
    </p>`;

  if (withContracts.length === 0) {
    html += `<div class="empty-state" style="height: 140px;">
      <p style="font-size: 13px;">No function needs a restriction on its inputs: every parameter value is safe.</p>
    </div>`;
  }

  html += `<div class="contracts-list">`;
  for (const fc of withContracts) {
    const requires = fc.contracts.map(c => c.text).join(" && ");
    const comment = `${COMMENT_PREFIX} ${requires} */`;
    const defLine = lines[fc.line - 1] || "";
    const prevLine = (lines[fc.line - 2] || "").trim();
    const present = prevLine === comment;
    html += `
      <div class="contract-card" data-line="${fc.line}">
        <div class="contract-header">
          <span class="contract-func">${escapeHtml(fc.function)}()</span>
          <span class="diag-loc">Ln ${fc.line}</span>
        </div>
        <div class="contract-requires"><span class="contract-kw">requires</span> ${fc.contracts
          .map(c => `<code class="contract-chip">${escapeHtml(c.text)}</code>`).join(" <span class='contract-kw'>and</span> ")}</div>
        <ul class="contract-reasons">
          ${fc.contracts.flatMap(c => c.reasons.map(r =>
            `<li><code>${escapeHtml(c.param)}</code>: because it ${escapeHtml(r)}</li>`)).join("")}
        </ul>
        <div class="rec-card-actions">
          <button class="btn-apply-fix btn-insert-contract" data-line="${fc.line}" ${present ? "disabled" : ""}
            data-comment="${escapeHtml(comment)}" data-indent="${escapeHtml(defLine.match(/^\s*/)[0])}">
            ${present ? "Comment inserted" : "Insert as comment"}
          </button>
        </div>
      </div>`;
  }
  html += `</div>`;

  if (without.length > 0) {
    html += `<p class="contracts-none">No input constraints needed: ${without
      .map(fc => `<a href="#" class="contract-jump" data-line="${fc.line}">${escapeHtml(fc.function)}()</a>`)
      .join(", ")}${without.some(fc => !fc.complete) ? " (search stopped early on a large file)" : ""}</p>`;
  }
  container.innerHTML = html;

  container.querySelectorAll(".contract-card").forEach(card => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      jumpToLine(parseInt(card.getAttribute("data-line"), 10), 1);
    });
  });
  container.querySelectorAll(".contract-jump").forEach(a => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      jumpToLine(parseInt(a.getAttribute("data-line"), 10), 1);
    });
  });
  container.querySelectorAll(".btn-insert-contract").forEach(btn => {
    btn.addEventListener("click", () => {
      const line = parseInt(btn.getAttribute("data-line"), 10);
      const text = btn.getAttribute("data-indent") + btn.getAttribute("data-comment");
      const prev = lines[line - 2];
      // Replace an older sca contract comment right above the function, else insert one.
      const edit = (prev !== undefined && prev.trim().startsWith(COMMENT_PREFIX))
        ? { line_start: line - 1, line_end: line - 1, expected_old: [prev], new: [text] }
        : { line_start: line, line_end: line - 1, expected_old: [], new: [text] };
      onInsertComment([edit]);
    });
  });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
