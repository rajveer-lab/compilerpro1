# SCA Analyzer - Web Application Documentation

A modern, offline-capable, interactive web application for the **Static Code Quality Analyzer for C**. Inspired by clean, responsive developer IDEs like OneCompiler, this web interface provides instant semantic analysis, automated recommendations with before/after diff previews, circular code quality scoring, function-level metrics, and an interactive AST explorer.

---

## 1. Quickstart & How to Run

### 1.1 Requirements
- WSL (Ubuntu) or Linux environment.
- Python 3.10+ with `build-essential`, `flex`, `bison`, `make`.
- Compiled `cparse` binary (`build/cparse`).

### 1.2 Installation
From the project root inside your WSL shell:
```bash
# 1. Ensure C parser is built
make build

# 2. Install Python package with optional web extras (Flask)
pip install -e ".[web]"
```

### 1.3 Starting the Web Server
Launch the application using either the CLI subcommand or Python module:
```bash
# Using CLI entry point:
sca web --host 127.0.0.1 --port 8000

# Or via Python module directly:
python3 -m sca.web --host 127.0.0.1 --port 8000
```

Open your browser to:
👉 **`http://127.0.0.1:8000`**

---

## 2. Interface Layout & Features

The interface is structured as a dual-pane workspace with a draggable horizontal split divider:

### Top Navigation Bar
- **Logo & Title:** "SCA Analyzer" with a C99 language chip.
- **Upload (`.c`, `.h`):** Upload one or more source files; each opens in its own editor tab (an empty current tab is reused for the first).
- **Download:** Save the current tab's code under the tab's file name.
- **Reset:** Revert the current tab back to the default template.
- **Theme Toggle:** Switch between sleek dark mode (default) and crisp light mode (persisted in `localStorage`).
- **Run Button:** Prominent green button (`Ctrl+Enter` / `Cmd+Enter`) with active spinner while analyzing.

### Left Pane: Code Editor
- **File Tabs:** Several files open at once. `+` opens a new empty file, `×` closes a tab (the last one stays), double-click (or F2) renames. Each tab keeps its own undo history, cursor, analysis results, Score before/after comparison and selected CFG function; switching tabs shows that file's last results without re-running. Each file is analyzed on its own (contracts and calls are checked within one file). Open tabs are saved in the browser's `localStorage` and restored on reload.
- **Offline Vendored CodeMirror 5:** Full C syntax highlighting, bracket matching, and auto-indent. Zero runtime CDN dependencies.
- **Inline Gutter Markers:** Color-coded icons (`!`, `▲`, `i`) on affected lines.
- **Wavy Text Underlines:** Pinpoints exact error ranges directly in the code buffer.
- **Interactive Tooltips:** Hovering over gutter markers reveals the rule ID, message, and quick fix advice.
- **Status Bar:** Real-time line and column tracking (`Ln X, Col Y`), language tag, execution time in ms, and parser readiness.
- **Modified State Tracking:** Displays a subtle *"Results out of date"* badge when code is edited after a run.

### Right Pane: Analysis Results
1. **Output Tab (Default):**
   - Severity filter chips (**All**, **Errors**, **Warnings**, **Info**) with live issue counts.
   - Diagnostic cards detailing rule ID, location, message, and matching source line snippet.
   - Clicking any diagnostic immediately jumps and highlights that line in the editor.
   - Syntax error banner if the C parser encounters unrecoverable syntax errors.
2. **Recommendations Tab:**
   - Global banner showing score projection: *"Applying all safe fixes would raise your score from X to Y (+Z points)"*.
   - **Apply all safe fixes Button:** Applies all non-conflicting safe fixes in a single step and re-analyzes.
   - **Before/After Diff Preview:** Monospace visual diff displaying lines removed (`-`) and inserted (`+`).
   - **Apply fix Button:** Modifies the editor buffer and re-runs analysis. Reverts cleanly with `Ctrl+Z`.
   - **Stale Detection:** If code is changed in the editor, out-of-date fix buttons are automatically disabled with *"Stale (code changed)"*.
3. **Contracts Tab:**
   - One card per function that needs safe inputs: the inferred contract (e.g. `0 <= n <= 4`)
     and the line that needs it ("because it indexes 'a[n]' (5 elements) at line 6").
   - **Insert as comment** adds `/* sca: requires ... */` above the function (or updates it).
   - Functions with no input constraints are listed at the bottom.
4. **Learning Tab:**
   - Misconception cards for the current code: the wrong belief, the correct mental model,
     the fix, and the lines involved. Output cards also name their misconception.
   - **Your profile:** distinct mistakes per misconception across runs, stored only in this
     browser (`localStorage`), with a Reset button.
5. **Score Tab:**
   - **Animated Circular SVG Gauge:** Displays score (0–100) and letter grade with color transitions (A green, B blue, C amber, D orange, F red).
   - **Deductions Breakdown:** Horizontal progress bars displaying penalties deducted by each rule, sorted by impact.
6. **Metrics Tab:**
   - Per-function summary table: Function Name, Lines of Code (LOC), Parameter count, Max Nesting Depth, and Cyclomatic Complexity.
   - Highlighted warning pills when metrics exceed established thresholds (LOC > 50, Params > 5, Nesting > 4, Complexity > 10).
7. **AST Tab:**
   - Collapsible hierarchical tree view of the JSON AST.
   - "Expand All" and "Collapse All" controls.
   - Clickable line:col tags on nodes that navigate and highlight that construct in the code editor.
8. **CFG Tab:**
   - Drawn automatically on every Run for every function in the editor; one button per function.
   - Each block shows its source lines; empty join blocks are folded away.
   - Branch edges are marked **T** (green) / **F** (red), loop back edges are dashed blue, and
     unreachable blocks are drawn dashed amber.
   - Header shows block count, edge count and cyclomatic complexity (E − N + 2).
   - Clicking a block jumps to its first line in the editor.

---

## 3. Web API Reference

All JSON endpoints return responses following the standard schema:
- Success: `{"ok": true, ...}`
- Error: `{"ok": false, "error": {"code": "...", "message": "..."}}` with HTTP status 400, 404, 413, or 500.

### `GET /api/health`
Checks health status and verifies that the `cparse` binary exists and is executable.
- **Response (200):**
  ```json
  {
    "ok": true,
    "status": "healthy",
    "cparse": {
      "found": true,
      "path": "build/cparse"
    }
  }
  ```

### `GET /api/rules`
Lists all 22 registered analysis rules.
- **Response (200):**
  ```json
  {
    "ok": true,
    "rules": [
      {
        "id": "unused-variable",
        "name": "Unused Variable",
        "default_severity": "warning",
        "description": "Local variable declared but never read.",
        "tier": 2
      }
    ]
  }
  ```

### `GET /api/examples` & `GET /api/examples/<name>`
- `GET /api/examples`: Returns an array of example identifiers and descriptions.
- `GET /api/examples/<name>`: Returns the code for a specific example program. Path traversal (`..`) is strictly blocked (returns 400).

### `POST /api/analyze`
Analyzes C source code string and returns complete analysis results.
- **Headers:** `Content-Type: application/json`
- **Request Body:**
  ```json
  {
    "code": "int main() { int x; return 0; }",
    "disabled_rules": ["magic-number"],
    "filename": "main.c"
  }
  ```
- **Response (200):**
  ```json
  {
    "ok": true,
    "parse_errors": [],
    "diagnostics": [
      {
        "file": "main.c",
        "line": 1,
        "col": 14,
        "end_line": 1,
        "end_col": 18,
        "message": "Local variable 'x' is declared but never read.",
        "rule_id": "unused-variable",
        "severity": "warning"
      }
    ],
    "summary": { "error": 0, "warning": 1, "info": 0 },
    "metrics": [
      { "function": "main", "loc": 1, "params": 0, "max_nesting": 0, "cyclomatic": 1 }
    ],
    "score": {
      "value": 98,
      "grade": "A (Excellent)",
      "total_issues": 1,
      "deductions": { "unused-variable": 2 }
    },
    "recommendations": [
      {
        "id": "rec-1",
        "rule_id": "unused-variable",
        "line": 1,
        "col": 14,
        "title": "Remove unused variable 'x'",
        "explanation": "Variable 'x' is declared but never read, so it adds clutter.",
        "priority": 2,
        "score_gain": 2,
        "safety": "safe",
        "edits": [
          { "line_start": 1, "line_end": 1, "expected_old": ["int main() { int x; return 0; }"], "new": [] }
        ]
      }
    ],
    "projected_score": 100,
    "elapsed_ms": 14.5
  }
  ```
- **Error Responses:**
  - `400 Bad Request`: Invalid JSON body or missing `code` string.
  - `413 Payload Too Large`: Code exceeds the 100 KB limit.

### `POST /api/ast`
Generates the JSON AST from `cparse` for the supplied C code.
- **Request Body:** `{"code": "..."}`
- **Response (200):** `{"ok": true, "ast": { "schema_version": 1, "unit": { ... } }}`

`/api/analyze` responses also include `"contracts"` (per function: `function`, `line`,
`contracts: [{param, text, allowed, reasons}]`, `complete`) and `"misconceptions"`
(`id`, `title`, `explanation`, `fix`, `lines`, `rule_ids`); diagnostics that map to a
misconception carry its `"misconception"` id.

### `POST /api/cfg`
Returns basic blocks and directional edges for one function, or for every function when
`function` is omitted.
- **Request Body:** `{"code": "...", "function": "main"}` or `{"code": "..."}`
- **Response (200), one function:** `{"ok": true, "function": "main", "line": 1, "blocks": [...], "edges": [...]}`
- **Response (200), all functions:** `{"ok": true, "functions": [{"function": "main", "line": 1, "blocks": [...], "edges": [...]}, ...]}`
- Each block: `{"id", "label", "statements": ["int x = 0;", "if (x > 3)"], "statements_count", "line", "end_line", "is_entry", "is_exit", "reachable"}`.
- Each edge: `{"from", "to", "kind"}` where `kind` is `"true"`, `"false"` (branch edges) or `"normal"`.

---

## 4. Security & Isolation Controls

1. **Static Analysis Only:** The server never compiles, links, or executes user code. Code is only parsed into an AST using `cparse`.
2. **Payload Size Enforcement:** Request bodies are strictly capped at 100 KB (`MAX_CONTENT_LENGTH = 100 * 1024`). Payloads exceeding this are rejected with HTTP 413.
3. **Isolated Temporary Files:** `cparse` invocations write to unique private directories created via `tempfile.mkdtemp()`. A `try...finally` block guarantees full directory cleanup after each request, even if errors occur.
4. **Execution Security:** Subprocesses are invoked with explicit argument lists (`no shell=True`) and enforced with a 10-second timeout.
5. **No Information Leaks:** Server errors (HTTP 500) return sanitized JSON error messages and never leak server directory paths, usernames, or stack traces.
6. **Local Binding:** The application binds to `127.0.0.1` by default without CORS or telemetry.

---

## 5. Manual QA Checklist

- [x] **Clean Example Analysis:** Load `clean.c` -> click Run -> Score is 100/100 (Grade A), 0 diagnostics, metrics table shows LOC 4, cyclomatic 1.
- [x] **Smelly Example Analysis:** Load `smelly.c` -> click Run -> Reports `unused-variable`, score 98/100, Projected Score 100/100.
- [x] **Apply Single Fix:** In Recommendations tab for `smelly.c`, click "Apply fix" -> `int x;` is removed from editor, analysis automatically re-runs, and score rises to 100/100.
- [x] **Undo Support:** Press `Ctrl+Z` / `Cmd+Z` in the editor -> code reverts to having `int x;`.
- [x] **Apply All Safe Fixes:** Load code with multiple safe issues -> click "Apply all safe fixes" -> all safe edits are applied and score updates.
- [x] **Stale Detection:** Manually edit a line with a pending recommendation -> the "Apply fix" button is disabled and indicates stale state.
- [x] **Theme Persistence:** Click theme toggle (☀️/🌙) -> background shifts cleanly between dark and light -> reload page -> theme remains preserved.
- [x] **Split Pane Resizing:** Drag the divider bar `#resizer` left and right -> reload page -> split ratio is preserved.
- [x] **AST Tree Exploration:** Switch to AST tab -> expand/collapse nodes -> click a line:col badge -> editor scrolls to and flashes that code construct.
- [x] **Responsive Layout:** Shrink viewport below 768px -> editor and results panes stack vertically; all buttons remain accessible.
- [x] **Keyboard Navigation:** Tab through all controls -> visible focus rings appear; `Ctrl+Enter` triggers analysis.
