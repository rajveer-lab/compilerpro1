# Phase W0: Discovery and Architecture Notes

## 1. Codebase Inspection & Baseline Analysis

### 1.1 Architecture Overview
- **Parsing Engine (`cparse`)**: High-performance C executable built with Flex (`cparse/lexer.l`) and Bison (`cparse/parser.y`). Outputs a structured JSON AST adhering to `docs/AST_SCHEMA.md`. Includes line directives, typedef tracking, and error recovery.
- **Python Driver & AST (`sca`)**:
  - `sca/frontend/runner.py`: Locates `build/cparse` (or `$SCA_CPARSE`) and executes subprocess calls (`run_cparse`, `run_cparse_tokens`) with a 10s timeout.
  - `sca/frontend/loader.py`: Transforms raw JSON AST from `cparse` into strongly typed Python dataclasses (`sca/ast/nodes.py`).
  - `sca/analysis/cfg.py`: Builds Control Flow Graphs from `FunctionDef` nodes, breaking AST blocks into basic blocks (`BasicBlock`) and directional edges.
  - `sca/analysis/dataflow.py` & `sca/analysis/liveness.py`: Generic forward/backward dataflow frameworks and live-variable analysis.
  - `sca/rules/`: 18 rule implementations across `ast_rules.py`, `unused.py`, `uninitialized.py`, `phase7.py`, `dataflow_rules.py`, and `cfg_rules.py`.
  - `sca/cli.py`: CLI driver handling subcommands: `tokens`, `parse`, `cfg`, `liveness`, `score`, and `analyze`.

### 1.2 Identified Issues and Discrepancies
1. **Rule ID Discrepancy (`uninitialized` vs `uninitialized-variable`)**:
   - `sca/rules/uninitialized.py` reports `rule_id="uninitialized"`.
   - `docs/RULES.md` and `WEB_KICKOFF_PROMPT.md` specify `uninitialized-variable`.
   - The CLI weights dictionary in `cli.py` had `"uninitialized": 10`. If any tool or future configuration refers to `uninitialized-variable`, it would fall back to the default weight (2).
   - **Resolution**: In `sca/scoring.py`, provide both `"uninitialized": 10` and `"uninitialized-variable": 10` so any lookup returns 10. Also add a test ensuring every registered rule ID is present in the weights table.
2. **Missing `sca metrics` Subcommand in CLI**:
   - Specified as FR7 in `docs/SPEC.md` and required by `WEB_KICKOFF_PROMPT.md`.
   - AST rules already calculate LOC, nesting, parameter counts, and CFG cyclomatic complexity, but no standalone `sca metrics` CLI parser existed.
   - **Resolution**: Implement `compute_metrics()` in `sca/service.py` and expose `sca metrics` in `sca/cli.py`.
3. **Inline Rule Instantiation & Duplication in CLI**:
   - In `cli.py`, both `score` and `analyze` subcommands manually instantiated the 18 rules.
   - **Resolution**: Extract rule registry to `sca/rules/registry.py` and centralize analysis in `sca/service.py`.

---

## 2. Refactored Module Design

### 2.1 `sca/scoring.py`
- Holds `DEFAULT_WEIGHTS` covering all 18 rules plus aliases.
- Holds `RULE_SEVERITIES` mapping rule IDs to `"error"`, `"warning"`, or `"info"`.
- `Score` dataclass encapsulating:
  - `value`: 0-100, from the penalty total by `score_from_penalty()`: `100 - penalty` up to 50
    penalty points, then `2500 / penalty` with one decimal (never below 0.1), so every fix on a
    very buggy file still raises it. Grades are unaffected: anything under 60 is an F either way.
  - `grade`: string formatted as `A (Excellent)`, `B (Good)`, `C (Fair)`, `D (Poor)`, or `F (Failing)`
  - `total_issues`: count of issues
  - `deductions`: dictionary of rule deductions sorted by impact
- `compute_score(diagnostics, weights=None) -> Score`:
  - Exactly preserves the CLI grading thresholds and deductions format.
  - Provides `format_cli()` for pristine backwards-compatible terminal output.

### 2.2 `sca/service.py`
- High-level API consumed identically by the CLI and Web backend:
  - `analyze_source(code, filename='main.c', options=None) -> AnalysisResult`
  - `analyze_file(filepath, options=None) -> AnalysisResult`
  - `compute_metrics(ast, source_code=None) -> List[Dict[str, Any]]`
  - `parse_suppressions(source_lines_or_text) -> Dict[int, Set[str]]`
- Enforces security controls:
  - Max code size check (100 KB).
  - Isolated temporary directory with guaranteed cleanup via `try...finally`.
  - Subprocess timeout enforcement (10 s).
  - Structured `AnalysisResult` dataclass matching the Web API specification.

### 2.3 `sca/rules/registry.py`
- Single source of truth for all analyzer rules.
- `get_all_rules()` returns instantiations of all 18 rules.
- `RULE_CATALOG` defines metadata (`id`, `severity`, `description`, `tier`) for each rule for documentation and `/api/rules`.

---

## 3. Implementation Roadmap (Phases W0 – W7)

- **W0 Discovery and refactor**:
  - Write `docs/WEB_NOTES.md`.
  - Extract scoring into `sca/scoring.py` and analysis into `sca/service.py`.
  - Centralize rules in `sca/rules/registry.py`.
  - Add `sca metrics` command to `sca/cli.py`.
  - Add CLI regression and parity test suites.
- **W1 Recommendations engine**:
  - Create `sca/recommendations.py` with per-rule recommendation logic, line-based edit generation, safety ratings (`safe`, `review`, `manual`), priority, and score gain.
  - Implement property testing (syntactic validity and issue clearance after applying fixes).
- **W2 Backend (Flask & API)**:
  - Declare optional `[web]` extra with `Flask` in `pyproject.toml`.
  - Implement Flask application factory `create_app()`, `/api/analyze`, `/api/rules`, `/api/examples`, `/api/ast`, `/api/cfg`, `/api/health`.
  - Add CLI command `sca web` and entry point `python -m sca.web`.
  - Comprehensive API integration and security tests.
- **W3 Frontend shell**:
  - Resizable split-pane layout (OneCompiler-style), top bar, status bar.
  - CodeMirror 5 vendored offline with C syntax highlighting and lint/gutter markers.
  - Dark/Light themes with CSS variables and `localStorage` persistence.
  - Run trigger (Ctrl+Enter / Cmd+Enter) and Output tab with severity filters.
- **W4 Recommendations & Score UI**:
  - Recommendations tab with diff preview, "Apply fix" and "Apply all safe fixes".
  - Score circular SVG gauge with grade, issue count, and deduction breakdown bars.
  - Metrics per-function table with threshold highlighting.
- **W5 Extras**:
  - AST collapsible viewer.
  - Examples dropdown, file upload/download, error banner.
- **W6 Stretch**:
  - CFG SVG visualization with interactive blocks/edges.
- **W7 Polish & Documentation**:
  - Accessibility audit (WCAG AA, focus rings, keyboard navigation).
  - Create `docs/WEB_APP.md` and update `README.md`.
