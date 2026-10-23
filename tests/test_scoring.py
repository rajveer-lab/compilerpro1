import pytest
from sca.scoring import compute_score, DEFAULT_WEIGHTS, RULE_SEVERITIES, get_grade
from sca.rules.registry import get_all_rules, RULE_CATALOG
from sca.rules.base import Issue

def test_all_rules_in_weights():
    """Fail if any registered rule id is missing from the weights table."""
    for entry in RULE_CATALOG:
        rule_id = entry["id"]
        assert rule_id in DEFAULT_WEIGHTS, f"Rule id '{rule_id}' is missing from DEFAULT_WEIGHTS!"

def test_weights_key_mismatch_resolved():
    """Verify both 'uninitialized' and 'uninitialized-variable' are in DEFAULT_WEIGHTS."""
    assert "uninitialized" in DEFAULT_WEIGHTS
    assert "uninitialized-variable" in DEFAULT_WEIGHTS
    assert DEFAULT_WEIGHTS["uninitialized"] == 10
    assert DEFAULT_WEIGHTS["uninitialized-variable"] == 10

def test_compute_score_clean():
    score = compute_score([])
    assert score.value == 100
    assert score.grade == "A (Excellent)"
    assert score.total_issues == 0
    assert score.deductions == {}
    assert "Perfect code! No deductions." in score.format_cli()

def test_compute_score_penalties():
    issues = [
        Issue(file="test.c", line=1, col=1, message="uninit", rule_id="uninitialized"),
        Issue(file="test.c", line=2, col=1, message="unused", rule_id="unused-variable"),
        Issue(file="test.c", line=3, col=1, message="dead", rule_id="dead-store"),
    ]
    score = compute_score(issues)
    # Deductions: uninitialized: 10, dead-store: 5, unused-variable: 2 => total 17 => score 83
    assert score.value == 83
    assert score.grade == "B (Good)"
    assert score.total_issues == 3
    assert score.deductions == {
        "uninitialized": 10,
        "dead-store": 5,
        "unused-variable": 2,
    }

def test_grade_thresholds():
    assert get_grade(95) == "A (Excellent)"
    assert get_grade(90) == "A (Excellent)"
    assert get_grade(85) == "B (Good)"
    assert get_grade(80) == "B (Good)"
    assert get_grade(75) == "C (Fair)"
    assert get_grade(70) == "C (Fair)"
    assert get_grade(65) == "D (Poor)"
    assert get_grade(60) == "D (Poor)"
    assert get_grade(59) == "F (Failing)"
    assert get_grade(0) == "F (Failing)"

def test_score_floor_at_zero():
    # 20 uninitialized issues = 200 points penalty
    issues = [
        Issue(file="test.c", line=i, col=1, message="msg", rule_id="uninitialized")
        for i in range(1, 21)
    ]
    score = compute_score(issues)
    assert score.value == 0
    assert score.grade == "F (Failing)"


def test_projected_score_respects_floor():
    """Safe-fix gains are taken off the penalty total, not added to a score floored at 0."""
    from sca.service import analyze_source
    lines = ["int main(void) {", "    int unused = 0;", "    int a = 1;", "    int z = 0;"]
    lines += ["    a = a / z;"] * 12          # 12 always-zero divisions: 120 penalty points
    lines += ["    return a;", "}"]
    result = analyze_source("\n".join(lines) + "\n")
    penalty = sum(result.score.deductions.values())
    assert penalty > 100 and result.score.value == 0
    assert any(r["safety"] == "safe" and r["edits"] for r in result.recommendations)
    # Removing the unused variable (2 points) still leaves well over 100 points.
    assert result.projected_score == 0
