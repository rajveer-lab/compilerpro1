"""Calls that break an inferred input contract (sca/analysis/contracts.py)."""

from typing import List
from sca.rules.base import Rule, Issue
from sca.ast import nodes
from sca.analysis.contracts import unit_contracts, call_violations


class ContractViolationRule(Rule):
    """`get(7)` where get indexes a 5-element array with its parameter."""
    rule_id = "contract-violation"

    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        return [
            Issue(file=filename, line=call.loc.line, col=call.loc.col,
                  message=message, rule_id=self.rule_id)
            for call, message in call_violations(ast, unit_contracts(ast))
        ]
