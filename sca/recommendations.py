"""Recommendation engine for code quality analyzer diagnostics."""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Union
from sca.scoring import DEFAULT_WEIGHTS

@dataclass
class Edit:
    line_start: int
    line_end: int
    expected_old: List[str]
    new: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_start": self.line_start,
            "line_end": self.line_end,
            "expected_old": self.expected_old,
            "new": self.new,
        }

@dataclass
class Recommendation:
    id: str
    rule_id: str
    line: int
    col: int
    title: str
    explanation: str
    priority: int
    score_gain: int
    safety: str  # "safe", "review", or "manual"
    edits: List[Edit] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "line": self.line,
            "col": self.col,
            "title": self.title,
            "explanation": self.explanation,
            "priority": self.priority,
            "score_gain": self.score_gain,
            "safety": self.safety,
            "edits": [e.to_dict() for e in self.edits],
        }

def apply_edits(source: str, edits: List[Union[Edit, Dict[str, Any]]]) -> str:
    """Apply line-based edits to source code. Edits are applied safely from bottom to top."""
    lines = source.splitlines()

    norm_edits = []
    for e in edits:
        if isinstance(e, dict):
            norm_edits.append((
                e["line_start"],
                e["line_end"],
                e.get("expected_old", []),
                e.get("new", [])
            ))
        else:
            norm_edits.append((
                e.line_start,
                e.line_end,
                e.expected_old,
                e.new
            ))

    # Sort descending by start line so modifying lower lines doesn't shift earlier line numbers
    norm_edits.sort(key=lambda x: (x[0], x[1]), reverse=True)

    for line_start, line_end, expected_old, new_lines in norm_edits:
        # Check expected_old
        if expected_old:
            actual_old = lines[line_start - 1 : line_end]
            if actual_old != expected_old:
                raise ValueError(
                    f"Edit conflict: expected {expected_old} at lines {line_start}..{line_end}, got {actual_old}"
                )

        if line_end == line_start - 1:
            # Insertion before line_start
            idx = line_start - 1
            lines[idx:idx] = new_lines
        else:
            # Replacement or deletion
            idx_start = line_start - 1
            idx_end = line_end
            lines[idx_start:idx_end] = new_lines

    result = "\n".join(lines)
    if source.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result

def extract_symbol_name(message: str) -> Optional[str]:
    """Extract symbol name enclosed in single quotes from issue message."""
    m = re.search(r"'([^']+)'", message)
    return m.group(1) if m else None

def has_side_effect_ops(text: str) -> bool:
    """True if the text contains ++ or -- (deleting it would drop the side effect)."""
    return "++" in text or "--" in text

def mentioned_elsewhere(name: str, lines: List[str], line: int) -> bool:
    """True if `name` appears as a whole word on any line other than `line` (1-based)."""
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    return any(pattern.search(text) for i, text in enumerate(lines, start=1) if i != line)

def build_recommendations(
    diagnostics: List[Dict[str, Any]],
    source: str,
    ast_items: Optional[List[Any]] = None
) -> List[Recommendation]:
    """Generate prioritized actionable recommendations for each diagnostic."""
    lines = source.splitlines()
    num_lines = len(lines)
    recommendations: List[Recommendation] = []
    used_edit_lines: Set[int] = set()

    for idx, diag in enumerate(diagnostics):
        rule_id = diag.get("rule_id", "")
        line = diag.get("line", 1)
        col = diag.get("col", 1)
        message = diag.get("message", "")
        symbol = extract_symbol_name(message)
        weight = DEFAULT_WEIGHTS.get(rule_id, 2)
        score_gain = weight
        priority = weight

        rec_id = f"rec-{idx + 1}"
        line_text = lines[line - 1] if 1 <= line <= num_lines else ""

        title = f"Fix {rule_id}"
        explanation = message
        safety = "manual"
        edits: List[Edit] = []

        # 1. Unused Variable
        if rule_id == "unused-variable":
            var_name = symbol or "variable"
            title = f"Remove unused variable '{var_name}'"
            explanation = f"Variable '{var_name}' is declared but never read, so it adds clutter."
            stripped = line_text.strip()
            # Only safe to delete if line solely declares this variable without function calls
            # or ++/--, and the name appears nowhere else (a later `x = 10;` would otherwise
            # be left assigning to an undeclared variable).
            is_simple_decl = (
                stripped.endswith(";") and
                var_name in stripped and
                "," not in stripped and
                "(" not in stripped and
                not has_side_effect_ops(stripped) and
                not mentioned_elsewhere(var_name, lines, line)
            )
            if is_simple_decl and line not in used_edit_lines:
                safety = "safe"
                edits = [Edit(line_start=line, line_end=line, expected_old=[line_text], new=[])]
                used_edit_lines.add(line)
            else:
                safety = "manual"

        # 2. Empty Body
        elif rule_id == "empty-body":
            title = "Remove stray semicolon after control statement"
            explanation = "The semicolon creates an empty statement body, altering intended program logic."
            safety = "review"
            stripped = line_text.strip()
            if stripped.endswith(");") and line not in used_edit_lines:
                last_idx = line_text.rfind(");")
                new_line = line_text[:last_idx] + ")" + line_text[last_idx + 2:]
                edits = [Edit(line_start=line, line_end=line, expected_old=[line_text], new=[new_line])]
                used_edit_lines.add(line)
            elif "; }" in line_text and line not in used_edit_lines:
                new_line = line_text.replace("; }", "; { ; } }", 1)
                edits = [Edit(line_start=line, line_end=line, expected_old=[line_text], new=[new_line])]
                used_edit_lines.add(line)
            else:
                safety = "manual"

        # 3. Assignment In Condition
        elif rule_id == "assignment-in-condition":
            title = "Change assignment '=' to comparison '=='"
            explanation = "Using '=' in a condition performs an assignment rather than testing equality. Wrap in extra parentheses if intentional."
            safety = "review"
            new_line = re.sub(r'(?<![=!<>\+\-\*/%&|^])=(?!=)', '==', line_text, count=1)
            if new_line != line_text and line not in used_edit_lines:
                edits = [Edit(line_start=line, line_end=line, expected_old=[line_text], new=[new_line])]
                used_edit_lines.add(line)
            else:
                safety = "manual"

        # 4. Missing Return
        elif rule_id == "missing-return":
            func_name = symbol or "function"
            title = f"Add return statement to function '{func_name}'"
            explanation = f"Function '{func_name}' has code paths reaching exit without returning a value."
            safety = "review"
            end_line = diag.get("end_line", line)
            if end_line == line and ast_items:
                for item in ast_items:
                    if getattr(item, "name", None) == func_name and hasattr(item, "loc"):
                        end_line = item.loc.end_line
                        break
            if end_line <= line:
                for ln_idx in range(line, num_lines):
                    if lines[ln_idx].strip() == "}":
                        end_line = ln_idx + 1
                        break

            if end_line > line and end_line not in used_edit_lines:
                indent = "    "
                edits = [Edit(line_start=end_line, line_end=end_line - 1, expected_old=[], new=[f"{indent}return 0;"])]
                used_edit_lines.add(end_line)
            else:
                safety = "manual"

        # 5. Uninitialized Variable
        elif rule_id in ("uninitialized", "uninitialized-variable"):
            var_name = symbol or "variable"
            title = f"Initialize variable '{var_name}' at declaration"
            explanation = f"Variable '{var_name}' is read before it is definitely assigned on all execution paths."
            safety = "review"
            decl_line = None
            decl_text = None
            decl_pattern = re.compile(
                r'^\s*(?:const\s+)?(?:int|char|float|double|long|short|unsigned)\s+(?:\*+)?\s*' +
                re.escape(var_name) +
                r'\s*;'
            )
            for ln in range(line - 1, 0, -1):
                txt = lines[ln - 1]
                if decl_pattern.match(txt) and "," not in txt:
                    decl_line = ln
                    decl_text = txt
                    break

            if decl_line and decl_line not in used_edit_lines:
                init_val = "NULL" if "*" in decl_text else "0"
                new_text = decl_text.replace(";", f" = {init_val};", 1)
                edits = [Edit(line_start=decl_line, line_end=decl_line, expected_old=[decl_text], new=[new_text])]
                used_edit_lines.add(decl_line)
            else:
                safety = "manual"

        # 6. Unreachable Code
        elif rule_id == "unreachable-code":
            title = "Delete unreachable statements"
            explanation = "This code cannot be reached because preceding statements already returned or exited."
            safety = "review"
            stripped = line_text.strip()
            if stripped.endswith(";") and not stripped.startswith("}") and line not in used_edit_lines:
                edits = [Edit(line_start=line, line_end=line, expected_old=[line_text], new=[])]
                used_edit_lines.add(line)
            else:
                safety = "manual"

        # 7. Dead Store
        elif rule_id == "dead-store":
            var_name = symbol or "variable"
            title = f"Remove dead store to '{var_name}'"
            explanation = f"The value assigned to '{var_name}' is never read before being overwritten or function exit."
            stripped = line_text.strip()
            # Only a plain `name = <expr>;` statement: a declaration line (any type, e.g.
            # `long t = 0;`) must stay, and `x = i++;` would lose the increment.
            is_simple_assign = (
                re.fullmatch(rf"{re.escape(var_name)}\s*=\s*[^;=(]*;", stripped) is not None and
                not has_side_effect_ops(stripped)
            )
            if is_simple_assign and line not in used_edit_lines:
                safety = "safe"
                edits = [Edit(line_start=line, line_end=line, expected_old=[line_text], new=[])]
                used_edit_lines.add(line)
            else:
                safety = "manual"

        # 8. Unused Parameter
        elif rule_id == "unused-parameter":
            param_name = symbol or "param"
            title = f"Prefix unused parameter '{param_name}' with '_'"
            explanation = f"Parameter '{param_name}' is never referenced. Prefix with '_' to mark it intentionally unused."
            safety = "review"
            if param_name and re.search(r'\b' + re.escape(param_name) + r'\b', line_text) and line not in used_edit_lines:
                new_line = re.sub(r'\b' + re.escape(param_name) + r'\b', f"_{param_name}", line_text, count=1)
                edits = [Edit(line_start=line, line_end=line, expected_old=[line_text], new=[new_line])]
                used_edit_lines.add(line)
            else:
                safety = "manual"

        # 9. Unsafe Function
        elif rule_id == "unsafe-function":
            fn_name = symbol
            if not fn_name:
                for b in ["gets", "strcpy", "strcat", "sprintf", "scanf"]:
                    if b in message:
                        fn_name = b
                        break

            if fn_name == "gets" and "gets(" in line_text and line not in used_edit_lines:
                m_buf = re.search(r'gets\s*\(\s*([a-zA-Z0-9_]+)\s*\)', line_text)
                if m_buf:
                    buf_name = m_buf.group(1)
                    title = f"Replace 'gets({buf_name})' with 'fgets'"
                    explanation = f"'gets' lacks bounds checking and causes buffer overflows. Use fgets({buf_name}, sizeof({buf_name}), stdin) instead."
                    safety = "review"
                    new_line = re.sub(
                        r'gets\s*\(\s*' + re.escape(buf_name) + r'\s*\)',
                        f"fgets({buf_name}, sizeof({buf_name}), stdin)",
                        line_text
                    )
                    edits = [Edit(line_start=line, line_end=line, expected_old=[line_text], new=[new_line])]
                    used_edit_lines.add(line)
                else:
                    title = "Replace banned 'gets' function"
                    explanation = "Use 'fgets(buffer, sizeof buffer, stdin)' instead of unsafe 'gets'."
                    safety = "manual"
            else:
                title = f"Replace unsafe '{fn_name or 'function'}'"
                if fn_name == "strcpy":
                    explanation = "Replace strcpy(dest, src) with snprintf(dest, sizeof(dest), \"%s\", src) or strncpy."
                elif fn_name == "strcat":
                    explanation = "Replace strcat(dest, src) with strncat(dest, src, sizeof(dest) - strlen(dest) - 1)."
                elif fn_name == "sprintf":
                    explanation = "Replace sprintf(buf, ...) with snprintf(buf, sizeof(buf), ...)."
                elif fn_name == "scanf":
                    explanation = "Specify maximum field width in scanf format (e.g. '%10s' instead of bare '%s')."
                else:
                    explanation = "Use bounds-checked alternative to prevent buffer overflows."
                safety = "manual"

        # 10. Shadowed Variable
        elif rule_id == "shadowed-variable":
            var_name = symbol or "variable"
            title = f"Rename shadowed variable '{var_name}'"
            explanation = f"Variable '{var_name}' shadows an outer declaration. Rename it (e.g. '{var_name}_inner') to clarify scope."
            safety = "manual"

        # 11. Const Index Out Of Bounds
        elif rule_id == "const-index-out-of-bounds":
            title = "Correct out-of-bounds array index"
            explanation = "Index is outside declared array bounds. Adjust the index or enlarge array dimensions."
            safety = "manual"

        # 12. Unused Function
        elif rule_id == "unused-function":
            fn_name = symbol or "function"
            title = f"Remove unused static function '{fn_name}'"
            explanation = f"Static function '{fn_name}' is never called within this file. Remove it or add callers."
            safety = "manual"

        # 13. Magic Number
        elif rule_id == "magic-number":
            num_val = symbol or "literal"
            title = f"Replace magic number '{num_val}' with a named constant"
            explanation = f"Replace literal '{num_val}' with a descriptive #define macro or const variable."
            safety = "manual"

        # 14. Naming Convention
        elif rule_id == "naming-convention":
            id_name = symbol or "identifier"
            title = f"Rename '{id_name}' according to convention"
            explanation = f"Use snake_case for functions and variables, and UPPER_CASE for constants."
            safety = "manual"

        # 15. Complexity & Function Structure Metrics
        elif rule_id == "high-complexity":
            title = "Reduce cyclomatic complexity"
            explanation = "Refactor logic by extracting helper functions and utilizing guard clauses with early returns."
            safety = "manual"

        elif rule_id == "function-too-long":
            title = "Break up long function"
            explanation = "Decompose function exceeding 50 lines into smaller, modular subroutines."
            safety = "manual"

        elif rule_id == "deep-nesting":
            title = "Flatten deeply nested control blocks"
            explanation = "Reduce nesting level (limit 4) by inverting conditions and returning early."
            safety = "manual"

        elif rule_id == "too-many-params":
            title = "Bundle parameters into a struct"
            explanation = "Reduce parameter count (limit 5) by grouping related arguments into a context struct."
            safety = "manual"

        # Construct Recommendation
        rec = Recommendation(
            id=rec_id,
            rule_id=rule_id,
            line=line,
            col=col,
            title=title,
            explanation=explanation,
            priority=priority,
            score_gain=score_gain,
            safety=safety,
            edits=edits,
        )
        recommendations.append(rec)

    # Sort recommendations by priority (highest penalty first), then line
    recommendations.sort(key=lambda r: (-r.priority, r.line, r.col))

    # Re-number IDs sequentially after sorting for stable display
    for i, r in enumerate(recommendations):
        r.id = f"rec-{i + 1}"

    return recommendations
