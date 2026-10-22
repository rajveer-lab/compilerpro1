"""Misconception diagnosis: link diagnostics to the beginner misunderstanding behind them.

A diagnostic says *what* is wrong; for a learner the more useful question is *why* they
wrote it. Each entry below names a common novice misconception about C (in the spirit
of the misconception catalogues in computing-education research, e.g. du Boulay 1986,
Sorva 2012), explains the correct mental model, and says how to fix the code.

The web UI keeps a per-browser profile of how often each misconception shows up;
`sca analyze --explain` adds the misconception to each diagnostic in the JSON output.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Misconception:
    id: str
    title: str          # the wrong belief, in the learner's words
    explanation: str    # the correct mental model
    fix: str            # what to do in the code

    def to_dict(self) -> Dict[str, str]:
        return {"id": self.id, "title": self.title,
                "explanation": self.explanation, "fix": self.fix}


MISCONCEPTIONS: Dict[str, Misconception] = {m.id: m for m in [
    Misconception(
        "array-index-n",
        "An array of size N has an index N",
        "A C array declared with N elements has indexes 0 to N-1. Index N is one past the "
        "end: reading it gives garbage and writing it silently overwrites other memory.",
        "Loop with 'i < N', not 'i <= N', and check an index before using it.",
    ),
    Misconception(
        "auto-zero",
        "Variables start at 0 automatically",
        "Local variables hold whatever was left in memory until you assign them. Only "
        "global and static variables start at 0.",
        "Give every local variable a value when you declare it, e.g. 'int sum = 0;'.",
    ),
    Misconception(
        "assign-compares",
        "'=' compares two values",
        "'=' stores a value and '==' compares. 'if (x = 5)' sets x to 5 and is always true.",
        "Use '==' in conditions. If you really mean to assign, wrap it in extra parentheses.",
    ),
    Misconception(
        "divisor-has-value",
        "The divisor will obviously have a value",
        "Dividing by zero is undefined in C: the program may crash or give nonsense, and "
        "the compiler does not check it. A counter that is never updated stays 0.",
        "Guard divisions, e.g. 'if (count != 0) avg = total / count;'.",
    ),
    Misconception(
        "variable-changes-itself",
        "A variable will change on its own",
        "A condition is checked against the variable's current value. If no statement "
        "changes the variable, the condition gives the same answer every time.",
        "Check that some statement actually updates the variable the condition depends on.",
    ),
    Misconception(
        "code-after-return",
        "Code after 'return' still runs",
        "'return' leaves the function immediately ('break' and 'continue' also jump away), "
        "so statements after it never execute.",
        "Move the code before the return, or delete it.",
    ),
    Misconception(
        "implicit-return",
        "A function returns its last value automatically",
        "A non-void C function must say 'return value;' on every path. Printing a value is "
        "not returning it, and a path that falls off the end hands the caller garbage.",
        "Add a return at the end of every path, including after loops and in else branches.",
    ),
    Misconception(
        "semicolon-harmless",
        "A ';' after if/while is harmless",
        "'if (x > 0);' ends the if right there: the ';' is its (empty) body, so the block "
        "below always runs. 'while (...);' can loop forever.",
        "Remove the semicolon directly after the condition.",
    ),
    Misconception(
        "redeclare-updates",
        "Re-declaring a variable updates the outer one",
        "'int x = 5;' inside a block creates a new, separate x. The outer x is untouched "
        "and the new one disappears when the block ends.",
        "Assign to the existing variable ('x = 5;') instead of declaring it again.",
    ),
    Misconception(
        "strings-grow",
        "Strings grow to fit what you copy into them",
        "A char array has a fixed size. gets, strcpy, strcat and sprintf keep writing past "
        "the end if the text is too long: a buffer overflow, a classic security hole.",
        "Use bounded versions (fgets, snprintf, strncat) and size buffers for the longest input.",
    ),
    Misconception(
        "function-checks-inputs",
        "A function will check its own inputs",
        "A function only works for the inputs it was written for. If it indexes an array or "
        "divides using a parameter without checking it, the caller must pass safe values.",
        "Pass a value inside the function's contract, or add a check at the top of the function.",
    ),
]}

# rule id -> misconception id
RULE_MISCONCEPTIONS: Dict[str, str] = {
    "index-out-of-range": "array-index-n",
    "const-index-out-of-bounds": "array-index-n",
    "uninitialized": "auto-zero",
    "uninitialized-variable": "auto-zero",
    "assignment-in-condition": "assign-compares",
    "division-by-zero": "divisor-has-value",
    "constant-condition": "variable-changes-itself",
    "unreachable-code": "code-after-return",
    "missing-return": "implicit-return",
    "empty-body": "semicolon-harmless",
    "shadowed-variable": "redeclare-updates",
    "unsafe-function": "strings-grow",
    "contract-violation": "function-checks-inputs",
}


def misconception_for(rule_id: str) -> Optional[Misconception]:
    mid = RULE_MISCONCEPTIONS.get(rule_id)
    return MISCONCEPTIONS.get(mid) if mid else None


def diagnose(diagnostics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Misconceptions behind a list of diagnostics, most frequent first.

    Each entry is the misconception plus the lines and rules that point to it.
    """
    found: Dict[str, Dict[str, Any]] = {}
    for d in diagnostics:
        m = misconception_for(d.get("rule_id", ""))
        if m is None:
            continue
        entry = found.setdefault(m.id, {**m.to_dict(), "lines": [], "rule_ids": []})
        if d.get("line") not in entry["lines"]:
            entry["lines"].append(d.get("line"))
        if d["rule_id"] not in entry["rule_ids"]:
            entry["rule_ids"].append(d["rule_id"])
    return sorted(found.values(), key=lambda e: (-len(e["lines"]), min(e["lines"])))
