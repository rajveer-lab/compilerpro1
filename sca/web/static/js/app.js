/**
 * Main application coordinator for SCA Analyzer Web UI.
 */

import { initTheme } from "./theme.js";
import {
  initEditor, getCode, setCode, resetCode, setDiagnosticsMarkers, clearMarkers,
  getActiveTab, onTabsChanged, openTab, renameTab,
} from "./editor.js";
import { initTabStrip } from "./tabs.js";
import { initPanels, renderResults, renderAst, resetScoreBaseline } from "./panels.js";
import { renderCfg } from "./cfg_viewer.js";
import { renderContracts } from "./contracts.js";
import { renderLearning } from "./learning.js";
import { analyzeCode, fetchAst, fetchCfg } from "./api.js";

let isRunning = false;
let liveAnalysisTimer = null;

document.addEventListener("DOMContentLoaded", async () => {
  // 1. Initialize Themes
  initTheme();

  // 2. Initialize Panels & Tabs with Fix Handlers
  initPanels(handleApplyFix, handleApplyAllSafe);

  // 3. Initialize CodeMirror Editor and its file tabs
  initEditor(handleRun, handleCodeChange);
  initTabStrip();
  onTabsChanged(handleTabsChanged);

  // 4. Initialize Split Pane Resizer
  initSplitPane();

  // 5. Initialize Top Bar Controls
  initTopBarControls();

  // 6. Initial Run
  handleRun();
});

export async function handleRun() {
  if (isRunning) return;
  const runBtn = document.getElementById("btn-run");
  const parserStatus = document.getElementById("parser-status");

  // Results belong to the tab that was active when the run started, even if the user
  // switches tabs while it is in flight.
  const tab = getActiveTab();
  const code = getCode();
  if (!code.trim()) {
    tab.state.run = null;
    showEmptyFile();
    return;
  }

  isRunning = true;
  if (runBtn) {
    runBtn.classList.add("loading");
    runBtn.disabled = true;
  }
  if (parserStatus) parserStatus.textContent = "Analyzing...";

  try {
    const [result, astResult, cfgResult] = await Promise.all([
      analyzeCode(code, [], tab.name),
      fetchAst(code).catch(() => null),
      fetchCfg(code).catch(() => null)
    ]);
    tab.state.run = { result, astResult, cfgResult, code };
    if (getActiveTab() === tab) renderRun(tab.state.run);
  } catch (err) {
    if (parserStatus) {
      parserStatus.textContent = "Error";
      parserStatus.style.color = "var(--severity-error)";
    }
    showErrorBanner(err.message || "Failed to analyze code");
  } finally {
    isRunning = false;
    if (runBtn) {
      runBtn.classList.remove("loading");
      runBtn.disabled = false;
    }
    // The user switched to a tab that has not been analyzed yet while this ran.
    const now = getActiveTab();
    if (now && now !== tab && !now.state.run) handleRun();
  }
}

/** Show one tab's stored results in the editor and every results panel. */
function renderRun(run) {
  const { result, astResult, cfgResult, code } = run;
  const parserStatus = document.getElementById("parser-status");
  const timeElapsed = document.getElementById("time-elapsed");

  // Update status bar
  if (timeElapsed) timeElapsed.textContent = `${result.elapsed_ms || 0} ms`;
  if (parserStatus) {
    if (result.parse_errors && result.parse_errors.length > 0) {
      parserStatus.textContent = "Syntax Error";
      parserStatus.style.color = "var(--severity-error)";
    } else {
      parserStatus.textContent = "Ready";
      parserStatus.style.color = "var(--text-secondary)";
    }
  }

  // Set editor inline markers and gutter badges
  setDiagnosticsMarkers(result.diagnostics || [], result.recommendations || []);

  // Render results panels
  renderResults(result, code);
  // null tells both tabs the code did not parse
  const parsed = !(result.parse_errors && result.parse_errors.length > 0);
  renderContracts(parsed ? (result.contracts || []) : null, code, handleApplyAllSafe);
  renderLearning(parsed ? (result.misconceptions || []) : null, code);

  // Render AST tree
  if (astResult && astResult.ok && astResult.ast) {
    renderAst(astResult.ast);
  }

  // Render control flow graphs for every function
  renderCfg(cfgResult);

  // The tab's code may have been edited since these results were computed.
  const staleBadge = document.getElementById("stale-badge");
  if (staleBadge) staleBadge.style.display = getCode() !== code ? "inline-block" : "none";
}

/** Results panels for a tab with no code in it. */
function showEmptyFile() {
  clearMarkers();
  const message = `
    <div class="empty-state">
      <h3 style="font-weight: 600;">Empty File</h3>
      <p style="font-size: 13px;">Write or paste C code in this tab, then click <strong>Run</strong>.</p>
    </div>`;
  for (const id of ["output-diagnostics-container", "recommendations-container", "contracts-container",
                    "learning-container", "score-container", "metrics-container", "ast-container",
                    "cfg-container"]) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = message;
  }
  for (const id of ["badge-output", "badge-recommendations", "badge-contracts", "badge-learning"]) {
    const el = document.getElementById(id);
    if (el) el.textContent = "0";
  }
  const parserStatus = document.getElementById("parser-status");
  if (parserStatus) {
    parserStatus.textContent = "Ready";
    parserStatus.style.color = "var(--text-secondary)";
  }
}

/** Another tab became active: show its results, analyzing it first if it never was. */
function handleTabsChanged(switched) {
  if (!switched) return;
  if (liveAnalysisTimer) clearTimeout(liveAnalysisTimer);
  const tab = getActiveTab();
  if (tab && tab.state.run) {
    renderRun(tab.state.run);
  } else {
    handleRun();
  }
}

function handleCodeChange() {
  const liveToggle = document.getElementById("toggle-live-analysis");
  if (liveToggle && liveToggle.checked) {
    if (liveAnalysisTimer) clearTimeout(liveAnalysisTimer);
    liveAnalysisTimer = setTimeout(() => {
      handleRun();
    }, 800);
  }
}

function handleApplyFix(rec) {
  if (!rec.edits || rec.edits.length === 0) return;
  try {
    const currentCode = getCode();
    const newCode = applyClientEdits(currentCode, rec.edits);
    setCode(newCode);
    handleRun();
  } catch (err) {
    showErrorBanner(`Cannot apply fix: ${err.message}`);
  }
}

function handleApplyAllSafe(edits) {
  if (!edits || edits.length === 0) return;
  try {
    const currentCode = getCode();
    const newCode = applyClientEdits(currentCode, edits);
    setCode(newCode);
    handleRun();
  } catch (err) {
    showErrorBanner(`Cannot apply all safe fixes: ${err.message}`);
  }
}

function applyClientEdits(source, edits) {
  const lines = source.split("\n");
  const normEdits = [...edits].sort((a, b) => b.line_start - a.line_start);

  for (const edit of normEdits) {
    const lineStart = edit.line_start;
    const lineEnd = edit.line_end;
    const expectedOld = edit.expected_old || [];
    const newLines = edit.new || [];

    if (expectedOld.length > 0) {
      const actualOld = lines.slice(lineStart - 1, lineEnd);
      if (JSON.stringify(actualOld) !== JSON.stringify(expectedOld)) {
        throw new Error(`Lines ${lineStart}..${lineEnd} have changed since analysis.`);
      }
    }

    if (lineEnd === lineStart - 1) {
      lines.splice(lineStart - 1, 0, ...newLines);
    } else {
      lines.splice(lineStart - 1, lineEnd - lineStart + 1, ...newLines);
    }
  }

  return lines.join("\n");
}

function initSplitPane() {
  const resizer = document.getElementById("resizer");
  const paneLeft = document.getElementById("pane-editor");
  const paneRight = document.getElementById("pane-results");
  const workspace = document.querySelector(".workspace");

  if (!resizer || !paneLeft || !paneRight || !workspace) return;

  try {
    const savedFlex = localStorage.getItem("sca_split_ratio");
    if (savedFlex) {
      const [leftFlex, rightFlex] = savedFlex.split(":");
      paneLeft.style.flex = leftFlex;
      paneRight.style.flex = rightFlex;
    }
  } catch (e) {}

  let isDragging = false;

  resizer.addEventListener("mousedown", (e) => {
    isDragging = true;
    resizer.classList.add("dragging");
    document.body.style.cursor = "col-resize";
    e.preventDefault();
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const bounds = workspace.getBoundingClientRect();
    const offsetX = e.clientX - bounds.left;
    const totalWidth = bounds.width;

    if (offsetX > 200 && (totalWidth - offsetX) > 200) {
      const leftRatio = (offsetX / totalWidth).toFixed(4);
      const rightRatio = (1 - leftRatio).toFixed(4);
      paneLeft.style.flex = leftRatio;
      paneRight.style.flex = rightRatio;

      try {
        localStorage.setItem("sca_split_ratio", `${leftRatio}:${rightRatio}`);
      } catch (err) {}
    }
  });

  window.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      resizer.classList.remove("dragging");
      document.body.style.cursor = "";
    }
  });
}

function initTopBarControls() {
  const runBtn = document.getElementById("btn-run");
  if (runBtn) {
    runBtn.addEventListener("click", handleRun);
  }

  const uploadBtn = document.getElementById("btn-upload");
  const fileInput = document.getElementById("file-upload-input");
  if (uploadBtn && fileInput) {
    uploadBtn.addEventListener("click", () => fileInput.click());
    // Every chosen file opens in its own tab; an empty current tab is reused for the first.
    fileInput.addEventListener("change", async (e) => {
      const files = [...e.target.files];
      fileInput.value = "";
      for (const file of files) {
        let text;
        try {
          text = await file.text();
        } catch (err) {
          showErrorBanner(`Could not read '${file.name}'`);
          continue;
        }
        const current = getActiveTab();
        if (current && !getCode().trim()) {
          renameTab(current.id, file.name);
          current.state = {};   // new file: no old results or before/after comparison
          setCode(text);
          handleRun();
        } else {
          openTab(file.name, text);
        }
      }
    });
  }

  const downloadBtn = document.getElementById("btn-download");
  if (downloadBtn) {
    downloadBtn.addEventListener("click", () => {
      const code = getCode();
      const blob = new Blob([code], { type: "text/x-csrc" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = (getActiveTab() && getActiveTab().name) || "main.c";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  }

  const resetBtn = document.getElementById("btn-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      const name = (getActiveTab() && getActiveTab().name) || "this file";
      if (confirm(`Reset "${name}" to the default template? Its current code will be lost.`)) {
        resetScoreBaseline();
        resetCode();
        handleRun();
      }
    });
  }
}

function showErrorBanner(message) {
  let banner = document.getElementById("error-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "error-banner";
    banner.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #cf222e;
      color: #fff;
      padding: 12px 18px;
      border-radius: 6px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      z-index: 9999;
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 12px;
    `;
    document.body.appendChild(banner);
  }
  banner.innerHTML = `<span>${message}</span> <button style="background:transparent; border:none; color:#fff; font-size:16px; cursor:pointer;" onclick="this.parentElement.remove()">&times;</button>`;
  setTimeout(() => {
    if (banner && banner.parentElement) banner.remove();
  }, 5000);
}
