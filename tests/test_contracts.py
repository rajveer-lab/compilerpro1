from sca.frontend.runner import run_cparse
from sca.frontend.loader import load_ast
from sca.analysis.intervals import Interval
from sca.analysis.contracts import infer_unit, call_violations
from sca.rules.contract_rules import ContractViolationRule
from sca.service import analyze_source


def load(tmp_path, code):
    c_file = tmp_path / "test.c"
    c_file.write_text(code)
    return load_ast(run_cparse(str(c_file)))


def contracts_of(tmp_path, code):
    """function name -> list of contract texts."""
    return {fc.function: [c.text for c in fc.contracts] for fc in infer_unit(load(tmp_path, code))}


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def test_index_bounds(tmp_path):
    code = "int get(int n) { int a[5] = {0}; return a[n]; }"
    assert contracts_of(tmp_path, code) == {"get": ["0 <= n <= 4"]}


def test_nonzero_divisor(tmp_path):
    code = "int avg(int total, int count) { return total / count; }"
    assert contracts_of(tmp_path, code) == {"avg": ["count != 0"]}


def test_modulo_divisor(tmp_path):
    code = "int wrap(int x, int m) { return x % m; }"
    assert contracts_of(tmp_path, code) == {"wrap": ["m != 0"]}


def test_loop_bound(tmp_path):
    code = """
#define SIZE 10
void fill(int n) {
    int buf[SIZE];
    for (int i = 0; i < n; i++)
        buf[i] = i;
}
"""
    assert contracts_of(tmp_path, code) == {"fill": ["n <= 10"]}


def test_off_by_one_loop_bound(tmp_path):
    code = """
void fill(int n) {
    int buf[10];
    for (int i = 0; i <= n; i++)
        buf[i] = i;
}
"""
    assert contracts_of(tmp_path, code) == {"fill": ["n <= 9"]}


def test_offset_index(tmp_path):
    code = "int prev(int i) { int a[8] = {0}; return a[i - 1]; }"
    assert contracts_of(tmp_path, code) == {"prev": ["1 <= i <= 8"]}


def test_guarded_function_needs_no_contract(tmp_path):
    code = """
int safe_get(int n) {
    int a[5] = {0};
    if (n < 0 || n >= 5)
        return -1;
    return a[n];
}
int safe_avg(int total, int count) {
    if (count == 0)
        return 0;
    return total / count;
}
"""
    assert contracts_of(tmp_path, code) == {"safe_get": [], "safe_avg": []}


def test_expression_shapes(tmp_path):
    code = """
int g1(int total, int count) { if (count != 0) return total / count; return 0; }
int g2(int n) { int a[5] = {0}; if (n > 0 && n < 5) return a[n]; return 0; }
int g3(int n) { int a[5] = {0}; if (n >= 0) return a[n]; return 0; }
int g4(int n) { int a[5] = {0}; return a[n % 5]; }
int g5(int n) { int a[5] = {0}; return a[n * 2]; }
int g6(int d) { return 100 / (d - 3); }
int g7(int n) { int a[10] = {0}; int s = 0; for (int i = n; i < 10; i++) s += a[i]; return s; }
"""
    assert contracts_of(tmp_path, code) == {
        "g1": [],
        "g2": [],
        "g3": ["n <= 4"],
        "g4": ["n >= 0"],          # C's % is negative for negative n
        "g5": ["0 <= n <= 2"],
        "g6": ["d != 3"],
        "g7": ["n >= 0"],
    }


def test_offset_with_no_safe_default_anchor(tmp_path):
    # None of 0, 1, -1, 2, 10, 100, -10 is a safe t here; the search must start
    # from the constants used in the function itself (20).
    code = """
#define MIN_TEMP 20
int calibrate(int t) { int table[10] = {0}; return t + table[t - MIN_TEMP]; }
int shifted(int k) { int a[4] = {0}; return a[k - 1000]; }
"""
    assert contracts_of(tmp_path, code) == {
        "calibrate": ["20 <= t <= 29"],
        "shifted": ["1000 <= k <= 1003"],
    }


def test_problem_independent_of_parameter_is_not_blamed_on_it(tmp_path):
    # count is always 0: no value of `total` can fix that, so no contract on total.
    code = "int average(int total) { int count = 0; return total / count; }"
    assert contracts_of(tmp_path, code) == {"average": []}


def test_reasons_name_the_site(tmp_path):
    code = "int get(int n) { int a[5] = {0}; return a[n]; }"
    (fc,) = infer_unit(load(tmp_path, code))
    assert fc.contracts[0].reasons == ["indexes 'a[n]' (5 elements) at line 1"]


def test_contract_check():
    from sca.analysis.contracts import Contract
    int_range = Interval(-2**31, 2**31 - 1)
    c = Contract("get", 1, "n", 0, [Interval(0, 4)], int_range)
    assert c.check(Interval(2, 3)) is None
    assert c.check(Interval(7, 7)) == "always"
    assert c.check(Interval(0, 9)) == "can"
    assert c.check(Interval(-float("inf"), float("inf"))) is None  # unknown argument
    nz = Contract("avg", 1, "count", 1, [Interval(-2**31, -1), Interval(1, 2**31 - 1)], int_range)
    assert nz.text == "count != 0"
    assert nz.check(Interval(0, 0)) == "always"
    assert nz.check(Interval(1, 10)) is None
    assert nz.check(Interval(-1, 1)) == "can"


# ---------------------------------------------------------------------------
# Call-site checks (contract-violation rule)
# ---------------------------------------------------------------------------

CALLS = """
#define SIZE 10
int get(int n) { int a[5] = {0}; return a[n]; }
int avg(int total, int count) { return total / count; }
void fill(int n) { int buf[SIZE]; for (int i = 0; i < n; i++) buf[i] = i; }
int main(void) {
    int x = 7;
    int ok = 3;
    fill(12);
    fill(SIZE);
    return get(x) + get(ok) + avg(10, 0) + avg(10, 2);
}
"""


def test_call_violations(tmp_path):
    issues = ContractViolationRule().analyze(load(tmp_path, CALLS), "test.c")
    found = sorted((i.line, i.message.split("(")[0]) for i in issues)
    assert found == [
        (9, "Call fill"),
        (11, "Call avg"),
        (11, "Call get"),
    ]
    get_issue = next(i for i in issues if "get" in i.message)
    assert "'0 <= n <= 4'" in get_issue.message and "'x' is 7" in get_issue.message


def test_loop_variable_argument_can_break_contract(tmp_path):
    code = """
int get(int n) { int a[5] = {0}; return a[n]; }
int main(void) {
    int s = 0;
    for (int i = 0; i <= 5; i++)
        s += get(i);
    return s;
}
"""
    issues = ContractViolationRule().analyze(load(tmp_path, code), "test.c")
    assert len(issues) == 1
    assert "can break" in issues[0].message and "[0, 5]" in issues[0].message


def test_unknown_argument_is_not_reported(tmp_path):
    code = """
int get(int n) { int a[5] = {0}; return a[n]; }
int use(int k) { return get(k); }
"""
    assert ContractViolationRule().analyze(load(tmp_path, code), "test.c") == []


def test_service_reports_contracts(tmp_path):
    result = analyze_source(CALLS)
    by_name = {fc["function"]: fc for fc in result.contracts}
    assert by_name["get"]["contracts"][0]["text"] == "0 <= n <= 4"
    assert by_name["main"]["contracts"] == []
    assert sum(d["rule_id"] == "contract-violation" for d in result.diagnostics) == 3


def test_no_false_alarms_on_examples():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "examples"
    for path in list(root.glob("*.c")) + list(root.glob("interval_eval/*.c")):
        result = analyze_source(path.read_text(), filename=path.name)
        assert not [d for d in result.diagnostics if d["rule_id"] == "contract-violation"], path
