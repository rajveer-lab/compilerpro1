"""Core analysis service shared by the CLI and Web backend."""

import os
import re
import time
import tempfile
import shutil
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set

from sca.frontend.runner import run_cparse
from sca.frontend.loader import load_ast
from sca.ast import nodes
from sca.rules.base import Issue
from sca.rules.registry import get_all_rules
from sca.rules.ast_rules import control_depths
from sca.scoring import compute_score, Score, RULE_SEVERITIES
from sca.recommendations import build_recommendations, apply_edits
from sca.analysis.contracts import unit_contracts
from sca.misconceptions import diagnose, misconception_for

MAX_SOURCE_SIZE = 100 * 1024  # 100 KB limit

@dataclass
class AnalysisResult:
    ok: bool = True
    parse_errors: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    metrics: List[Dict[str, Any]] = field(default_factory=list)
    score: Optional[Score] = None
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    projected_score: int = 100
    elapsed_ms: float = 0.0
    contracts: List[Dict[str, Any]] = field(default_factory=list)
    misconceptions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "ok": self.ok,
            "parse_errors": self.parse_errors,
            "diagnostics": self.diagnostics,
            "summary": self.summary,
            "metrics": self.metrics,
            "contracts": self.contracts,
            "misconceptions": self.misconceptions,
            "recommendations": self.recommendations,
            "projected_score": self.projected_score,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.score is not None:
            res["score"] = self.score.to_dict()
        else:
            res["score"] = None
        return res

def parse_suppressions(source: str) -> Dict[int, Set[str]]:
    """Parse inline suppressions (sca-disable and sca-disable-next-line)."""
    suppressions: Dict[int, Set[str]] = {}
    lines = source.splitlines()

    for i, line in enumerate(lines):
        line_num = i + 1

        match1 = re.search(r'sca-disable-next-line[:\s]*([a-z0-9-]+)', line)
        if match1:
            rule_id = match1.group(1)
            target_line = line_num + 1
            if target_line not in suppressions:
                suppressions[target_line] = set()
            suppressions[target_line].add(rule_id)
            if rule_id == "uninitialized":
                suppressions[target_line].add("uninitialized-variable")
            elif rule_id == "uninitialized-variable":
                suppressions[target_line].add("uninitialized")

        match2 = re.search(r'sca-disable[:\s]*([a-z0-9-]+)', line)
        if match2 and not match1:
            rule_id = match2.group(1)
            if line_num not in suppressions:
                suppressions[line_num] = set()
            suppressions[line_num].add(rule_id)
            if rule_id == "uninitialized":
                suppressions[line_num].add("uninitialized-variable")
            elif rule_id == "uninitialized-variable":
                suppressions[line_num].add("uninitialized")

    return suppressions

def compute_metrics(ast: nodes.TranslationUnit, source: Optional[str] = None) -> List[Dict[str, Any]]:
    """Compute per-function metrics: LOC, params, max nesting, cyclomatic complexity."""
    metrics_list = []
    lines = source.splitlines() if source else None

    for item in ast.items:
        if not isinstance(item, nodes.FunctionDef):
            continue

        # 1. LOC
        if lines and item.loc and item.loc.end_line:
            start = max(0, item.loc.line - 1)
            end = min(len(lines), item.loc.end_line)
            loc = sum(1 for ln in lines[start:end] if ln.strip())
        elif item.loc and item.loc.end_line:
            loc = item.loc.end_line - item.loc.line + 1
        else:
            loc = 0

        # 2. Parameters count
        params = len(item.params) if item.params else 0

        # 3. Max nesting depth (same counting as the deep-nesting rule)
        max_depth = max((depth for _, depth in control_depths(item.body)), default=0)

        # 4. Cyclomatic complexity
        complexity = 1
        def calc_complexity(n: Optional[nodes.Node]):
            nonlocal complexity
            if not n:
                return
            if isinstance(n, (nodes.If, nodes.While, nodes.For, nodes.DoWhile)):
                complexity += 1
            elif isinstance(n, nodes.Binary) and n.op in ('&&', '||'):
                complexity += 1
            elif isinstance(n, nodes.Ternary):
                complexity += 1
            elif isinstance(n, nodes.Case):
                complexity += 1

            if hasattr(n, '__dataclass_fields__'):
                for field_name in n.__dataclass_fields__:
                    val = getattr(n, field_name)
                    if isinstance(val, nodes.Node):
                        calc_complexity(val)
                    elif isinstance(val, list):
                        for el in val:
                            if isinstance(el, nodes.Node):
                                calc_complexity(el)

        calc_complexity(item.body)

        metrics_list.append({
            "function": item.name,
            # Where the definition starts, so the web UI can jump to it from the table.
            "line": item.loc.line if item.loc else None,
            "col": item.loc.col if item.loc else None,
            "loc": loc,
            "params": params,
            "max_nesting": max_depth,
            "cyclomatic": complexity,
        })

    return metrics_list

def analyze_source(
    code: str,
    filename: str = "main.c",
    options: Optional[Dict[str, Any]] = None
) -> AnalysisResult:
    """Analyze C source code string and return structured AnalysisResult."""
    start_time = time.time()
    options = options or {}

    # Check payload size limit
    code_bytes = code.encode("utf-8")
    if len(code_bytes) > MAX_SOURCE_SIZE:
        raise ValueError(f"Payload size ({len(code_bytes)} bytes) exceeds limit of {MAX_SOURCE_SIZE} bytes.")

    temp_dir = tempfile.mkdtemp(prefix="sca_run_")
    temp_file = os.path.join(temp_dir, os.path.basename(filename) or "main.c")

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code)

        cparse_data = run_cparse(temp_file)

        # Check for parse/syntax errors
        errors = cparse_data.get("errors", [])
        if "unit" not in cparse_data or cparse_data["unit"] is None or errors:
            formatted_errors = []
            for err in errors:
                formatted_errors.append({
                    "line": err.get("line", 1),
                    "col": err.get("col", 1),
                    "message": err.get("message", "Syntax error"),
                })
            elapsed = round((time.time() - start_time) * 1000, 2)
            return AnalysisResult(
                ok=True,
                parse_errors=formatted_errors,
                diagnostics=[],
                summary={"error": len(formatted_errors), "warning": 0, "info": 0},
                metrics=[],
                score=None,
                recommendations=[],
                projected_score=100,
                elapsed_ms=elapsed,
            )

        ast = load_ast(cparse_data)
        rules = get_all_rules()

        raw_issues: List[Issue] = []
        for r in rules:
            # One broken rule must not take the whole analysis down (SPEC §5).
            try:
                raw_issues.extend(r.analyze(ast, filename))
            except Exception as exc:
                raw_issues.append(Issue(
                    file=filename,
                    line=1,
                    col=1,
                    message=f"Rule {type(r).__name__} failed: {exc}",
                    rule_id="internal-error",
                ))

        # Apply inline suppressions
        suppressions = parse_suppressions(code)

        enabled_rules: Optional[List[str]] = options.get("rule")
        disabled_rules: Optional[List[str]] = options.get("disable")

        filtered_issues: List[Issue] = []
        for issue in raw_issues:
            # Check suppression
            if issue.line in suppressions:
                if issue.rule_id in suppressions[issue.line]:
                    continue
                # Handle uninitialized alias
                if issue.rule_id == "uninitialized" and "uninitialized-variable" in suppressions[issue.line]:
                    continue

            # Check rule filter flags
            if enabled_rules and issue.rule_id not in enabled_rules:
                continue
            if disabled_rules and issue.rule_id in disabled_rules:
                continue

            filtered_issues.append(issue)

        # Sort issues by line and column
        filtered_issues.sort(key=lambda x: (x.line, x.col, x.rule_id))

        # Build diagnostics list
        diagnostics = []
        summary = {"error": 0, "warning": 0, "info": 0}

        for issue in filtered_issues:
            severity = RULE_SEVERITIES.get(issue.rule_id, "warning")
            summary[severity] = summary.get(severity, 0) + 1

            diag = {
                "file": issue.file,
                "line": issue.line,
                "col": issue.col,
                "end_line": getattr(issue, "end_line", issue.line),
                "end_col": getattr(issue, "end_col", issue.col),
                "message": issue.message,
                "rule_id": issue.rule_id,
                "severity": severity,
            }
            misconception = misconception_for(issue.rule_id)
            if misconception is not None:
                diag["misconception"] = misconception.id
            diagnostics.append(diag)

        # Compute metrics
        metrics = compute_metrics(ast, source=code)

        # Inferred input contracts (shared with the contract-violation rule's run)
        try:
            contracts = [fc.to_dict() for fc in unit_contracts(ast)]
        except Exception:
            contracts = []

        # Compute score
        score = compute_score(filtered_issues)

        # Build recommendations
        recs = build_recommendations(diagnostics, code, ast_items=ast.items if ast else None)
        recommendations = [r.to_dict() for r in recs]

        # Calculate projected score if all safe fixes were applied. Work from the penalty
        # total: score.value is floored at 0, so adding gains to it would overstate the
        # result for a file with more than 100 penalty points.
        safe_gain = sum(r.score_gain for r in recs if r.safety == "safe" and r.edits)
        total_penalty = sum(score.deductions.values())
        projected_score = max(0, min(100, 100 - max(0, total_penalty - safe_gain)))

        elapsed = round((time.time() - start_time) * 1000, 2)

        return AnalysisResult(
            ok=True,
            parse_errors=[],
            diagnostics=diagnostics,
            summary=summary,
            metrics=metrics,
            score=score,
            recommendations=recommendations,
            projected_score=projected_score,
            elapsed_ms=elapsed,
            contracts=contracts,
            misconceptions=diagnose(diagnostics),
        )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def analyze_file(filepath: str, options: Optional[Dict[str, Any]] = None) -> AnalysisResult:
    """Analyze a C file on disk."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()
    return analyze_source(code, filename=filepath, options=options)
