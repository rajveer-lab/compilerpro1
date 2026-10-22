# Rule catalog

Defaults shown; thresholds configurable. Messages: short, specific, name the symbol,
no trailing period.

## Tier 1: AST only
| id | severity | default | description |
|---|---|---|---|
| function-too-long | warning | 50 lines | Function body exceeds limit (non-blank, non-comment lines). |
| deep-nesting | warning | 4 | Max nesting of blocks/loops/conditionals/switch exceeds limit. |
| too-many-params | warning | 5 | More parameters than limit. |
| magic-number | info | allowed 0,1,-1,2 | Numeric literal outside `#define`, `const` initializers, array sizes, and `case` labels. |
| naming-convention | info | regex per kind | Function/variable/constant (`#define`, `const` globals) names violate configured regexes. |
| unsafe-function | warning | list below | Call to a banned function. Default list: gets, strcpy, strcat, sprintf, scanf with bare `%s`. Suggest the safer alternative in the message. |
| assignment-in-condition | warning | n/a | `=` used as the condition of if/while/for/do-while/ternary (e.g. `if (x = 5)`), unless wrapped in extra parentheses. |
| empty-body | warning | n/a | `if (...);`, `while (...);`, `for (...);` with an empty statement as body (do-while excluded). |

## Tier 2: AST + symbol table
| id | severity | description |
|---|---|---|
| unused-variable | warning | Local declared but never read (write-only counts as unused). |
| unused-parameter | info | Parameter never referenced. Skip names starting with `_`. |
| unused-function | warning | `static` function never called. Non-static functions are skipped (they may be used by other files). `main` always skipped. |
| shadowed-variable | warning | Declaration hides a declaration from an enclosing scope (including globals and parameters). |
| const-index-out-of-bounds | error | `a[k]` where `a` is a fixed-size array of known size N and `k` is an integer constant outside `0..N-1`. |

## Tier 3: CFG + dataflow
| id | severity | needs | description |
|---|---|---|---|
| unreachable-code | warning | CFG | Statements in blocks unreachable from entry. One report per unreachable region, at its first statement. |
| missing-return | error | CFG | Non-void function where a path reaches exit without `return value`. `main` is exempt (C99 implicit return 0). |
| uninitialized-variable | error | definite assignment | Local scalar read when not assigned on all paths. First offending read per variable. |
| dead-store | warning | liveness | Assigned value never read before being overwritten or function ends. |
| high-complexity | warning | CFG/AST | Cyclomatic complexity > limit (default 10). Decision points: if, while, for, do-while, case, `&&`, `||`, `?:`. Also reported in `sca metrics`. |

## Tier 4: Interval analysis (abstract interpretation)
See `docs/INTERVAL_ANALYSIS.md`. All three share one analysis run per file.

| id | severity | description |
|---|---|---|
| index-out-of-range | error | `a[e]` on a fixed-size 1-D array where the value range of `e` reaches outside `0..N-1` (e.g. a `for (i = 0; i <= N; i++)` loop). Literal indexes are left to `const-index-out-of-bounds`. Points at the `<=` loop condition when that is the cause. |
| division-by-zero | error | Divisor of `/`, `%`, `/=`, `%=` that is always 0, or whose bounded range starts or ends at 0 (`for (i = 0; ...) x / i`). |
| constant-condition | warning | if/while/for condition that is always false (body never runs), or an `if` that is always true while it has an `else` (else never runs). Literal conditions like `while (1)` are not reported. |

## Stretch rules (only after everything else is done and I approve)
| id | description |
|---|---|
| missing-default-case | `switch` without `default`. |
| implicit-fallthrough | Non-empty `case` that falls into the next `case` without `break`/`return`. |
| memory-leak-simple | Local pointer assigned from `malloc/calloc/realloc` with no `free` and not returned or stored on any path to exit. Heuristic; document limits. |
| use-after-free | Use of a pointer after `free(p)` on the same path without reassignment. |

## Internal diagnostics (not configurable)
`parse-error`, `unsupported-construct`, `undeclared-identifier`, `internal-error`.

## False-positive guidance
- When unsure, do not report. Prefer a missed issue over flagging correct code.
- Address-taken variables (`&x`) and arrays are excluded from uninitialized/dead-store analysis.
- Variables passed to functions by pointer are treated as possibly written.
- Struct member writes count as writes to the struct variable for usage tracking.

## Adding a rule (checklist)
1. New file in `sca/rules/`, decorated class, unique kebab-case id.
2. Add row to this file and to `sca.config.example.json`.
3. Tests under `tests/rules/<id>/` (>=2 positive, >=2 negative).
