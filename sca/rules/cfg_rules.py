from typing import List, Set
from sca.rules.base import Rule, Issue
from sca.ast import nodes
from sca.analysis.cfg import build_cfg, BasicBlock, reachable_blocks

class UnreachableCodeRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                cfg = build_cfg(item)
                reachable = reachable_blocks(cfg)

                # Find connected components of unreachable blocks
                unreachable_blocks = [b for b in cfg.blocks if b.bid not in reachable and b.statements]
                visited_unreachable = set()
                
                for b in unreachable_blocks:
                    if b.bid in visited_unreachable:
                        continue
                        
                    # New region
                    region = []
                    wq = [b]
                    while wq:
                        curr = wq.pop()
                        if curr.bid not in visited_unreachable:
                            visited_unreachable.add(curr.bid)
                            region.append(curr)
                            for s in curr.succs:
                                if s.bid not in reachable:
                                    wq.append(s)
                            for p in curr.preds:
                                if p.bid not in reachable:
                                    wq.append(p)
                                    
                    # Find the first statement in the region (lowest line number)
                    first_stmt = None
                    for rb in region:
                        if rb.statements:
                            stmt = rb.statements[0]
                            if hasattr(stmt, 'loc') and stmt.loc:
                                if not first_stmt or stmt.loc.line < first_stmt.loc.line:
                                    first_stmt = stmt
                    
                    if first_stmt and first_stmt.loc:
                        issues.append(Issue(
                            file=filename,
                            line=first_stmt.loc.line,
                            col=first_stmt.loc.col,
                            message="Code is unreachable.",
                            rule_id="unreachable-code"
                        ))
                        
        return issues


class MissingReturnRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                if item.name == 'main':
                    continue
                # Pointer return types have no `name`; only a plain `void` is exempt.
                if isinstance(item.return_type, nodes.BaseType) and item.return_type.name == 'void':
                    continue

                cfg = build_cfg(item)
                reachable = reachable_blocks(cfg)
                # Are there any reachable predecessors to exit that are NOT Return statements?
                # (Unreachable ones, e.g. the empty merge block after an if/else that returns
                # on both branches, never actually fall off the end.)
                missing = False
                for p in cfg.exit.preds:
                    if p.bid not in reachable:
                        continue
                    if not p.statements:
                        missing = True
                        break
                    last_stmt = p.statements[-1]
                    if not isinstance(last_stmt, nodes.Return):
                        missing = True
                        break
                        
                if missing:
                    issues.append(Issue(
                        file=filename,
                        line=item.loc.line,
                        col=item.loc.col,
                        message=f"Non-void function '{item.name}' reaches end of control flow without returning a value.",
                        rule_id="missing-return"
                    ))
                    
        return issues


class HighComplexityRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                complexity = 1
                
                def count(n: nodes.Node):
                    nonlocal complexity
                    if not n: return
                    
                    if isinstance(n, (nodes.If, nodes.While, nodes.For, nodes.DoWhile)):
                        complexity += 1
                    elif isinstance(n, nodes.Binary) and n.op in ('&&', '||'):
                        complexity += 1
                    elif isinstance(n, nodes.Ternary):
                        complexity += 1
                    elif isinstance(n, nodes.Case):
                        complexity += 1
                        
                    if hasattr(n, '__dataclass_fields__'):
                        for field in n.__dataclass_fields__:
                            val = getattr(n, field)
                            if isinstance(val, nodes.Node):
                                count(val)
                            elif isinstance(val, list):
                                for i in val:
                                    if isinstance(i, nodes.Node):
                                        count(i)
                                        
                count(item.body)
                if complexity > 10:
                    issues.append(Issue(
                        file=filename,
                        line=item.loc.line,
                        col=item.loc.col,
                        message=f"Cyclomatic complexity of function '{item.name}' is {complexity} (exceeds limit of 10).",
                        rule_id="high-complexity"
                    ))
                    
        return issues
