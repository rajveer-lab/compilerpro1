"""Interval analysis: abstract interpretation of integer variables over the CFG.

Every tracked integer variable is mapped to a range [lo, hi] of the values it may hold
at a program point. The solver is the usual forward worklist algorithm, with three
additions that the set-based analyses in dataflow.py don't need:

* Branch refinement. On the edge where `i < 5` holds we know i <= 4, and on the other
  edge i >= 5. This is what lets the analysis see that the body of
  `for (i = 0; i <= 5; i++)` runs with i in [0, 5].
* Widening. Around a loop a range can grow forever ([0,0], [0,1], [0,2], ...), so at a
  loop head a bound that is still growing after a few visits jumps straight to
  infinity. That guarantees termination.
* Narrowing. Widening over-shoots (i in [0, +inf) at the loop head); a couple of normal
  passes afterwards pull the bounds back in using the loop conditions.

The analysis is deliberately conservative. Anything it can't model precisely (globals,
variables whose address is taken, unsigned or floating-point arithmetic, array contents,
function results) is "unknown" (top), and the rules built on it only report when a
range is precise enough to be sure.
"""

import math
from collections import Counter, deque
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple

from sca.ast import nodes
from sca.analysis.cfg import CFG, BasicBlock, build_cfg, parse_c_int

INF = math.inf


def _fmt(bound: float) -> str:
    if bound == -INF:
        return "-inf"
    if bound == INF:
        return "+inf"
    return str(int(bound))


@dataclass(frozen=True)
class Interval:
    """The integers lo..hi inclusive; lo may be -inf and hi may be +inf."""
    lo: float
    hi: float

    @staticmethod
    def const(value: int) -> "Interval":
        return Interval(value, value)

    def is_top(self) -> bool:
        return self.lo == -INF and self.hi == INF

    def is_bounded(self) -> bool:
        return self.lo != -INF and self.hi != INF

    def is_const(self) -> bool:
        return self.lo == self.hi

    def contains(self, value: int) -> bool:
        return self.lo <= value <= self.hi

    def join(self, other: "Interval") -> "Interval":
        return Interval(min(self.lo, other.lo), max(self.hi, other.hi))

    def meet(self, other: "Interval") -> Optional["Interval"]:
        lo, hi = max(self.lo, other.lo), min(self.hi, other.hi)
        return Interval(lo, hi) if lo <= hi else None

    def widen(self, newer: "Interval") -> "Interval":
        # Keep a bound only if it did not move; a moving bound is assumed to keep moving.
        lo = self.lo if newer.lo >= self.lo else -INF
        hi = self.hi if newer.hi <= self.hi else INF
        return Interval(lo, hi)

    def __str__(self) -> str:
        if self.is_const():
            return _fmt(self.lo)
        return f"[{_fmt(self.lo)}, {_fmt(self.hi)}]"


TOP = Interval(-INF, INF)
ZERO = Interval.const(0)
ONE = Interval.const(1)
BOOL = Interval(0, 1)

# Value ranges of the signed integer types we track. Unsigned types wrap around instead
# of going negative, which this domain can't express, so they are not tracked.
_INT32 = Interval(-2**31, 2**31 - 1)
_INT64 = Interval(-2**63, 2**63 - 1)
INT_RANGES: Dict[str, Interval] = {
    "char": Interval(-128, 127),
    "signed char": Interval(-128, 127),
    "short": Interval(-32768, 32767),
    "short int": Interval(-32768, 32767),
    "signed short": Interval(-32768, 32767),
    "int": _INT32,
    "signed": _INT32,
    "signed int": _INT32,
    "long": _INT64,
    "long int": _INT64,
    "signed long": _INT64,
    "long long": _INT64,
    "long long int": _INT64,
}


# ---------------------------------------------------------------------------
# Interval arithmetic
# ---------------------------------------------------------------------------

def _mul(a: float, b: float) -> float:
    # 0 * inf is 0 for interval bounds (it would be NaN in float arithmetic).
    if a == 0 or b == 0:
        return 0
    return a * b


def _tdiv(a: float, b: float) -> float:
    """C integer division (truncates toward zero), extended to infinite bounds."""
    if math.isinf(a):
        return a if b > 0 else -a
    if math.isinf(b):
        return 0
    q = abs(int(a)) // abs(int(b))
    return q if (a >= 0) == (b > 0) else -q


def iv_add(a: Interval, b: Interval) -> Interval:
    return Interval(a.lo + b.lo, a.hi + b.hi)


def iv_sub(a: Interval, b: Interval) -> Interval:
    return Interval(a.lo - b.hi, a.hi - b.lo)


def iv_neg(a: Interval) -> Interval:
    return Interval(-a.hi, -a.lo)


def iv_mul(a: Interval, b: Interval) -> Interval:
    corners = [_mul(x, y) for x in (a.lo, a.hi) for y in (b.lo, b.hi)]
    return Interval(min(corners), max(corners))


def iv_div(a: Interval, b: Interval) -> Interval:
    if b.contains(0):
        return TOP
    # With a divisor that keeps one sign, truncating division is monotone in each
    # argument, so the extremes are at the corners.
    corners = [_tdiv(x, y) for x in (a.lo, a.hi) for y in (b.lo, b.hi)]
    return Interval(min(corners), max(corners))


def iv_mod(a: Interval, b: Interval) -> Interval:
    if b == ZERO:
        return TOP
    m = max(abs(b.lo), abs(b.hi))
    bound = INF if math.isinf(m) else m - 1
    # |a % b| < |b|, and the result takes the sign of a.
    if a.lo >= 0:
        return Interval(0, min(a.hi, bound))
    if a.hi <= 0:
        return Interval(max(a.lo, -bound), 0)
    return Interval(-bound, bound)


def iv_compare(op: str, a: Interval, b: Interval) -> Interval:
    """Result of a comparison: [1,1] if surely true, [0,0] if surely false, else [0,1]."""
    if op == "<":
        sure, never = a.hi < b.lo, a.lo >= b.hi
    elif op == "<=":
        sure, never = a.hi <= b.lo, a.lo > b.hi
    elif op == ">":
        sure, never = a.lo > b.hi, a.hi <= b.lo
    elif op == ">=":
        sure, never = a.lo >= b.hi, a.hi < b.lo
    elif op == "==":
        sure = a.is_const() and b.is_const() and a.lo == b.lo
        never = a.meet(b) is None
    elif op == "!=":
        sure = a.meet(b) is None
        never = a.is_const() and b.is_const() and a.lo == b.lo
    else:
        return BOOL
    if sure:
        return ONE
    if never:
        return ZERO
    return BOOL


def iv_truth(a: Interval) -> Interval:
    """C truthiness of a value: 1 if surely nonzero, 0 if surely zero."""
    if a == ZERO:
        return ZERO
    if not a.contains(0):
        return ONE
    return BOOL


COMPARISONS = {"<", "<=", ">", ">=", "==", "!="}
_NEGATE = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "!=", "!=": "=="}
_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "==", "!=": "!="}
_INC_DEC = {"++", "--", "INC_OP", "DEC_OP"}
_COMPOUND = {"+=": "+", "-=": "-", "*=": "*", "/=": "/", "%=": "%"}


# ---------------------------------------------------------------------------
# Abstract states: variable name -> Interval. A missing name means "unknown" (top);
# None as a whole state means the program point is unreachable (bottom).
# ---------------------------------------------------------------------------

State = Dict[str, Interval]


def _store(state: State, name: str, value: Interval) -> None:
    if value.is_top():
        state.pop(name, None)
    else:
        state[name] = value


def join_states(a: Optional[State], b: Optional[State]) -> Optional[State]:
    if a is None:
        return None if b is None else dict(b)
    if b is None:
        return dict(a)
    out: State = {}
    # A name missing from either side is top there, so only shared names stay bounded.
    for name in a.keys() & b.keys():
        _store(out, name, a[name].join(b[name]))
    return out


def widen_states(old: Optional[State], new: Optional[State]) -> Optional[State]:
    if old is None or new is None:
        return new if old is None else old
    out: State = {}
    for name in old.keys() & new.keys():
        _store(out, name, old[name].widen(new[name]))
    return out


# ---------------------------------------------------------------------------
# Helpers over the AST
# ---------------------------------------------------------------------------

def walk(node: Optional[nodes.Node]) -> Iterator[nodes.Node]:
    """Yield node and every AST node below it."""
    if node is None:
        return
    stack: List[nodes.Node] = [node]
    while stack:
        n = stack.pop()
        yield n
        if hasattr(n, "__dataclass_fields__"):
            for field_name in n.__dataclass_fields__:
                val = getattr(n, field_name)
                if isinstance(val, nodes.Node):
                    stack.append(val)
                elif isinstance(val, list):
                    stack.extend(i for i in val if isinstance(i, nodes.Node))


def has_side_effects(expr: Optional[nodes.Node]) -> bool:
    """True if evaluating expr may change a variable (assignment, ++ or --)."""
    for n in walk(expr):
        if isinstance(n, nodes.Assign):
            return True
        if isinstance(n, (nodes.Unary, nodes.Postfix)) and n.op in _INC_DEC:
            return True
    return False


_ESCAPES = {"n": 10, "t": 9, "r": 13, "\\": 92, "'": 39, '"': 34,
            "a": 7, "b": 8, "f": 12, "v": 11, "?": 63}


def char_value(text: str) -> Optional[int]:
    """Numeric value of a C character literal such as 'a', '\\n' or '\\x41'."""
    if len(text) < 3 or text[0] != "'" or text[-1] != "'":
        return None
    body = text[1:-1]
    if len(body) == 1:
        return ord(body)
    if body[0] != "\\":
        return None
    rest = body[1:]
    try:
        if rest[:1] in ("x", "X"):
            return int(rest[1:], 16)
        if rest and all(c in "01234567" for c in rest):
            return int(rest, 8)
    except ValueError:
        return None
    return _ESCAPES.get(rest)


def define_value(text: str) -> Optional[int]:
    """Integer value of a `#define` body like `5`, `(10)`, `-1`, `0x10` or `'A'`."""
    t = text.strip()
    while t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    sign = 1
    if t.startswith("-"):
        sign, t = -1, t[1:].strip()
    value = parse_c_int(t)
    if value is None:
        value = char_value(t)
    return None if value is None else sign * value


_PREC = {"*": 10, "/": 10, "%": 10, "+": 9, "-": 9, "<<": 8, ">>": 8,
         "<": 7, "<=": 7, ">": 7, ">=": 7, "==": 6, "!=": 6,
         "&": 5, "^": 4, "|": 3, "&&": 2, "||": 1}


def expr_text(e: Optional[nodes.Node], max_len: int = 40) -> str:
    """Short C source text for an expression, for diagnostic messages."""
    text = _expr_text(e)
    return text if len(text) <= max_len else text[:max_len - 3] + "..."


def _expr_text(e: Optional[nodes.Node], parent_prec: int = 0, right: bool = False) -> str:
    if e is None:
        return ""
    if isinstance(e, nodes.Identifier):
        return e.name
    if isinstance(e, (nodes.IntLiteral, nodes.FloatLiteral, nodes.CharLiteral, nodes.StringLiteral)):
        return e.text
    if isinstance(e, nodes.Binary):
        prec = _PREC.get(e.op, 0)
        text = f"{_expr_text(e.left, prec)} {e.op} {_expr_text(e.right, prec, True)}"
        # Parenthesize only where C precedence requires it.
        if prec < parent_prec or (right and prec == parent_prec):
            return f"({text})"
        return text
    if isinstance(e, nodes.Unary):
        op = {"INC_OP": "++", "DEC_OP": "--"}.get(e.op, e.op)
        return f"{op}{_expr_text(e.operand, 11)}"
    if isinstance(e, nodes.Postfix):
        op = {"INC_OP": "++", "DEC_OP": "--"}.get(e.op, e.op)
        return f"{_expr_text(e.operand, 12)}{op}"
    if isinstance(e, nodes.Assign):
        text = f"{_expr_text(e.target)} {e.op} {_expr_text(e.value)}"
        return f"({text})" if parent_prec else text
    if isinstance(e, nodes.Index):
        return f"{_expr_text(e.base, 12)}[{_expr_text(e.index)}]"
    if isinstance(e, nodes.Call):
        args = ", ".join(_expr_text(a) for a in e.args)
        return f"{_expr_text(e.callee, 12)}({args})"
    if isinstance(e, nodes.Member):
        return f"{_expr_text(e.base, 12)}{'->' if e.arrow else '.'}{e.name}"
    if isinstance(e, nodes.Ternary):
        text = f"{_expr_text(e.cond, 1)} ? {_expr_text(e.then_branch)} : {_expr_text(e.else_branch)}"
        return f"({text})" if parent_prec else text
    if isinstance(e, nodes.Cast):
        type_name = e.type.name if isinstance(e.type, nodes.BaseType) else "..."
        return f"({type_name}) {_expr_text(e.operand, 11)}"
    if isinstance(e, nodes.Sizeof):
        return f"sizeof({_expr_text(e.operand)})" if e.operand else "sizeof(...)"
    return "..."


def _is_literal(e: nodes.Node) -> bool:
    if isinstance(e, (nodes.IntLiteral, nodes.CharLiteral)):
        return True
    return isinstance(e, nodes.Unary) and e.op in ("-", "+") and _is_literal(e.operand)


# ---------------------------------------------------------------------------
# Evaluation of expressions and statements on an abstract state
# ---------------------------------------------------------------------------

IndexHook = Callable[[nodes.Index, Interval], None]
DivideHook = Callable[[nodes.Node, str, nodes.Expr, Interval], None]


class Evaluator:
    """Evaluates expressions to intervals, applying their assignments to the state.

    The optional hooks are called with the index range at every `a[i]` and the divisor
    range at every `/` and `%`; the solver runs without hooks, the rules run one final
    pass with them once the states are stable.
    """

    def __init__(self, tracked: Dict[str, Interval], constants: Dict[str, int],
                 on_index: Optional[IndexHook] = None,
                 on_divide: Optional[DivideHook] = None):
        self.tracked = tracked      # tracked variable -> value range of its C type
        self.constants = constants  # #define NAME <int>
        self.on_index = on_index
        self.on_divide = on_divide

    def silent(self) -> "Evaluator":
        return Evaluator(self.tracked, self.constants)

    def lookup(self, name: str, state: State) -> Interval:
        if name in self.tracked:
            return state.get(name, TOP)
        if name in self.constants:
            return Interval.const(self.constants[name])
        return TOP

    def assign(self, name: str, value: Interval, state: State) -> None:
        if name not in self.tracked:
            return
        # A result outside the type's range wraps around (or is undefined), so we no
        # longer know anything about the variable.
        type_range = self.tracked[name]
        if not (type_range.lo <= value.lo and value.hi <= type_range.hi):
            value = TOP
        _store(state, name, value)

    def binary(self, op: str, a: Interval, b: Interval) -> Interval:
        if op == "+":
            return iv_add(a, b)
        if op == "-":
            return iv_sub(a, b)
        if op == "*":
            return iv_mul(a, b)
        if op == "/":
            return iv_div(a, b)
        if op == "%":
            return iv_mod(a, b)
        if op in COMPARISONS:
            return iv_compare(op, a, b)
        if op == "&" and b.is_const() and b.lo >= 0:
            return Interval(0, b.lo)  # masking with a non-negative constant
        if op == "&" and a.is_const() and a.lo >= 0:
            return Interval(0, a.lo)
        return TOP

    def check_divide(self, node: nodes.Node, op: str, divisor: nodes.Expr, value: Interval) -> None:
        if self.on_divide is not None and op in ("/", "%"):
            self.on_divide(node, op, divisor, value)

    def eval(self, e: Optional[nodes.Node], state: State) -> Interval:
        if e is None:
            return TOP
        if isinstance(e, nodes.IntLiteral):
            value = parse_c_int(e.text)
            return TOP if value is None else Interval.const(value)
        if isinstance(e, nodes.CharLiteral):
            value = char_value(e.text)
            return TOP if value is None else Interval.const(value)
        if isinstance(e, nodes.Identifier):
            return self.lookup(e.name, state)
        if isinstance(e, nodes.Unary):
            return self._unary(e, state)
        if isinstance(e, nodes.Postfix):
            old = self.eval(e.operand, state)
            if e.op in _INC_DEC and isinstance(e.operand, nodes.Identifier):
                step = ONE if e.op in ("++", "INC_OP") else iv_neg(ONE)
                self.assign(e.operand.name, iv_add(old, step), state)
            return old
        if isinstance(e, nodes.Binary):
            return self._binary(e, state)
        if isinstance(e, nodes.Assign):
            return self._assign(e, state)
        if isinstance(e, nodes.Ternary):
            cond = iv_truth(self.eval(e.cond, state))
            if cond == ONE:
                return self.eval(e.then_branch, state)
            if cond == ZERO:
                return self.eval(e.else_branch, state)
            then_state, else_state = dict(state), dict(state)
            value = self.eval(e.then_branch, then_state).join(self.eval(e.else_branch, else_state))
            state.clear()
            state.update(join_states(then_state, else_state) or {})
            return value
        if isinstance(e, nodes.Call):
            for arg in e.args:
                self.eval(arg, state)
            return TOP
        if isinstance(e, nodes.Index):
            self.eval(e.base, state)
            index = self.eval(e.index, state)
            if self.on_index is not None:
                self.on_index(e, index)
            return TOP
        if isinstance(e, nodes.Member):
            self.eval(e.base, state)
            return TOP
        if isinstance(e, nodes.Cast):
            value = self.eval(e.operand, state)
            if isinstance(e.type, nodes.BaseType) and e.type.name in INT_RANGES:
                type_range = INT_RANGES[e.type.name]
                if type_range.lo <= value.lo and value.hi <= type_range.hi:
                    return value
            return TOP
        if isinstance(e, nodes.InitList):
            for item in e.items:
                self.eval(item, state)
            return TOP
        # sizeof does not evaluate its operand; floats and strings are not tracked.
        return TOP

    def _unary(self, e: nodes.Unary, state: State) -> Interval:
        if e.op == "&":
            return TOP  # only names, whose address is taken, never tracked
        if e.op in _INC_DEC:
            old = self.eval(e.operand, state)
            step = ONE if e.op in ("++", "INC_OP") else iv_neg(ONE)
            new = iv_add(old, step)
            if isinstance(e.operand, nodes.Identifier):
                self.assign(e.operand.name, new, state)
            return new
        value = self.eval(e.operand, state)
        if e.op == "-":
            return iv_neg(value)
        if e.op == "+":
            return value
        if e.op == "!":
            truth = iv_truth(value)
            return ONE if truth == ZERO else ZERO if truth == ONE else BOOL
        return TOP  # *, ~

    def _binary(self, e: nodes.Binary, state: State) -> Interval:
        if e.op in ("&&", "||"):
            left = iv_truth(self.eval(e.left, state))
            # Short-circuit: the right operand runs only sometimes.
            if (e.op == "&&" and left == ZERO) or (e.op == "||" and left == ONE):
                return left
            right_state = dict(state)
            right = iv_truth(self.eval(e.right, right_state))
            if left == BOOL:
                merged = join_states(state, right_state) or {}
            else:
                merged = right_state
            state.clear()
            state.update(merged)
            if e.op == "&&":
                if left == ONE:
                    return right
                return ZERO if right == ZERO else BOOL
            if left == ZERO:
                return right
            return ONE if right == ONE else BOOL
        if e.op == ",":
            self.eval(e.left, state)
            return self.eval(e.right, state)
        left = self.eval(e.left, state)
        right = self.eval(e.right, state)
        self.check_divide(e, e.op, e.right, right)
        return self.binary(e.op, left, right)

    def _assign(self, e: nodes.Assign, state: State) -> Interval:
        value = self.eval(e.value, state)
        if isinstance(e.target, nodes.Identifier):
            name = e.target.name
            if e.op != "=":
                op = _COMPOUND.get(e.op)
                current = self.lookup(name, state)
                if op is not None:
                    self.check_divide(e, op, e.value, value)
                    value = self.binary(op, current, value)
                else:
                    value = TOP  # <<=, >>=, &=, |=, ^=
            self.assign(name, value, state)
            return state.get(name, TOP) if name in self.tracked else value
        # Writes through a[i], p->x, *p: evaluate the target for its index checks and
        # side effects. They can't change tracked variables (none has its address taken).
        self.eval(e.target, state)
        if e.op in ("/=", "%="):
            self.check_divide(e, e.op[0], e.value, value)
        return value

    def exec_stmt(self, stmt: nodes.Node, state: State) -> None:
        """Apply one CFG statement (or a bare condition/step expression) to state."""
        if isinstance(stmt, nodes.DeclStmt):
            for decl in stmt.decls:
                if not isinstance(decl, nodes.VarDecl) or not decl.name:
                    continue
                if decl.init is not None:
                    self.assign(decl.name, self.eval(decl.init, state), state)
                else:
                    # An uninitialized local holds garbage; a redeclaration inside a
                    # loop also forgets the previous iteration's value.
                    state.pop(decl.name, None)
        elif isinstance(stmt, nodes.ExprStmt):
            self.eval(stmt.expr, state)
        elif isinstance(stmt, nodes.Return):
            self.eval(stmt.value, state)
        elif isinstance(stmt, nodes.Expr):
            self.eval(stmt, state)
        # case/default markers, break, continue and empty statements change nothing.

    # -- branch refinement -------------------------------------------------

    def refine(self, cond: nodes.Expr, state: Optional[State], truth: bool) -> Optional[State]:
        """State on the edge where cond evaluates to `truth`; None if that edge is impossible.

        The block has already executed cond, so a condition with side effects
        (`i++ < 5`) can't be re-read here; we keep the state as is for those.
        """
        if state is None:
            return None
        if has_side_effects(cond):
            return dict(state)
        return self._refine(cond, dict(state), truth)

    def _refine(self, cond: nodes.Expr, state: Optional[State], truth: bool) -> Optional[State]:
        if state is None:
            return None
        if isinstance(cond, nodes.Unary) and cond.op == "!":
            return self._refine(cond.operand, state, not truth)
        if isinstance(cond, nodes.Binary) and cond.op == "&&":
            if truth:
                return self._refine(cond.right, self._refine(cond.left, state, True), True)
            # !(a && b) == !a || (a && !b)
            return join_states(self._refine(cond.left, dict(state), False),
                               self._refine(cond.right, self._refine(cond.left, dict(state), True), False))
        if isinstance(cond, nodes.Binary) and cond.op == "||":
            if truth:
                return join_states(self._refine(cond.left, dict(state), True),
                                   self._refine(cond.right, self._refine(cond.left, dict(state), False), True))
            return self._refine(cond.right, self._refine(cond.left, state, False), False)
        if isinstance(cond, nodes.Binary) and cond.op in COMPARISONS:
            op = cond.op if truth else _NEGATE[cond.op]
            state = self._narrow(cond.left, op, cond.right, state)
            state = self._narrow(cond.right, _FLIP[op], cond.left, state)
            if state is None:
                return None
            check = self.binary(op, self.silent().eval(cond.left, dict(state)),
                                self.silent().eval(cond.right, dict(state)))
            return None if check == ZERO else state
        if isinstance(cond, nodes.Identifier) and cond.name in self.tracked:
            current = state.get(cond.name, TOP)
            if truth:
                # x != 0: we can only cut a zero off an end of the range.
                lo = 1 if current.lo == 0 else current.lo
                hi = -1 if current.hi == 0 else current.hi
                if lo > hi:
                    return None
                _store(state, cond.name, Interval(lo, hi))
            else:
                narrowed = current.meet(ZERO)
                if narrowed is None:
                    return None
                _store(state, cond.name, narrowed)
            return state
        truth_value = iv_truth(self.silent().eval(cond, dict(state)))
        if (truth and truth_value == ZERO) or (not truth and truth_value == ONE):
            return None
        return state

    def _narrow(self, lhs: nodes.Expr, op: str, rhs: nodes.Expr, state: Optional[State]) -> Optional[State]:
        """Constrain lhs (if it is a tracked variable) so that `lhs op rhs` holds."""
        if state is None or not isinstance(lhs, nodes.Identifier) or lhs.name not in self.tracked:
            return state
        current = state.get(lhs.name, TOP)
        bound = self.silent().eval(rhs, dict(state))
        lo, hi = current.lo, current.hi
        if op == "<":
            hi = min(hi, bound.hi - 1)
        elif op == "<=":
            hi = min(hi, bound.hi)
        elif op == ">":
            lo = max(lo, bound.lo + 1)
        elif op == ">=":
            lo = max(lo, bound.lo)
        elif op == "==":
            lo, hi = max(lo, bound.lo), min(hi, bound.hi)
        elif op == "!=" and bound.is_const():
            if lo == bound.lo:
                lo += 1
            if hi == bound.lo:
                hi -= 1
        if lo > hi:
            return None
        _store(state, lhs.name, Interval(lo, hi))
        return state


# ---------------------------------------------------------------------------
# Which variables and arrays a function's analysis can rely on
# ---------------------------------------------------------------------------

def tracked_variables(func: nodes.FunctionDef, global_names: Set[str]) -> Dict[str, Interval]:
    """Signed integer locals/params we can follow precisely, mapped to their type range.

    Scopes are matched by name only, so a name that is declared twice, shadows a global,
    has its address taken or is `static` is left out rather than risk mixing up two
    different variables.
    """
    counts: Counter = Counter()
    types: Dict[str, nodes.Type] = {}
    excluded: Set[str] = set()
    for p in func.params:
        if p.name:
            counts[p.name] += 1
            types[p.name] = p.type
    for n in walk(func.body):
        if isinstance(n, nodes.VarDecl) and n.name:
            counts[n.name] += 1
            types[n.name] = n.type
            if n.storage == "static":
                excluded.add(n.name)
        elif isinstance(n, nodes.Unary) and n.op == "&" and isinstance(n.operand, nodes.Identifier):
            # scanf("%d", &x) or init(&x) can change x behind our back.
            excluded.add(n.operand.name)
    excluded |= global_names
    tracked: Dict[str, Interval] = {}
    for name, t in types.items():
        if counts[name] != 1 or name in excluded:
            continue
        if isinstance(t, nodes.BaseType) and t.name in INT_RANGES:
            tracked[name] = INT_RANGES[t.name]
    return tracked


def array_size(t: nodes.Type, constants: Dict[str, int]) -> Optional[int]:
    """Element count of a one-dimensional array type with a constant size."""
    if not isinstance(t, nodes.ArrayType) or isinstance(t.of, nodes.ArrayType):
        return None
    size: Optional[int] = None
    if isinstance(t.size, nodes.IntLiteral):
        size = parse_c_int(t.size.text)
    elif isinstance(t.size, nodes.Identifier):
        size = constants.get(t.size.name)
    return size if size is not None and size > 0 else None


def array_sizes(func: nodes.FunctionDef, global_arrays: Dict[str, int],
                constants: Dict[str, int]) -> Dict[str, int]:
    sizes = dict(global_arrays)
    seen: Set[str] = set()
    ambiguous: Set[str] = set()
    for n in walk(func.body):
        if isinstance(n, nodes.VarDecl) and n.name:
            size = array_size(n.type, constants)
            if n.name in seen or (n.name in sizes and sizes[n.name] != size):
                ambiguous.add(n.name)
            seen.add(n.name)
            if size is not None:
                sizes[n.name] = size
    for name in ambiguous:
        sizes.pop(name, None)
    return sizes


# ---------------------------------------------------------------------------
# The solver
# ---------------------------------------------------------------------------

def _dfs_order(cfg: CFG) -> Tuple[List[BasicBlock], Set[int]]:
    """Reverse postorder of the reachable blocks, and the loop heads (back-edge targets).

    Every cycle in a graph contains at least one DFS back edge, so widening at the
    targets of back edges is enough to make every loop terminate.
    """
    postorder: List[BasicBlock] = []
    heads: Set[int] = set()
    status: Dict[int, int] = {cfg.entry.bid: 1}  # 1 = on the DFS stack, 2 = finished
    stack = [(cfg.entry, iter(cfg.entry.succs))]
    while stack:
        block, succs = stack[-1]
        nxt = next(succs, None)
        if nxt is None:
            stack.pop()
            status[block.bid] = 2
            postorder.append(block)
        elif nxt.bid not in status:
            status[nxt.bid] = 1
            stack.append((nxt, iter(nxt.succs)))
        elif status[nxt.bid] == 1:
            heads.add(nxt.bid)
    return list(reversed(postorder)), heads


@dataclass
class Finding:
    kind: str           # "index", "divide" or "condition"
    node: nodes.Node    # where to report it
    message: str


class IntervalAnalysis:
    MAX_ITERATIONS = 10000  # safety cap; a function that hits it reports nothing
    WIDEN_DELAY = 3         # visits to a loop head before widening starts
    NARROWING_PASSES = 2

    def __init__(self, func: nodes.FunctionDef, global_names: Set[str] = frozenset(),
                 global_arrays: Optional[Dict[str, int]] = None,
                 constants: Optional[Dict[str, int]] = None):
        self.func = func
        self.cfg = build_cfg(func)
        self.constants = dict(constants or {})
        self.tracked = tracked_variables(func, set(global_names))
        self.arrays = array_sizes(func, global_arrays or {}, self.constants)
        self.evaluator = Evaluator(self.tracked, self.constants)
        self.in_states: Dict[int, Optional[State]] = {b.bid: None for b in self.cfg.blocks}
        self.out_states: Dict[int, Optional[State]] = {b.bid: None for b in self.cfg.blocks}
        self.converged = False

    def _edge(self, pred: BasicBlock, succ: BasicBlock) -> Optional[State]:
        out = self.out_states[pred.bid]
        if out is None or pred.branch_cond is None:
            return out
        on_true, on_false = succ is pred.true_succ, succ is pred.false_succ
        if on_true == on_false:
            return out
        return self.evaluator.refine(pred.branch_cond, out, on_true)

    def _incoming(self, block: BasicBlock) -> Optional[State]:
        state: Optional[State] = {} if block is self.cfg.entry else None
        for p in block.preds:
            state = join_states(state, self._edge(p, block))
        return state

    def _transfer(self, block: BasicBlock, state: Optional[State],
                  evaluator: Optional[Evaluator] = None) -> Optional[State]:
        if state is None:
            return None
        ev = evaluator or self.evaluator
        out = dict(state)
        for stmt in block.statements:
            ev.exec_stmt(stmt, out)
        return out

    def run(self) -> "IntervalAnalysis":
        order, heads = _dfs_order(self.cfg)
        visits: Counter = Counter()
        processed: Set[int] = set()
        worklist = deque([self.cfg.entry])
        queued = {self.cfg.entry.bid}
        iterations = 0
        while worklist:
            iterations += 1
            if iterations > self.MAX_ITERATIONS:
                return self
            block = worklist.popleft()
            queued.discard(block.bid)
            old_in = self.in_states[block.bid]
            new_in = self._incoming(block)
            if block.bid in heads:
                visits[block.bid] += 1
                if visits[block.bid] > self.WIDEN_DELAY:
                    new_in = widen_states(old_in, new_in)
            if block.bid in processed and new_in == old_in:
                continue
            first_visit = block.bid not in processed
            processed.add(block.bid)
            self.in_states[block.bid] = new_in
            new_out = self._transfer(block, new_in)
            if first_visit or new_out != self.out_states[block.bid]:
                self.out_states[block.bid] = new_out
                for succ in block.succs:
                    if succ.bid not in queued:
                        worklist.append(succ)
                        queued.add(succ.bid)
        # Descending passes: re-applying the equations to a post-fixpoint stays sound
        # and recovers the bounds widening threw away (e.g. i == 5 after the loop).
        for _ in range(self.NARROWING_PASSES):
            for block in order:
                self.in_states[block.bid] = self._incoming(block)
                self.out_states[block.bid] = self._transfer(block, self.in_states[block.bid])
        self.converged = True
        return self

    # -- reporting ---------------------------------------------------------

    def findings(self) -> List[Finding]:
        """Out-of-range indexes, zero divisors and constant conditions, once converged."""
        if not self.converged:
            return []
        found: List[Finding] = []
        loops = [n for n in walk(self.func.body) if isinstance(n, (nodes.For, nodes.While))]

        def on_index(node: nodes.Index, index: Interval) -> None:
            message = self._index_message(node, index, loops)
            if message:
                found.append(Finding("index", node, message))

        def on_divide(node: nodes.Node, op: str, divisor: nodes.Expr, value: Interval) -> None:
            what = "Division" if op == "/" else "Modulo"
            text = expr_text(divisor)
            if value == ZERO:
                found.append(Finding("divide", node, f"{what} by zero: '{text}' is always 0 here."))
            elif value.is_bounded() and (value.lo == 0 or value.hi == 0):
                # Only a zero at the edge of a bounded range: a zero in the middle could
                # come from a guard like `if (d)` that intervals can't represent.
                found.append(Finding("divide", node,
                                     f"Possible {what.lower()} by zero: '{text}' can be 0 here (range {value})."))

        checker = Evaluator(self.tracked, self.constants, on_index=on_index, on_divide=on_divide)
        for block in self.cfg.blocks:
            state = self.in_states[block.bid]
            if state is None:
                continue  # unreachable
            out = self._transfer(block, state, checker)
            if block.branch_cond is not None:
                message = self._condition_message(block, out)
                if message:
                    found.append(Finding("condition", block.branch_cond, message))
        return found

    def _index_message(self, node: nodes.Index, index: Interval,
                       loops: List[nodes.Stmt]) -> Optional[str]:
        if not isinstance(node.base, nodes.Identifier) or _is_literal(node.index):
            return None  # literal indexes are const-index-out-of-bounds' job
        name = node.base.name
        size = self.arrays.get(name)
        if size is None:
            return None
        text = expr_text(node.index)
        valid = f"'{name}' has {size} elements (valid indexes 0..{size - 1})"
        if index.lo >= size or index.hi < 0:
            return f"Index '{text}' is always out of bounds here (range {index}): {valid}."
        if index.hi >= size and index.hi != INF:
            message = f"Index '{text}' can reach {_fmt(index.hi)} here, but {valid}."
            hint = self._off_by_one_hint(node, size, loops) if index.hi == size else None
            return f"{message} {hint}" if hint else message
        if index.lo < 0 and index.lo != -INF:
            return f"Index '{text}' can be {_fmt(index.lo)} here, but {valid}."
        return None

    def _off_by_one_hint(self, node: nodes.Index, size: int, loops: List[nodes.Stmt]) -> Optional[str]:
        """Point at the `i <= N` loop condition that let the index reach N."""
        if not isinstance(node.index, nodes.Identifier):
            return None
        var = node.index.name
        best = None
        for loop in loops:
            cond = loop.cond
            inside = loop.loc.line <= node.loc.line <= loop.loc.end_line
            if (inside and isinstance(cond, nodes.Binary) and cond.op == "<="
                    and isinstance(cond.left, nodes.Identifier) and cond.left.name == var):
                if best is None or loop.loc.line > best.loc.line:
                    best = loop  # innermost
        if best is None:
            return None
        bound = expr_text(best.cond.right)
        return (f"Off-by-one: the loop on line {best.loc.line} runs while '{var} <= {bound}'; "
                f"did you mean '{var} < {bound}'?")

    def _condition_message(self, block: BasicBlock, state: Optional[State]) -> Optional[str]:
        cond, node = block.branch_cond, block.branch_node
        if isinstance(node, nodes.DoWhile) or has_side_effects(cond):
            return None
        names = sorted({n.name for n in walk(cond) if isinstance(n, nodes.Identifier)
                        and n.name in self.tracked})
        if not names:
            return None  # `if (0)`, `while (1)`, unknown globals: intentional or unknowable
        can_be_true = self.evaluator.refine(cond, state, True) is not None
        can_be_false = self.evaluator.refine(cond, state, False) is not None
        if can_be_true and can_be_false:
            return None
        facts = [f"{n} is {state[n]}" if state[n].is_const() else f"{n} is in {state[n]}"
                 for n in names if n in state]
        why = f" ({', '.join(facts)})" if facts else ""
        text = expr_text(cond)
        if not can_be_true:
            if isinstance(node, nodes.If):
                return f"Condition '{text}' is always false here{why}, so the 'if' body never runs."
            return f"Loop condition '{text}' is false on entry{why}, so the loop body never runs."
        if isinstance(node, nodes.If) and node.else_branch is not None:
            return f"Condition '{text}' is always true here{why}, so the 'else' branch never runs."
        return None


    def describe(self) -> str:
        """Human-readable ranges at the start of each block (`sca ranges`)."""
        lines = []
        for block in self.cfg.blocks:
            state = self.in_states[block.bid]
            first = next((s for s in block.statements if getattr(s, "loc", None)), None)
            where = f" (line {first.loc.line})" if first else ""
            if state is None:
                lines.append(f"Block {block.bid}{where}: unreachable")
                continue
            ranges = ", ".join(f"{name} = {state[name]}" for name in sorted(state)) or "nothing known"
            lines.append(f"Block {block.bid}{where}: {ranges}")
            if block.branch_cond is not None:
                lines.append(f"  branches on '{expr_text(block.branch_cond)}'")
        return "\n".join(lines)


def _unit_context(ast: nodes.TranslationUnit) -> Tuple[Dict[str, int], Set[str], Dict[str, int]]:
    """Integer #defines, global variable names and global array sizes."""
    constants: Dict[str, int] = {}
    for name, text in ast.defines.items():
        value = define_value(text)
        if value is not None:
            constants[name] = value
    global_names: Set[str] = set()
    global_arrays: Dict[str, int] = {}
    for item in ast.items:
        if isinstance(item, nodes.DeclStmt):
            for decl in item.decls:
                if isinstance(decl, nodes.VarDecl) and decl.name:
                    global_names.add(decl.name)
                    size = array_size(decl.type, constants)
                    if size is not None:
                        global_arrays[decl.name] = size
    return constants, global_names, global_arrays


def analyze_function(ast: nodes.TranslationUnit, func: nodes.FunctionDef) -> IntervalAnalysis:
    constants, global_names, global_arrays = _unit_context(ast)
    return IntervalAnalysis(func, global_names, global_arrays, constants).run()


def analyze_unit(ast: nodes.TranslationUnit) -> List[Finding]:
    """Run interval analysis on every function in a translation unit."""
    constants, global_names, global_arrays = _unit_context(ast)
    found: List[Finding] = []
    for item in ast.items:
        if isinstance(item, nodes.FunctionDef):
            analysis = IntervalAnalysis(item, global_names, global_arrays, constants).run()
            found.extend(analysis.findings())
    return found
