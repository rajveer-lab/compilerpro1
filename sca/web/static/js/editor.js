/**
 * CodeMirror 5 Editor Integration Module with Inline Markers and Gutter Tooltips.
 */

let editor = null;
let currentMarks = [];
let tooltipEl = null;

const STORAGE_CODE_KEY = "sca_editor_code";   // single-file format, migrated on load
const STORAGE_TABS_KEY = "sca_editor_tabs";   // { tabs: [{name, code}], active }
const DEFAULT_CODE = `int main() {
    int x;
    return 0;
}
`;

// ---------------------------------------------------------------------------
// Tabs: one CodeMirror Doc per open file (keeps its own undo history and cursor),
// plus a free-form `state` object where the app keeps that file's last results.
// ---------------------------------------------------------------------------

let tabs = [];          // { id, name, doc, state }
let activeId = null;
let nextTabId = 1;
const tabListeners = [];

function makeTab(name, code) {
  return {
    id: nextTabId++,
    name,
    doc: window.CodeMirror.Doc(code, "text/x-csrc"),
    state: {},
  };
}

function loadSavedTabs() {
  try {
    const raw = localStorage.getItem(STORAGE_TABS_KEY);
    const data = raw ? JSON.parse(raw) : null;
    if (data && Array.isArray(data.tabs) && data.tabs.length > 0) {
      return {
        tabs: data.tabs.filter(t => typeof t.name === "string" && typeof t.code === "string"),
        active: data.active || 0,
      };
    }
    const single = localStorage.getItem(STORAGE_CODE_KEY);
    if (single !== null && single.trim()) {
      return { tabs: [{ name: "main.c", code: single }], active: 0 };
    }
  } catch (e) {}
  return { tabs: [{ name: "main.c", code: DEFAULT_CODE }], active: 0 };
}

function saveTabs() {
  try {
    localStorage.setItem(STORAGE_TABS_KEY, JSON.stringify({
      tabs: tabs.map(t => ({ name: t.name, code: t.doc.getValue() })),
      active: Math.max(0, tabs.findIndex(t => t.id === activeId)),
    }));
  } catch (e) {}
}

function notifyTabs(switched) {
  saveTabs();
  for (const fn of tabListeners) fn(switched);
}

/** fn(switched) runs after any tab change; switched is true when the active tab changed. */
export function onTabsChanged(fn) {
  tabListeners.push(fn);
}

export function getTabs() {
  return tabs;
}

export function getActiveTab() {
  return tabs.find(t => t.id === activeId) || null;
}

/** "name.c", or "name (2).c" etc. if that name is already open (ignoring tab `exceptId`). */
export function uniqueTabName(name, exceptId = null) {
  const taken = new Set(tabs.filter(t => t.id !== exceptId).map(t => t.name));
  if (!taken.has(name)) return name;
  const dot = name.lastIndexOf(".");
  const base = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : "";
  for (let i = 2; ; i++) {
    const candidate = `${base} (${i})${ext}`;
    if (!taken.has(candidate)) return candidate;
  }
}

export function switchToTab(id) {
  const tab = tabs.find(t => t.id === id);
  if (!tab || !editor || id === activeId) return;
  clearMarkers();               // markers belong to the outgoing document
  activeId = id;
  editor.swapDoc(tab.doc);
  editor.focus();
  notifyTabs(true);
}

/** Open a new tab with this code and make it active; returns it. */
export function openTab(name, code) {
  const tab = makeTab(uniqueTabName(name), code);
  tabs.push(tab);
  switchToTab(tab.id);
  return tab;
}

export function newUntitledTab() {
  let n = 1;
  while (tabs.some(t => t.name === `untitled-${n}.c`)) n++;
  return openTab(`untitled-${n}.c`, "");
}

/** Close a tab (the last one stays open). Returns false if it was not closed. */
export function closeTab(id) {
  if (tabs.length <= 1) return false;
  const idx = tabs.findIndex(t => t.id === id);
  if (idx < 0) return false;
  const wasActive = id === activeId;
  tabs.splice(idx, 1);
  if (wasActive) {
    switchToTab(tabs[Math.min(idx, tabs.length - 1)].id);
  } else {
    notifyTabs(false);
  }
  return true;
}

/** Rename a tab; returns the name actually used (made unique, .c added if missing). */
export function renameTab(id, rawName) {
  const tab = tabs.find(t => t.id === id);
  if (!tab) return null;
  let name = (rawName || "").trim().replace(/[\\/]/g, "");
  if (!name) return tab.name;
  if (!/\.[ch]$/.test(name)) name += ".c";
  tab.name = uniqueTabName(name, id);
  notifyTabs(false);
  return tab.name;
}

export function initEditor(onRunRequested, onCodeChanged) {
  const textarea = document.getElementById("code-editor");

  const saved = loadSavedTabs();
  tabs = saved.tabs.map(t => makeTab(t.name, t.code));
  const first = tabs[Math.min(saved.active, tabs.length - 1)];
  activeId = first.id;
  textarea.value = "";

  // Initialize CodeMirror 5
  editor = window.CodeMirror.fromTextArea(textarea, {
    mode: "text/x-csrc",
    lineNumbers: true,
    matchBrackets: true,
    autoCloseBrackets: true,
    gutters: ["CodeMirror-linenumbers", "sca-gutter-markers"],
    tabSize: 4,
    indentUnit: 4,
    indentWithTabs: false,
    lineWrapping: false,
    extraKeys: {
      "Ctrl-Enter": () => onRunRequested && onRunRequested(),
      "Cmd-Enter": () => onRunRequested && onRunRequested(),
    },
  });
  editor.swapDoc(first.doc);

  // Cursor activity tracking
  editor.on("cursorActivity", () => {
    const cursor = editor.getCursor();
    const posEl = document.getElementById("cursor-pos");
    if (posEl) {
      posEl.textContent = `Ln ${cursor.line + 1}, Col ${cursor.ch + 1}`;
    }
  });

  // Code modification listener
  editor.on("change", () => {
    saveTabs();

    // Show stale results badge if markers were active
    if (currentMarks.length > 0) {
      const staleBadge = document.getElementById("stale-badge");
      if (staleBadge) staleBadge.style.display = "inline-block";
    }

    if (onCodeChanged) onCodeChanged();
  });

  // Tooltip element
  tooltipEl = document.createElement("div");
  tooltipEl.className = "sca-tooltip";
  document.body.appendChild(tooltipEl);

  return editor;
}

export function getCode() {
  return editor ? editor.getValue() : "";
}

export function setCode(newCode) {
  if (editor) {
    editor.setValue(newCode);
    clearMarkers();
  }
}

export function resetCode() {
  setCode(DEFAULT_CODE);
}

export function clearMarkers() {
  if (!editor) return;

  // Clear text marks
  currentMarks.forEach(m => m.clear());
  currentMarks = [];

  // Clear gutter markers
  editor.clearGutter("sca-gutter-markers");

  const staleBadge = document.getElementById("stale-badge");
  if (staleBadge) staleBadge.style.display = "none";
}

export function setDiagnosticsMarkers(diagnostics, recommendations = []) {
  if (!editor) return;
  clearMarkers();

  // Create lookup for recommendations by line and rule_id
  const recLookup = {};
  for (const r of recommendations) {
    const key = `${r.line}:${r.rule_id}`;
    recLookup[key] = r;
  }

  // Group diagnostics by line for gutter markers
  const lineDiags = {};

  for (const d of diagnostics) {
    const line = d.line;
    if (!lineDiags[line]) lineDiags[line] = [];
    lineDiags[line].push(d);

    // Add wavy underline mark
    const startLine = Math.max(0, d.line - 1);
    const startCol = Math.max(0, (d.col || 1) - 1);
    const endLine = Math.max(0, (d.end_line || d.line) - 1);
    const endCol = Math.max(startCol + 1, (d.end_col || startCol + 4));

    const markClass = `sca-mark-${d.severity || "warning"}`;
    try {
      const mark = editor.markText(
        { line: startLine, ch: startCol },
        { line: endLine, ch: endCol },
        { className: markClass }
      );
      currentMarks.push(mark);
    } catch (e) {}
  }

  // Add gutter markers
  for (const [lineStr, diags] of Object.entries(lineDiags)) {
    const lineNum = parseInt(lineStr, 10);
    const primaryDiag = diags[0];
    const severity = primaryDiag.severity || "warning";

    const marker = document.createElement("div");
    marker.className = `sca-gutter-marker marker-${severity}`;
    marker.textContent = severity === "error" ? "!" : (severity === "warning" ? "▲" : "i");

    // Tooltip data
    const rec = recLookup[`${lineNum}:${primaryDiag.rule_id}`];
    const tooltipText = `<strong>[${primaryDiag.rule_id}]</strong> ${primaryDiag.message}` +
      (rec && rec.title ? `<br><em style="color:#58a6ff;">💡 Fix: ${rec.title}</em>` : "");

    marker.addEventListener("mouseenter", (e) => {
      showTooltip(e, tooltipText);
    });
    marker.addEventListener("mouseleave", hideTooltip);
    marker.addEventListener("click", () => {
      jumpToLine(lineNum, primaryDiag.col || 1);
    });

    editor.setGutterMarker(lineNum - 1, "sca-gutter-markers", marker);
  }
}

export function jumpToLine(line, col = 1) {
  if (!editor) return;
  const lineIdx = Math.max(0, line - 1);
  const colIdx = Math.max(0, col - 1);

  editor.scrollIntoView({ line: lineIdx, ch: colIdx }, 100);
  editor.setCursor({ line: lineIdx, ch: colIdx });
  editor.focus();

  // Highlight flash effect
  const lineHandle = editor.addLineClass(lineIdx, "background", "sca-highlight-flash");
  setTimeout(() => {
    editor.removeLineClass(lineHandle, "background", "sca-highlight-flash");
  }, 900);
}

function showTooltip(event, htmlContent) {
  if (!tooltipEl) return;
  tooltipEl.innerHTML = htmlContent;
  const rect = event.target.getBoundingClientRect();
  tooltipEl.style.left = `${rect.right + 8}px`;
  tooltipEl.style.top = `${rect.top - 4}px`;
  tooltipEl.classList.add("visible");
}

function hideTooltip() {
  if (tooltipEl) {
    tooltipEl.classList.remove("visible");
  }
}
