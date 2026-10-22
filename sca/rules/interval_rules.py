"""Rules built on interval analysis (sca/analysis/intervals.py).

All three rules share one analysis run per translation unit: the first rule to ask
computes it, the other two reuse it.
"""

from typing import List, Optional, Tuple
from sca.rules.base import Rule, Issue
from sca.ast import nodes
from sca.analysis.intervals import Finding, analyze_unit

# (translation unit, its findings). Holding a reference to the unit keeps its id from
# being reused, so an identity check is enough to know the cache is for this AST.
_last: Optional[Tuple[nodes.TranslationUnit, List[Finding]]] = None


def interval_findings(ast: nodes.TranslationUnit) -> List[Finding]:
    global _last
    cached = _last
    if cached is not None and cached[0] is ast:
        return cached[1]
    found = analyze_unit(ast)
    _last = (ast, found)
    return found


class _IntervalRule(Rule):
    kind = ""
    rule_id = ""

    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        for f in interval_findings(ast):
            if f.kind == self.kind:
                issues.append(Issue(
                    file=filename,
                    line=f.node.loc.line,
                    col=f.node.loc.col,
                    message=f.message,
                    rule_id=self.rule_id,
                ))
        return issues


class IndexOutOfRangeRule(_IntervalRule):
    """`a[i]` where the range of i (e.g. from a loop bound) goes outside the array."""
    kind = "index"
    rule_id = "index-out-of-range"


class DivisionByZeroRule(_IntervalRule):
    """`x / d` or `x % d` where d is always 0, or a bounded range that starts or ends at 0."""
    kind = "divide"
    rule_id = "division-by-zero"


class ConstantConditionRule(_IntervalRule):
    """An if/while/for condition whose value is fixed, so a branch can never run."""
    kind = "condition"
    rule_id = "constant-condition"
