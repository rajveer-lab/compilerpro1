# Interval analysis

`sca/analysis/intervals.py` is an abstract interpreter that computes, for every point in
a function, the **range of values** each integer variable can hold. Three rules use it:

| rule | finds |
|---|---|
| `index-out-of-range` | `a[i]` where the range of `i` reaches outside `0..N-1` (off-by-one loops) |
| `division-by-zero` | `x / d`, `x % d` where `d` is always 0, or a range that starts/ends at 0 |
| `constant-condition` | `if`/`while`/`for` conditions that are always false (or always true with an `else`) |

## Why

These bugs are common in student code and the compiler stays silent about them.
`examples/interval_demo.c` compiles with **zero warnings** under `gcc -Wall -Wextra`
(no optimisation, the way students usually compile):

```c
for (int i = 0; i <= STUDENTS; i++) {   /* i reaches 5 */
    marks[i] = i * 10;                  /* marks has 5 elements */
```
```
$ sca analyze examples/interval_demo.c --disable magic-number
L12:9  index-out-of-range: Index 'i' can reach 5 here, but 'marks' has 5 elements (valid indexes 0..4).
       Off-by-one: the loop on line 11 runs while 'i <= STUDENTS'; did you mean 'i < STUDENTS'?
L20:12 division-by-zero: Division by zero: 'count' is always 0 here.
L25:9  constant-condition: Condition 'score > 100' is always false here (score is 72), so the 'if' body never runs.
```

Every message says *why*: the range that was computed and, for off-by-one loops, the
loop condition responsible. The web UI's Recommendations tab offers the `<=` → `<` fix
for review.

## Evaluation

`examples/interval_eval/` holds a small reproducible benchmark (checked by
`tests/test_intervals.py::test_evaluation_set`):

| file | contents | `gcc -Wall -Wextra -O0` | `sca` interval rules |
|---|---|---|---|
| `buggy.c` | 10 range bugs (4 index, 2 divide, 4 condition) | 0 warnings | 10 found |
| `correct.c` | 12 correct functions: binary search, reverse loops, guarded indexes, modulo guards, do-while, nested loops | 0 warnings | 0 false alarms |

Extend both files with real student submissions to grow the evaluation.

## How it works

### 1. The domain

A value is an interval `[lo, hi]` (`lo` may be −∞, `hi` may be +∞). A program point maps
each tracked variable to an interval; a missing variable means "unknown" (−∞, +∞), and a
whole state of `None` means the point is unreachable.

Arithmetic follows the corners: `[a,b] + [c,d] = [a+c, b+d]`,
`[a,b] * [c,d] = [min, max of the four products]`. Division truncates toward zero like C,
and gives "unknown" if the divisor range contains 0. Comparisons evaluate to `[1,1]`
(surely true), `[0,0]` (surely false) or `[0,1]`.

### 2. Statements

The solver walks the CFG (`sca/analysis/cfg.py`) forwards. `int i = 0` sets `i = [0,0]`,
`i++` adds `[1,1]`, `x = y / 2` evaluates the right side, and so on. If a result leaves
the C type's range (`int` overflow) the variable becomes unknown, since C wraps or is
undefined there.

### 3. Branch refinement

The CFG builder records, for each `if`/loop condition block, which successor is the
*true* edge and which is the *false* edge. On the true edge of `i <= 5` the solver
intersects `i` with `(−∞, 5]`; on the false edge with `[6, +∞)`. `&&`, `||` and `!` are
handled by combining the refinements of their operands. If an edge's state becomes empty,
that edge can never be taken. That is how `constant-condition` works.

### 4. Loops: widening and narrowing

Around `for (i = 0; i <= 5; i++)` the head of the loop sees `i = [0,0]`, then `[0,1]`,
`[0,2]`... Iterating to the end would be slow, and for unbounded loops it would never end. So
after a loop head has been visited 3 times, any bound that is still moving jumps to
infinity (**widening**): `i = [0, +∞)`. Every cycle in a CFG passes through a DFS back
edge, so widening at back-edge targets guarantees termination.

Widening over-shoots, so the solver then runs 2 normal passes (**narrowing**). The loop
condition pulls the bounds back in. `sca ranges` shows the result:

```
$ sca ranges examples/interval_demo.c total_marks
Block 2 (line 11): i = [0, 6]          <- loop head: i <= 5 is tested with i up to 6
  branches on 'i <= STUDENTS'
Block 3 (line 12): i = [0, 5]          <- loop body, after refining with i <= 5
Block 5 (line 15): i = 6               <- after the loop, refined with i > 5
```

The body sees `i = [0, 5]` and `marks` has 5 elements, so `marks[5]` is reachable.

### 5. Staying quiet when unsure

Following the project rule "prefer a missed issue over flagging correct code":

* Only signed integer locals/params are tracked. Globals, `static` locals, variables
  whose address is taken (`scanf("%d", &n)`), unsigned/float values, array contents and
  function results are unknown.
* A name declared twice in a function isn't tracked (scopes are matched by name).
* An index is reported only if the offending bound is finite: `a[n]` with an unknown
  `n` is not reported.
* A divisor is reported only if it is exactly 0, or a *bounded* range with 0 at an end.
  Intervals can't represent "anything but 0", so a 0 in the middle of a range might be
  excluded by a guard like `if (d)`.
* Conditions without a tracked variable (`while (1)`, `if (0)`) are intentional and not
  reported. An always-true `if` without an `else` is only redundant, so it isn't reported.
* Literal indexes (`a[7]`) are left to `const-index-out-of-bounds`.

See `docs/KNOWN_LIMITATIONS.md` for what this can't do (path-insensitive merges, no
inter-procedural analysis).

## Code map

| piece | where |
|---|---|
| `Interval`, arithmetic, `join`/`meet`/`widen` | `sca/analysis/intervals.py` (top) |
| expression/statement evaluation, branch refinement | `Evaluator` |
| tracked variables, array sizes, `#define` values | `tracked_variables`, `array_sizes`, `define_value` |
| worklist solver, widening, narrowing | `IntervalAnalysis.run` |
| messages | `IntervalAnalysis.findings` |
| rules (one analysis per file, shared) | `sca/rules/interval_rules.py` |
| true/false edges on branch blocks | `BasicBlock.set_branch` in `sca/analysis/cfg.py` |
| `#define` values in the AST | `TranslationUnit.defines`, filled by `sca/frontend/loader.py` |
| tests | `tests/test_intervals.py` |
