"""Code quality scoring engine for the Static Code Analyzer."""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from sca.rules.base import Issue

# Weights dictionary keyed by rule id.
# Note: Both 'uninitialized' (reported by UninitializedVariableRule) and
# 'uninitialized-variable' (catalog/spec alias) are mapped to 10 points.
DEFAULT_WEIGHTS: Dict[str, int] = {
    # High impact (10 pts)
    "uninitialized": 10,
    "uninitialized-variable": 10,
    "const-index-out-of-bounds": 10,
    "unsafe-function": 10,
    "index-out-of-range": 10,
    "division-by-zero": 10,
    "contract-violation": 10,

    # Medium impact (4-5 pts)
    "constant-condition": 5,
    "dead-store": 5,
    "missing-return": 5,
    "unreachable-code": 5,
    "shadowed-variable": 5,
    "assignment-in-condition": 5,
    "high-complexity": 5,
    "deep-nesting": 4,

    # Style / Minor impact (1-3 pts)
    "empty-body": 3,
    "function-too-long": 3,
    "too-many-params": 3,
    "unused-variable": 2,
    "unused-parameter": 2,
    "unused-function": 2,
    "magic-number": 2,
    "naming-convention": 1,

    # A crashed rule is the analyzer's fault, not the code's
    "internal-error": 0,
}

RULE_SEVERITIES: Dict[str, str] = {
    "const-index-out-of-bounds": "error",
    "missing-return": "error",
    "uninitialized": "error",
    "uninitialized-variable": "error",
    "internal-error": "error",
    "index-out-of-range": "error",
    "division-by-zero": "error",
    "contract-violation": "error",

    "constant-condition": "warning",
    "function-too-long": "warning",
    "deep-nesting": "warning",
    "too-many-params": "warning",
    "unsafe-function": "warning",
    "assignment-in-condition": "warning",
    "empty-body": "warning",
    "unused-variable": "warning",
    "unused-function": "warning",
    "shadowed-variable": "warning",
    "unreachable-code": "warning",
    "dead-store": "warning",
    "high-complexity": "warning",

    "magic-number": "info",
    "naming-convention": "info",
    "unused-parameter": "info",
}

# Up to this many penalty points the score falls one point per penalty point.
LINEAR_LIMIT = 50


def score_from_penalty(total_penalty: int) -> Union[int, float]:
    """Score (0-100] for a penalty total.

    100 - penalty up to 50 points; above that 2500 / penalty, which meets the line at
    50 and keeps falling without ever reaching 0, so fixes on a very buggy file still
    raise the score. Below 50 the score has one decimal, so small fixes stay visible;
    grades are unaffected because everything under 60 is an F either way.
    """
    if total_penalty <= LINEAR_LIMIT:
        return 100 - total_penalty
    # Tenths, rounded half up in exact integer arithmetic (matches Math.round in the
    # web UI; Python's round() would round exact halves to even).
    tenths = (2 * LINEAR_LIMIT * LINEAR_LIMIT * 10 + total_penalty) // (2 * total_penalty)
    tenths = max(1, tenths)   # beyond 50,000 points it would round to 0; 0.1 is the floor
    return tenths // 10 if tenths % 10 == 0 else tenths / 10


def get_grade(score: float) -> str:
    """Return letter grade with qualitative descriptor."""
    if score >= 90:
        return "A (Excellent)"
    if score >= 80:
        return "B (Good)"
    if score >= 70:
        return "C (Fair)"
    if score >= 60:
        return "D (Poor)"
    return "F (Failing)"

@dataclass
class Score:
    value: Union[int, float]   # see score_from_penalty: one decimal below 50
    grade: str
    total_issues: int
    deductions: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "grade": self.grade,
            "total_issues": self.total_issues,
            "deductions": self.deductions,
        }

    def format_cli(self) -> str:
        """Format the score output exactly as the CLI expects."""
        lines = [
            "========================================",
            f"       Code Quality Score: {self.value}/100",
            f"       Grade: {self.grade}",
            "========================================",
            f"Total Issues Found: {self.total_issues}",
            "",
        ]
        if self.deductions:
            lines.append("Score Deductions by Rule:")
            for rule_id, penalty in sorted(self.deductions.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  - {rule_id}: -{penalty} points")
        else:
            lines.append("Perfect code! No deductions.")
        lines.append("========================================")
        return "\n".join(lines)

def compute_score(
    diagnostics: List[Union[Issue, Dict[str, Any]]],
    weights: Optional[Dict[str, int]] = None
) -> Score:
    """Compute overall quality score (0-100), letter grade, and breakdown."""
    if weights is None:
        weights = DEFAULT_WEIGHTS

    total_penalty = 0
    deductions: Dict[str, int] = {}

    for diag in diagnostics:
        if isinstance(diag, dict):
            rule_id = diag.get("rule_id", "")
        else:
            rule_id = getattr(diag, "rule_id", "")

        weight = weights.get(rule_id, 2)
        total_penalty += weight
        deductions[rule_id] = deductions.get(rule_id, 0) + weight

    score_val = score_from_penalty(total_penalty)
    grade = get_grade(score_val)

    # Sort deductions descending by penalty
    sorted_deductions = dict(sorted(deductions.items(), key=lambda item: item[1], reverse=True))

    return Score(
        value=score_val,
        grade=grade,
        total_issues=len(diagnostics),
        deductions=sorted_deductions,
    )
