"""Input contract inference: the parameter values for which a function is provably safe.

For each signed integer parameter p of a function, interval analysis is run with p
assumed to lie in a range [lo, hi] (the other parameters stay unknown), and the
possible out-of-bounds indexes and zero divisors are collected
(IntervalAnalysis.possible_violations). Starting from a safe "anchor" value, a binary
search finds the widest range of p that adds no violation, e.g.

    int get(int n) { int a[5]; return a[n]; }          ->  requires 0 <= n <= 4
    int avg(int total, int count) { return total / count; }  ->  requires count != 0

Calls inside the same file are then checked against these contracts using the
caller's own value ranges (the contract-violation rule).

Limits: parameters are searched one at a time; only signed integer parameters are
considered; a contract is a single range, or a range with one excluded value.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from sca.ast import nodes
from sca.analysis.cfg import parse_c_int
from sca.analysis.intervals import (
    Interval, IntervalAnalysis, State, _fmt, _unit_context, expr_text, walk,
)

# Values tried as the starting point of the search, in order of preference; constants
# used in the function itself are tried after these (at most MAX_EXTRA_ANCHORS).
ANCHORS = (0, 1, -1, 2, 10, 100, -10)
MAX_EXTRA_ANCHORS = 24
# Analysis runs allowed per translation unit, so a large file stays fast.
RUN_BUDGET = 4000


@dataclass
class Contract:
    function: str
    line: int                 # line of the function definition
    param: str
    param_index: int
    allowed: List[Interval]   # one range, or two around a single excluded value
    type_range: Interval
    reasons: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        p = self.param
        if len(self.allowed) == 2:
            return f"{p} != {_fmt(self.allowed[0].hi + 1)}"
        r = self.allowed[0]
        if r.lo == r.hi:
            return f"{p} == {_fmt(r.lo)}"
        if r.lo <= self.type_range.lo:
            return f"{p} <= {_fmt(r.hi)}"
        if r.hi >= self.type_range.hi:
            return f"{p} >= {_fmt(r.lo)}"
        return f"{_fmt(r.lo)} <= {p} <= {_fmt(r.hi)}"

    def check(self, value: Interval) -> Optional[str]:
        """'always' if every value in the range breaks the contract, 'can' if some do."""
        if value.is_top():
            return None  # nothing known about the argument
        if any(value.lo >= r.lo and value.hi <= r.hi for r in self.allowed):
            return None
        if all(value.meet(r) is None for r in self.allowed):
            return "always"
        return "can"

    def to_dict(self) -> Dict:
        return {
            "function": self.function,
            "line": self.line,
            "param": self.param,
            "param_index": self.param_index,
            "text": self.text,
            "allowed": [[_fmt(r.lo), _fmt(r.hi)] for r in self.allowed],
            "reasons": self.reasons,
        }


@dataclass
class FunctionContracts:
    function: str
    line: int
    contracts: List[Contract]
    complete: bool = True     # False if the run budget ran out for this function

    def to_dict(self) -> Dict:
        return {
            "function": self.function,
            "line": self.line,
            "contracts": [c.to_dict() for c in self.contracts],
            "complete": self.complete,
        }


class _OutOfBudget(Exception):
    pass


class _Prober:
    """Runs the analysis of one function under parameter assumptions, with a cache."""

    def __init__(self, func: nodes.FunctionDef, context, budget: List[int]):
        self.func = func
        self.constants, self.global_names, self.global_arrays = context
        self.budget = budget
        self.cache: Dict[Tuple[str, float, float], Optional[Dict]] = {}

    def violations(self, param: str, lo: float, hi: float) -> Optional[Dict]:
        """Possible violations with param in [lo, hi]; None if the analysis gave up."""
        key = (param, lo, hi)
        if key not in self.cache:
            if self.budget[0] <= 0:
                raise _OutOfBudget()
            self.budget[0] -= 1
            assume: State = {param: Interval(lo, hi)}
            analysis = IntervalAnalysis(self.func, self.global_names, self.global_arrays,
                                        self.constants, assume=assume).run()
            self.cache[key] = analysis.possible_violations() if analysis.converged else None
        return self.cache[key]


def _search_max(start: int, limit: int, ok: Callable[[int], bool]) -> int:
    """Largest h in [start, limit] with ok(h), given ok(start) and ok monotone."""
    if ok(limit):
        return limit
    good, bad = start, limit
    while bad - good > 1:
        mid = (good + bad) // 2
        if ok(mid):
            good = mid
        else:
            bad = mid
    return good


def _search_min(limit: int, start: int, ok: Callable[[int], bool]) -> int:
    """Smallest l in [limit, start] with ok(l), given ok(start) and ok monotone."""
    if ok(limit):
        return limit
    bad, good = limit, start
    while good - bad > 1:
        mid = (good + bad) // 2
        if ok(mid):
            good = mid
        else:
            bad = mid
    return good


def _function_constants(func: nodes.FunctionDef, constants: Dict[str, int]) -> List[int]:
    """Integer literals and #define values used in a function, with their neighbours.

    Extra anchor candidates: for `table[t - 20]` none of the fixed ANCHORS is safe,
    but 20 is.
    """
    values: Set[int] = set()
    for n in walk(func.body):
        value = None
        if isinstance(n, nodes.IntLiteral):
            value = parse_c_int(n.text)
        elif isinstance(n, nodes.Identifier) and n.name in constants:
            value = constants[n.name]
        if value is not None:
            values.update((value, value - 1, value + 1, -value))
    return sorted(values - set(ANCHORS), key=lambda v: (abs(v), v))[:MAX_EXTRA_ANCHORS]


def _infer_param(prober: _Prober, func: nodes.FunctionDef, index: int,
                 param: str, type_range: Interval) -> Optional[Contract]:
    tmin, tmax = int(type_range.lo), int(type_range.hi)

    # Anchor: the candidate value with the fewest violations. Violations it still has
    # don't depend on this parameter and are ignored from here on.
    best: Optional[Tuple[int, Set]] = None
    for a in ANCHORS + tuple(_function_constants(func, prober.constants)):
        if not tmin <= a <= tmax:
            continue
        found = prober.violations(param, a, a)
        if found is None:
            return None
        if best is None or len(found) < len(best[1]):
            best = (a, set(found))
        if not found:
            break
    if best is None:
        return None
    anchor, base = best

    full = prober.violations(param, tmin, tmax)
    if full is None or set(full) <= base:
        return None  # no value of this parameter makes things worse

    def safe(lo: int, hi: int) -> bool:
        found = prober.violations(param, lo, hi)
        return found is not None and set(found) <= base

    hi = _search_max(anchor, tmax, lambda h: safe(anchor, h))
    lo = _search_min(tmin, anchor, lambda l: safe(l, hi))

    # The binary search assumes "safe" is monotone, which interval imprecision can break:
    # after `if (count == 0) return 0;` the range [-5, 5] still contains 0 on the other
    # branch, so a guarded function looks unsafe for ranges that straddle 0. Each
    # boundary is therefore re-checked: if everything beyond it is safe, it was not a
    # real boundary; otherwise the value just past it must be unsafe on its own.
    # Anything else gives no contract: a missed contract beats a wrong one.
    def point_unsafe(v: int) -> bool:
        return not safe(v, v)

    if lo > tmin and safe(tmin, lo - 1):
        lo = tmin
    if hi < tmax and safe(hi + 1, tmax):
        hi = tmax
    if lo == tmin and hi == tmax:
        return None

    allowed = [Interval(lo, hi)]
    if lo > tmin:
        if lo - 2 >= tmin and safe(tmin, lo - 2):
            # A single excluded value, e.g. `count != 0`: safe on both sides of one point.
            if hi != tmax or not point_unsafe(lo - 1):
                return None
            allowed.insert(0, Interval(tmin, lo - 2))
        elif not point_unsafe(lo - 1):
            return None
    if hi < tmax:
        if hi + 2 <= tmax and safe(hi + 2, tmax):
            if lo != tmin or len(allowed) > 1 or not point_unsafe(hi + 1):
                return None
            allowed.append(Interval(hi + 2, tmax))
        elif not point_unsafe(hi + 1):
            return None

    reasons = [desc for key, desc in sorted(full.items(), key=lambda kv: (kv[0][1], kv[0][2]))
               if key not in base]
    return Contract(func.name, func.loc.line, param, index, allowed, type_range, reasons)


def infer_unit(ast: nodes.TranslationUnit) -> List[FunctionContracts]:
    """Contracts for every function definition in a translation unit."""
    context = _unit_context(ast)
    constants, global_names, global_arrays = context
    budget = [RUN_BUDGET]
    results: List[FunctionContracts] = []
    for item in ast.items:
        if not isinstance(item, nodes.FunctionDef):
            continue
        entry = FunctionContracts(item.name, item.loc.line, [])
        results.append(entry)
        tracked = IntervalAnalysis(item, global_names, global_arrays, constants).tracked
        prober = _Prober(item, context, budget)
        for i, p in enumerate(item.params):
            if not p.name or p.name not in tracked:
                continue
            try:
                contract = _infer_param(prober, item, i, p.name, tracked[p.name])
            except _OutOfBudget:
                entry.complete = False
                break
            if contract is not None:
                entry.contracts.append(contract)
    return results


def call_violations(ast: nodes.TranslationUnit,
                    contracts: List[FunctionContracts]) -> List[Tuple[nodes.Call, str]]:
    """Calls in this file whose argument ranges break the callee's contract."""
    by_name: Dict[str, List[Contract]] = {fc.function: fc.contracts for fc in contracts if fc.contracts}
    if not by_name:
        return []
    constants, global_names, global_arrays = _unit_context(ast)
    out: List[Tuple[nodes.Call, str]] = []
    for item in ast.items:
        if not isinstance(item, nodes.FunctionDef):
            continue
        analysis = IntervalAnalysis(item, global_names, global_arrays, constants).run()
        for call, values in analysis.call_arguments():
            if not isinstance(call.callee, nodes.Identifier):
                continue
            for contract in by_name.get(call.callee.name, []):
                if contract.param_index >= len(values):
                    continue
                value = values[contract.param_index]
                verdict = contract.check(value)
                # A partly-unknown range ([0, +inf)) is too vague to blame the caller.
                if verdict is None or (verdict == "can" and not value.is_bounded()):
                    continue
                arg = expr_text(call.args[contract.param_index])
                shown = f"is {value}" if value.is_const() else f"is in {value}"
                how = "breaks" if verdict == "always" else "can break"
                out.append((call, (
                    f"Call {call.callee.name}(...) {how} its input contract "
                    f"'{contract.text}': argument '{arg}' {shown} here.")))
    return out


# One inference per translation unit, shared by the rule and the service (same idea as
# the cache in sca/rules/interval_rules.py).
_last: Optional[Tuple[nodes.TranslationUnit, List[FunctionContracts]]] = None


def unit_contracts(ast: nodes.TranslationUnit) -> List[FunctionContracts]:
    global _last
    cached = _last
    if cached is not None and cached[0] is ast:
        return cached[1]
    found = infer_unit(ast)
    _last = (ast, found)
    return found
