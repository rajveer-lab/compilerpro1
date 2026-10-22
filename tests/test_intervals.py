import math
import pytest
from sca.ast import nodes
from sca.frontend.runner import run_cparse
from sca.frontend.loader import load_ast
from sca.analysis.intervals import (
    Interval, TOP, ZERO, ONE, BOOL, INF,
    iv_add, iv_sub, iv_mul, iv_div, iv_mod, iv_compare,
    IntervalAnalysis, char_value, define_value,
)
from sca.rules.interval_rules import IndexOutOfRangeRule, DivisionByZeroRule, ConstantConditionRule
from sca.recommendations import build_recommendations, apply_edits


def load(tmp_path, code):
    c_file = tmp_path / "test.c"
    c_file.write_text(code)
    return load_ast(run_cparse(str(c_file)))


def run_rule(tmp_path, rule, code):
    return rule.analyze(load(tmp_path, code), "test.c")


def get_func(ast, name):
    for item in ast.items:
        if isinstance(item, nodes.FunctionDef) and item.name == name:
            return item
    return None


# ---------------------------------------------------------------------------
# Interval domain
# ---------------------------------------------------------------------------

def test_arithmetic():
    assert iv_add(Interval(0, 4), Interval(1, 1)) == Interval(1, 5)
    assert iv_sub(Interval(0, 4), Interval(1, 2)) == Interval(-2, 3)
    assert iv_mul(Interval(-2, 3), Interval(4, 5)) == Interval(-10, 15)
    # 0 * inf must be 0, not NaN
    assert iv_mul(Interval(0, 2), Interval(0, INF)) == Interval(0, INF)


def test_division_truncates_toward_zero():
    assert iv_div(Interval(7, 7), Interval(2, 2)) == Interval(3, 3)
    assert iv_div(Interval(-7, -7), Interval(2, 2)) == Interval(-3, -3)
    assert iv_div(Interval(0, 100), Interval(10, 10)) == Interval(0, 10)
    # a divisor range containing 0 gives no information
    assert iv_div(Interval(1, 5), Interval(-1, 1)) == TOP


def test_modulo():
    assert iv_mod(Interval(0, 100), Interval(3, 3)) == Interval(0, 2)
    assert iv_mod(Interval(-100, 100), Interval(5, 5)) == Interval(-4, 4)
    assert iv_mod(Interval(0, 1), Interval(10, 10)) == Interval(0, 1)


def test_compare():
    assert iv_compare("<", Interval(0, 4), Interval(5, 5)) == ONE
    assert iv_compare("<", Interval(5, 9), Interval(5, 5)) == ZERO
    assert iv_compare("<", Interval(0, 9), Interval(5, 5)) == BOOL
    assert iv_compare("==", Interval(3, 3), Interval(3, 3)) == ONE
    assert iv_compare("!=", Interval(0, 2), Interval(5, 9)) == ONE


def test_join_meet_widen():
    assert Interval(0, 2).join(Interval(5, 6)) == Interval(0, 6)
    assert Interval(0, 2).meet(Interval(3, 6)) is None
    assert Interval(0, 4).meet(Interval(2, 9)) == Interval(2, 4)
    # A bound that moved goes to infinity; one that stayed put is kept.
    assert Interval(0, 1).widen(Interval(0, 2)) == Interval(0, INF)
    assert Interval(0, 1).widen(Interval(-1, 1)) == Interval(-INF, 1)


def test_literal_helpers():
    assert char_value("'a'") == 97
    assert char_value("'\\n'") == 10
    assert char_value("'\\0'") == 0
    assert define_value("5") == 5
    assert define_value("(10)") == 10
    assert define_value("-1") == -1
    assert define_value("0x10") == 16
    assert define_value('"text"') is None


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def _state_at_return(analysis):
    for b in analysis.cfg.blocks:
        if any(isinstance(s, nodes.Return) for s in b.statements):
            return analysis.in_states[b.bid]
    return None


def test_loop_exit_value_recovered_by_narrowing(tmp_path):
    ast = load(tmp_path, "int f(void) { int i; for (i = 0; i < 5; i++) { } return i; }")
    analysis = IntervalAnalysis(get_func(ast, "f")).run()
    assert analysis.converged
    # Widening alone would give [5, +inf); the loop condition narrows it back to 5.
    assert _state_at_return(analysis)["i"] == Interval(5, 5)


def test_loop_body_range(tmp_path):
    ast = load(tmp_path, "int f(void) { int s = 0; for (int i = 0; i <= 9; i++) { s = i; } return s; }")
    analysis = IntervalAnalysis(get_func(ast, "f")).run()
    assert _state_at_return(analysis)["s"] == Interval(0, 9)


def test_unknown_values_stay_unknown(tmp_path):
    # parameters, address-taken variables and globals are never assumed to hold anything
    ast = load(tmp_path, "int g; int f(int p) { int x; scanf(\"%d\", &x); int y = p + x + g; return y; }")
    analysis = IntervalAnalysis(get_func(ast, "f"), global_names={"g"}).run()
    state = _state_at_return(analysis)
    assert "x" not in analysis.tracked and "g" not in analysis.tracked
    assert state.get("y", TOP) == TOP


def test_terminates_on_tricky_loops(tmp_path):
    code = """
    int f(int n) {
        int a = 0, b = 1, c = 0;
        while (a < n) {
            for (int j = n; j > 0; j = j / 2) {
                b = b * 2 - a;
                c = c + j % 7;
            }
            a = a + b;
            if (c > 1000) c = 0;
        }
        do { a--; } while (a > c);
        return a + b + c;
    }
    """
    analysis = IntervalAnalysis(get_func(load(tmp_path, code), "f")).run()
    assert analysis.converged


# ---------------------------------------------------------------------------
# index-out-of-range
# ---------------------------------------------------------------------------

def test_index_off_by_one_loop(tmp_path):
    code = "int main() { int a[5]; for (int i = 0; i <= 5; i++) a[i] = i; return 0; }"
    issues = run_rule(tmp_path, IndexOutOfRangeRule(), code)
    assert len(issues) == 1
    assert issues[0].rule_id == "index-out-of-range"
    assert "can reach 5" in issues[0].message
    assert "did you mean 'i < 5'" in issues[0].message


def test_index_plus_one_and_define(tmp_path):
    code = "#define N 4\nint main() { int a[N]; int s = 0;\n for (int i = 0; i < N; i++) s += a[i + 1];\n return s; }"
    issues = run_rule(tmp_path, IndexOutOfRangeRule(), code)
    assert len(issues) == 1
    assert issues[0].line == 3
    assert "'i + 1' can reach 4" in issues[0].message


def test_index_negative(tmp_path):
    code = "int main() { int a[5]; int s = 0; for (int i = 4; i >= -1; i--) s += a[i]; return s; }"
    issues = run_rule(tmp_path, IndexOutOfRangeRule(), code)
    assert len(issues) == 1
    assert "can be -1" in issues[0].message


def test_index_in_range_loops_not_flagged(tmp_path):
    code = """
    int main() {
        int a[5]; int s = 0;
        for (int i = 0; i < 5; i++) a[i] = i;
        for (int j = 4; j >= 0; j--) s += a[j];
        for (int k = 0; k + 1 < 5; k++) a[k + 1] = a[k];
        return s;
    }"""
    assert run_rule(tmp_path, IndexOutOfRangeRule(), code) == []


def test_index_guarded_or_unknown_not_flagged(tmp_path):
    code = """
    int get(int a[], int n, int k) { return a[k]; }
    int main(int argc) {
        int b[5];
        if (argc >= 0 && argc < 5) b[argc] = 1;
        b[0] = get(b, 5, 2);
        return b[0];
    }"""
    assert run_rule(tmp_path, IndexOutOfRangeRule(), code) == []


def test_literal_index_left_to_const_rule(tmp_path):
    # a[7] is const-index-out-of-bounds' finding; don't report it twice
    assert run_rule(tmp_path, IndexOutOfRangeRule(), "int main() { int a[5]; a[7] = 1; return 0; }") == []


def test_same_name_declared_twice_not_tracked(tmp_path):
    # Two different `i`s: matching by name would mix them up, so neither is tracked.
    code = "int main() { int a[3]; int i = 2; { int i = 10; a[0] = i; } a[i] = 1; return 0; }"
    assert run_rule(tmp_path, IndexOutOfRangeRule(), code) == []


# ---------------------------------------------------------------------------
# division-by-zero
# ---------------------------------------------------------------------------

def test_divide_by_constant_zero(tmp_path):
    code = "int main() { int sum = 10; int n = 0; return sum / n; }"
    issues = run_rule(tmp_path, DivisionByZeroRule(), code)
    assert len(issues) == 1
    assert issues[0].rule_id == "division-by-zero"
    assert "always 0" in issues[0].message


def test_divide_by_loop_counter_from_zero(tmp_path):
    code = "int main() { int s = 0; for (int i = 0; i < 4; i++) s += 100 / i; return s; }"
    issues = run_rule(tmp_path, DivisionByZeroRule(), code)
    assert len(issues) == 1
    assert "range [0, 3]" in issues[0].message


def test_modulo_assign_by_zero(tmp_path):
    code = "int main() { int s = 7; int n = 0; s %= n; return s; }"
    issues = run_rule(tmp_path, DivisionByZeroRule(), code)
    assert len(issues) == 1
    assert "Modulo by zero" in issues[0].message


def test_divide_guarded_not_flagged(tmp_path):
    code = """
    int avg(int total, int count) { if (count == 0) return 0; return total / count; }
    int ratio(int v) { int r = v % 3; if (r) return 12 / r; return 0; }
    int main() { return avg(10, 2) + ratio(7); }"""
    assert run_rule(tmp_path, DivisionByZeroRule(), code) == []


def test_divide_unknown_or_nonzero_not_flagged(tmp_path):
    code = "int main(int argc) { int n = 2; int s = 10 / n; for (int i = 1; i < 4; i++) s += 6 / i; return s / argc; }"
    assert run_rule(tmp_path, DivisionByZeroRule(), code) == []


# ---------------------------------------------------------------------------
# constant-condition
# ---------------------------------------------------------------------------

def test_if_always_false(tmp_path):
    code = "int main() { int x = 5; if (x > 10) return 1; return 0; }"
    issues = run_rule(tmp_path, ConstantConditionRule(), code)
    assert len(issues) == 1
    assert issues[0].rule_id == "constant-condition"
    assert "always false" in issues[0].message and "x is 5" in issues[0].message


def test_loop_never_runs(tmp_path):
    code = "int main() { int t = 0; for (int i = 10; i < 5; i++) t += i; return t; }"
    issues = run_rule(tmp_path, ConstantConditionRule(), code)
    assert len(issues) == 1
    assert "loop body never runs" in issues[0].message


def test_else_never_runs(tmp_path):
    code = "int main() { int x = 5; int y; if (x < 10) y = 1; else y = 2; return y; }"
    issues = run_rule(tmp_path, ConstantConditionRule(), code)
    assert len(issues) == 1
    assert "'else' branch never runs" in issues[0].message


def test_check_inside_loop_always_false(tmp_path):
    code = "int main() { int t = 0; for (int j = 0; j < 5; j++) { if (j > 5) t = -1; } return t; }"
    issues = run_rule(tmp_path, ConstantConditionRule(), code)
    assert len(issues) == 1
    assert "j is in [0, 4]" in issues[0].message


def test_intentional_constants_not_flagged(tmp_path):
    # while (1), if (0) and conditions on unknown values are left alone
    code = """
    int main(int argc) {
        int x = 0;
        while (1) { x++; if (x > 3) break; }
        if (0) x = 9;
        if (argc > 2) x = 1;
        return x;
    }"""
    assert run_rule(tmp_path, ConstantConditionRule(), code) == []


def test_changing_conditions_not_flagged(tmp_path):
    code = """
    int main(int n) {
        int x = 0, found = 0;
        while (x < 10) x++;
        for (int i = 0; i < n && !found; i++) { if (i * i > 50) found = 1; }
        if (x == 10) found = 2;
        return found;
    }"""
    assert run_rule(tmp_path, ConstantConditionRule(), code) == []


# ---------------------------------------------------------------------------
# Recommendation and demo
# ---------------------------------------------------------------------------

def test_off_by_one_recommendation_fixes_loop(tmp_path):
    code = "int main() {\n    int a[5];\n    for (int i = 0; i <= 5; i++)\n        a[i] = i;\n    return 0;\n}\n"
    issues = run_rule(tmp_path, IndexOutOfRangeRule(), code)
    diags = [{"rule_id": i.rule_id, "line": i.line, "col": i.col, "message": i.message} for i in issues]
    recs = build_recommendations(diags, code)
    assert recs[0].safety == "review"
    fixed = apply_edits(code, recs[0].edits)
    assert "i < 5" in fixed and "i <= 5" not in fixed
    assert run_rule(tmp_path, IndexOutOfRangeRule(), fixed) == []


INTERVAL_RULES = ["index-out-of-range", "division-by-zero", "constant-condition"]


def _example(*parts):
    import os
    return os.path.join(os.path.dirname(__file__), "..", "examples", *parts)


def test_interval_demo_example():
    from sca.service import analyze_file
    result = analyze_file(_example("interval_demo.c"))
    rules = {d["rule_id"] for d in result.diagnostics}
    assert set(INTERVAL_RULES) <= rules


def test_evaluation_set():
    # The numbers quoted in docs/INTERVAL_ANALYSIS.md: 10/10 bugs found, 0 false alarms.
    from collections import Counter
    from sca.service import analyze_file
    buggy = analyze_file(_example("interval_eval", "buggy.c"), options={"rule": INTERVAL_RULES})
    assert Counter(d["rule_id"] for d in buggy.diagnostics) == {
        "index-out-of-range": 4, "division-by-zero": 2, "constant-condition": 4}
    correct = analyze_file(_example("interval_eval", "correct.c"), options={"rule": INTERVAL_RULES})
    assert correct.diagnostics == []
