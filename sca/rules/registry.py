"""Rule registry and metadata catalog."""

from typing import List, Dict, Any
from sca.rules.base import Rule
from sca.rules.uninitialized import UninitializedVariableRule
from sca.rules.unused import UnusedVariableRule, UnusedParameterRule
from sca.rules.phase7 import UnusedFunctionRule, ShadowedVariableRule, ConstIndexOutOfBoundsRule
from sca.rules.cfg_rules import UnreachableCodeRule, MissingReturnRule, HighComplexityRule
from sca.rules.dataflow_rules import DeadStoreRule
from sca.rules.interval_rules import IndexOutOfRangeRule, DivisionByZeroRule, ConstantConditionRule
from sca.rules.contract_rules import ContractViolationRule
from sca.rules.ast_rules import (
    FunctionTooLongRule,
    DeepNestingRule,
    TooManyParamsRule,
    MagicNumberRule,
    NamingConventionRule,
    UnsafeFunctionRule,
    AssignmentInConditionRule,
    EmptyBodyRule,
)

RULE_CATALOG: List[Dict[str, Any]] = [
    # Tier 1: AST only
    {
        "id": "function-too-long",
        "name": "Function Too Long",
        "default_severity": "warning",
        "description": "Function body exceeds limit (50 lines).",
        "tier": 1,
    },
    {
        "id": "deep-nesting",
        "name": "Deep Nesting",
        "default_severity": "warning",
        "description": "Max nesting of blocks/loops/conditionals/switch exceeds limit (4).",
        "tier": 1,
    },
    {
        "id": "too-many-params",
        "name": "Too Many Parameters",
        "default_severity": "warning",
        "description": "Function parameter count exceeds limit (5).",
        "tier": 1,
    },
    {
        "id": "magic-number",
        "name": "Magic Number",
        "default_severity": "info",
        "description": "Numeric literal outside constants, initializers, and case labels.",
        "tier": 1,
    },
    {
        "id": "naming-convention",
        "name": "Naming Convention",
        "default_severity": "info",
        "description": "Identifier naming does not match conventions (snake_case / UPPER_CASE).",
        "tier": 1,
    },
    {
        "id": "unsafe-function",
        "name": "Unsafe Function",
        "default_severity": "warning",
        "description": "Call to banned/unsafe C library functions (gets, strcpy, strcat, sprintf, scanf).",
        "tier": 1,
    },
    {
        "id": "assignment-in-condition",
        "name": "Assignment in Condition",
        "default_severity": "warning",
        "description": "Assignment '=' used as condition expression.",
        "tier": 1,
    },
    {
        "id": "empty-body",
        "name": "Empty Body",
        "default_severity": "warning",
        "description": "Control statement has an empty statement/block as body.",
        "tier": 1,
    },

    # Tier 2: AST + Symbol Table
    {
        "id": "unused-variable",
        "name": "Unused Variable",
        "default_severity": "warning",
        "description": "Local variable declared but never read.",
        "tier": 2,
    },
    {
        "id": "unused-parameter",
        "name": "Unused Parameter",
        "default_severity": "info",
        "description": "Function parameter never referenced.",
        "tier": 2,
    },
    {
        "id": "unused-function",
        "name": "Unused Function",
        "default_severity": "warning",
        "description": "Static function never called within translation unit.",
        "tier": 2,
    },
    {
        "id": "shadowed-variable",
        "name": "Shadowed Variable",
        "default_severity": "warning",
        "description": "Declaration hides a variable from an enclosing scope.",
        "tier": 2,
    },
    {
        "id": "const-index-out-of-bounds",
        "name": "Constant Index Out of Bounds",
        "default_severity": "error",
        "description": "Constant array index is outside the fixed array bounds.",
        "tier": 2,
    },

    # Tier 3: CFG + Dataflow
    {
        "id": "unreachable-code",
        "name": "Unreachable Code",
        "default_severity": "warning",
        "description": "Statements in basic blocks unreachable from function entry.",
        "tier": 3,
    },
    {
        "id": "missing-return",
        "name": "Missing Return",
        "default_severity": "error",
        "description": "Non-void function path reaches exit without return value.",
        "tier": 3,
    },
    {
        "id": "uninitialized",
        "name": "Uninitialized Variable",
        "default_severity": "error",
        "description": "Local scalar variable read before definite assignment.",
        "tier": 3,
    },
    {
        "id": "dead-store",
        "name": "Dead Store",
        "default_severity": "warning",
        "description": "Assigned value is never read before being overwritten or function exit.",
        "tier": 3,
    },
    {
        "id": "high-complexity",
        "name": "High Cyclomatic Complexity",
        "default_severity": "warning",
        "description": "Function cyclomatic complexity exceeds threshold (10).",
        "tier": 3,
    },

    # Tier 4: Interval analysis (abstract interpretation)
    {
        "id": "index-out-of-range",
        "name": "Index Out of Range",
        "default_severity": "error",
        "description": "Array index whose value range (e.g. from a loop bound) reaches outside the array.",
        "tier": 4,
    },
    {
        "id": "division-by-zero",
        "name": "Division by Zero",
        "default_severity": "error",
        "description": "Divisor that is always 0, or whose value range starts or ends at 0.",
        "tier": 4,
    },
    {
        "id": "constant-condition",
        "name": "Constant Condition",
        "default_severity": "warning",
        "description": "Condition that is always false (or always true), so a branch or loop body never runs.",
        "tier": 4,
    },
    {
        "id": "contract-violation",
        "name": "Contract Violation",
        "default_severity": "error",
        "description": "Call whose argument range breaks the callee's inferred input contract (e.g. get(7) when get requires 0 <= n <= 4).",
        "tier": 4,
    },
]

def get_all_rules() -> List[Rule]:
    """Return new instances of all registered analysis rules."""
    return [
        UninitializedVariableRule(),
        UnusedVariableRule(),
        UnusedParameterRule(),
        UnusedFunctionRule(),
        ShadowedVariableRule(),
        ConstIndexOutOfBoundsRule(),
        UnreachableCodeRule(),
        MissingReturnRule(),
        HighComplexityRule(),
        DeadStoreRule(),
        FunctionTooLongRule(),
        DeepNestingRule(),
        TooManyParamsRule(),
        MagicNumberRule(),
        NamingConventionRule(),
        UnsafeFunctionRule(),
        AssignmentInConditionRule(),
        EmptyBodyRule(),
        IndexOutOfRangeRule(),
        DivisionByZeroRule(),
        ConstantConditionRule(),
        ContractViolationRule(),
    ]
