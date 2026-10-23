import subprocess
import json
import pytest
from sca.service import analyze_source, analyze_file, MAX_SOURCE_SIZE
from sca.scoring import compute_score

def test_service_clean_example():
    """Verify clean example returns score 100, no diagnostics, and clean metrics."""
    res = analyze_file("examples/clean.c")
    assert res.ok is True
    assert res.parse_errors == []
    assert res.diagnostics == []
    assert res.summary == {"error": 0, "warning": 0, "info": 0}
    assert res.score is not None
    assert res.score.value == 100
    assert res.score.grade == "A (Excellent)"
    assert res.projected_score == 100
    assert len(res.metrics) == 1
    assert res.metrics[0]["function"] == "main"
    assert res.metrics[0]["line"] == 1
    assert res.metrics[0]["col"] == 1
    assert res.metrics[0]["params"] == 0
    assert res.metrics[0]["cyclomatic"] == 1

def test_service_metrics_void_params_count_as_zero():
    """`f(void)` takes no parameters, so Metrics must not show Params 1 for it."""
    res = analyze_source("int helper(void) {\n    return 1;\n}\n\nint main(void) {\n    return helper();\n}\n")
    assert [(m["function"], m["params"]) for m in res.metrics] == [("helper", 0), ("main", 0)]

def test_service_smelly_example():
    """Verify smelly example reports unused-variable and correct score deductions."""
    res = analyze_file("examples/smelly.c")
    assert res.ok is True
    assert res.parse_errors == []
    assert len(res.diagnostics) == 1
    assert res.diagnostics[0]["rule_id"] == "unused-variable"
    assert res.diagnostics[0]["line"] == 2
    assert res.score is not None
    assert res.score.value == 98
    assert res.score.deductions == {"unused-variable": 2}

def test_parity_source_vs_file():
    """Verify analyze_source and analyze_file produce identical results."""
    with open("examples/smelly.c", "r", encoding="utf-8") as f:
        code = f.read()
    res_file = analyze_file("examples/smelly.c")
    res_source = analyze_source(code, filename="examples/smelly.c")

    assert res_file.diagnostics == res_source.diagnostics
    assert res_file.score.value == res_source.score.value
    assert res_file.metrics == res_source.metrics

def test_cli_regression_analyze():
    """Verify CLI `sca analyze` behaves identically to service analysis."""
    p = subprocess.run(
        ["python3", "-m", "sca.cli", "analyze", "examples/smelly.c"],
        capture_output=True,
        text=True
    )
    # smelly.c has 1 issue, CLI should exit with code 1
    assert p.returncode == 1
    cli_out = json.loads(p.stdout)
    assert len(cli_out) == 1
    assert cli_out[0]["rule_id"] == "unused-variable"
    assert cli_out[0]["line"] == 2

    # clean.c has 0 issues, CLI should exit with code 0
    p_clean = subprocess.run(
        ["python3", "-m", "sca.cli", "analyze", "examples/clean.c"],
        capture_output=True,
        text=True
    )
    assert p_clean.returncode == 0
    assert json.loads(p_clean.stdout) == []

def test_cli_regression_score():
    """Verify CLI `sca score` produces expected score and format."""
    p = subprocess.run(
        ["python3", "-m", "sca.cli", "score", "examples/smelly.c"],
        capture_output=True,
        text=True
    )
    assert p.returncode == 0
    assert "Code Quality Score: 98/100" in p.stdout
    assert "unused-variable: -2 points" in p.stdout

def test_cli_regression_metrics():
    """Verify CLI `sca metrics --json` produces valid metrics JSON."""
    p = subprocess.run(
        ["python3", "-m", "sca.cli", "metrics", "examples/clean.c", "--json"],
        capture_output=True,
        text=True
    )
    assert p.returncode == 0
    metrics = json.loads(p.stdout)
    assert len(metrics) == 1
    assert metrics[0]["function"] == "main"
    assert metrics[0]["cyclomatic"] == 1

def test_security_max_payload_size():
    """Ensure payloads exceeding 100 KB are strictly rejected."""
    oversized = "int main() {\n" + "    int x = 0;\n" * 10000 + "    return 0;\n}\n"
    assert len(oversized.encode("utf-8")) > MAX_SOURCE_SIZE
    with pytest.raises(ValueError, match="Payload size"):
        analyze_source(oversized)

def test_syntax_error_handling():
    """Verify invalid syntax returns ok=True, populated parse_errors, and no score."""
    bad_code = "int main( {"
    res = analyze_source(bad_code)
    assert res.ok is True
    assert len(res.parse_errors) > 0
    assert res.diagnostics == []
    assert res.score is None
