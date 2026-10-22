from typing import List, Set
from sca.rules.base import Rule, Issue
from sca.ast import nodes
from sca.analysis.cfg import build_cfg, reachable_blocks
from sca.analysis.liveness import LivenessAnalysis
from sca.rules.uninitialized import extract_detailed_usage, address_taken_names, is_scalar

class DeadStoreRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                issues.extend(self.analyze_func(item, filename))
        return issues
        
    def analyze_func(self, func: nodes.FunctionDef, filename: str) -> List[Issue]:
        issues = []
        cfg = build_cfg(func)
        
        # Only check local variables
        local_vars = set()
        def find_locals(n: nodes.Node):
            if not n: return
            if (isinstance(n, nodes.VarDecl) and not getattr(n, 'is_global', False) and n.name
                    and n.storage != 'static' and is_scalar(n.type)):
                local_vars.add(n.name)
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node):
                        find_locals(val)
                    elif isinstance(val, list):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                find_locals(i)
        find_locals(func.body)
        # A pointer to x may read it later (int *p = &x; x = 2; use(*p)).
        local_vars -= address_taken_names(func.body)
        # Variables that are never read at all are reported once by unused-variable;
        # flagging every store to them as well would double-count the same problem.
        read_names = {name for name, _ in extract_detailed_usage(func.body)[0]}
        local_vars &= read_names

        liveness = LivenessAnalysis(cfg)
        liveness.run()
        reachable = reachable_blocks(cfg)

        for b in cfg.blocks:
            if b.bid not in reachable:
                continue  # already reported by unreachable-code
            live = set(liveness.out_sets[b.bid])
            for stmt in reversed(b.statements):
                r, w = extract_detailed_usage(stmt)
                
                # Check dead stores
                for var in w:
                    if var in local_vars and var not in live:
                        # Dead store!
                        # Find the exact location of the write in this stmt
                        # extract_detailed_usage doesn't return write locations, so we just use stmt location
                        loc = stmt.loc
                        if loc:
                            issues.append(Issue(
                                file=filename,
                                line=loc.line,
                                col=loc.col,
                                message=f"Value assigned to '{var}' is never read (dead store).",
                                rule_id="dead-store"
                            ))
                            
                # Update live set: remove writes, add reads
                live -= w
                for name, _ in r:
                    live.add(name)
                    
        return issues
