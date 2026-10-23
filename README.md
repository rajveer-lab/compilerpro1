# sca — Static Code Quality Analyzer for C

**Live demo:** https://compilerpro1.vercel.app (web app hosted on Vercel; redeploys on every push to `main`)

Two components:



1. **`cparse`** (C, Flex + Bison): lexes and parses a C subset and prints a JSON AST.
2. **`sca`** (Python): runs `cparse`, then performs semantic analysis, builds control-flow
   graphs, runs dataflow analyses and quality rules, and reports diagnostics.

## Features (target)
- AST checks: function length, nesting depth, parameter count, magic numbers, naming,
  unsafe library calls, assignment in condition, empty bodies
- Symbol-table checks: unused variables/parameters/functions, shadowing,
  constant array index out of bounds
- Flow checks (CFG + dataflow): unreachable code, missing return, uninitialized use,
  dead stores, cyclomatic complexity
- Interval analysis (abstract interpretation with widening/narrowing): off-by-one loop
  indexes, division by zero, and conditions that are always false, with an explanation
  of the values involved. These bugs compile without a single `gcc -Wall -Wextra`
  warning; see `examples/interval_demo.c` and `docs/INTERVAL_ANALYSIS.md`.
- Input contract inference: for each function, the parameter values it is provably safe
  for (`get(int n)` indexing `a[5]` requires `0 <= n <= 4`; `avg` dividing by `count`
  requires `count != 0`), and a `contract-violation` error for calls in the same file
  that break them (`sca contracts`, Contracts tab).
- Misconception diagnosis: each issue is linked to the beginner misconception behind it
  ("an array of size N has an index N", "variables start at 0"), with a per-browser
  learning profile in the web UI (`sca analyze --explain`, Learning tab).
- Text and JSON output, config file, inline suppression, CI-friendly exit codes
- Interactive Web UI: offline-first browser IDE with automated fix recommendations, score gauge, and AST viewer

## Setup (Windows + WSL)
See `docs/BUILD_AND_RUN.md`. Short version, inside a WSL terminal:
```bash
sudo apt update && sudo apt install -y build-essential flex bison make python3 python3-venv python3-pip
bash scripts/check_env.sh
make build
make test
```

## Usage
```bash
sca analyze <file.c> [--rule ID ...] [--disable ID ...] [--fail-on error,warning] [--explain]
sca contracts <file.c>             # infer the input ranges each function is safe for
sca score <file.c>                 # compute quality score (0-100) and grade
sca metrics <file.c>               # compute per-function code metrics
sca ast <file.c>                   # dump the AST
sca tokens <file.c>                # dump tokens (from cparse --tokens)
sca parse <file.c>                 # Parse and print python AST
sca cfg <file.c> <func>            # dump a CFG (debugging)
sca liveness <file.c> <func>       # print liveness IN/OUT per block
sca ranges <file.c> <func>         # print interval-analysis value ranges per block
sca web [--host HOST] [--port PORT] # launch interactive web application
```

## Web UI
Install the optional web dependencies and launch the server:
```bash
pip install -e ".[web]"
sca web
```
Then navigate to `http://127.0.0.1:8000` in your browser.

Key Web Features:
- **Interactive Editor:** C99 code editing powered by offline vendored CodeMirror with inline gutter markers and error highlights.
- **One-Click Recommendations:** Automated fix engine with side-by-side diff previews, single fix application, and "Apply all safe fixes".
- **Quality Score & Metrics:** Circular SVG score gauge (0–100), letter grade, rule deduction bars, and function metrics table.
- **AST Explorer:** Interactive collapsible JSON syntax tree linked to editor source ranges.
- **REST API:** Headless JSON endpoints (`/api/analyze`, `/api/rules`, `/api/examples`, `/api/ast`, `/api/cfg`).

See [`docs/WEB_APP.md`](docs/WEB_APP.md) for full documentation, API reference, and manual QA checklist.

## Quality score
Each finding deducts its rule's weight (10 points for errors such as `index-out-of-range`, down to
1 for `naming-convention`). The score is `100 − penalty` up to 50 penalty points; above that it is
`2500 ÷ penalty` with one decimal, so it never reaches 0 and every fix on a very buggy file still
raises it. Grades: A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, F below.

## Exit codes
- 0: no findings at or above `--fail-on` severity
- 1: findings at or above `--fail-on` severity
- 2: usage error, unreadable file, or source failed to parse

## Docs
`docs/`: spec, C subset and grammar, JSON AST schema, architecture, build/run, rules,
testing, interval analysis (`docs/INTERVAL_ANALYSIS.md`), web application guide
(`docs/WEB_APP.md`), task plan.
