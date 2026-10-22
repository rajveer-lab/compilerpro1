from typing import List, Set, Tuple, Dict
from sca.rules.base import Rule, Issue
from sca.ast import nodes
from sca.analysis.cfg import build_cfg, BasicBlock
from sca.analysis.dataflow import DataflowAnalysis

def extract_detailed_usage(node: nodes.Node):
    reads: List[Tuple[str, nodes.Loc]] = []
    writes: Set[str] = set()
    
    def visit(n: nodes.Node, is_lvalue: bool = False):
        if not n: return
        
        if isinstance(n, nodes.Identifier):
            if is_lvalue:
                writes.add(n.name)
            else:
                reads.append((n.name, n.loc))
        elif isinstance(n, nodes.Assign):
            if n.op == '=':
                visit(n.value, False)
                visit(n.target, True)
            else:
                visit(n.value, False)
                visit(n.target, False)
                visit(n.target, True)
        elif isinstance(n, (nodes.Unary, nodes.Postfix)):
            if n.op in ('INC_OP', 'DEC_OP', '++', '--'):
                visit(n.operand, False)
                visit(n.operand, True)
            else:
                visit(n.operand, False)
        elif isinstance(n, nodes.VarDecl):
            if n.init:
                visit(n.init, False)
                if n.name:
                    writes.add(n.name)
            else:
                pass # no write for uninit decl
        else:
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node):
                        visit(val, False)
                    elif isinstance(val, list):
                        for item in val:
                            if isinstance(item, nodes.Node):
                                visit(item, False)
                                
    visit(node, False)
    return reads, writes

def is_scalar(t: nodes.Type) -> bool:
    """Plain values and pointers. Arrays, structs and unknown typedefs are not tracked."""
    return isinstance(t, (nodes.BaseType, nodes.PointerType))

def address_taken_names(node: nodes.Node) -> Set[str]:
    """Names of variables whose address is taken with `&x` anywhere under node."""
    names: Set[str] = set()

    def visit(n: nodes.Node):
        if not n: return
        if isinstance(n, nodes.Unary) and n.op == '&' and isinstance(n.operand, nodes.Identifier):
            names.add(n.operand.name)
        if hasattr(n, '__dataclass_fields__'):
            for field in n.__dataclass_fields__:
                val = getattr(n, field)
                if isinstance(val, nodes.Node):
                    visit(val)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, nodes.Node):
                            visit(item)

    visit(node)
    return names

class UninitDataflow(DataflowAnalysis):
    def __init__(self, cfg, uninit_locals: Set[str]):
        super().__init__(cfg, forward=True)
        self.uninit_locals = uninit_locals
        
        self.kill: Dict[int, Set[str]] = {}
        for b in cfg.blocks:
            b_kill = set()
            for stmt in b.statements:
                _, w = extract_detailed_usage(stmt)
                b_kill.update(w)
            self.kill[b.bid] = b_kill
            
        # Entry block IN set
        self.in_sets[cfg.entry.bid] = set(uninit_locals)
        self.out_sets[cfg.entry.bid] = set(uninit_locals) - self.kill[cfg.entry.bid]
        
    def meet(self, block: BasicBlock) -> Set[str]:
        if block.bid == self.cfg.entry.bid:
            return set(self.uninit_locals)
        res = set()
        for p in block.preds:
            res.update(self.out_sets[p.bid])
        return res
        
    def transfer(self, block: BasicBlock, in_val: Set[str]) -> Set[str]:
        return in_val - self.kill[block.bid]

class UninitializedVariableRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                issues.extend(self.analyze_func(item, filename))
        return issues
        
    def analyze_func(self, func: nodes.FunctionDef, filename: str) -> List[Issue]:
        issues = []
        
        # 1. Collect all local uninitialized scalar variables. Arrays and structs are
        # filled element by element (a[0] = 1, p.x = 1), and `static` locals start at 0.
        uninit_locals = set()
        def find_locals(n: nodes.Node):
            if not n: return
            if (isinstance(n, nodes.VarDecl) and not n.is_global and n.init is None and n.name
                    and n.storage != 'static' and is_scalar(n.type)):
                uninit_locals.add(n.name)
            
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
        # `scanf("%d", &n)` or `init(&n)` may write n through the pointer; we can't
        # see that without alias analysis, so skip address-taken variables entirely.
        uninit_locals -= address_taken_names(func.body)

        if not uninit_locals:
            return []
            
        cfg = build_cfg(func)
        df = UninitDataflow(cfg, uninit_locals)
        df.run()
        
        reported = set()
        
        for b in cfg.blocks:
            curr_uninit = set(df.in_sets[b.bid])
            for stmt in b.statements:
                r, w = extract_detailed_usage(stmt)
                for name, loc in r:
                    if name in curr_uninit:
                        # Report
                        issue_key = (name, loc.line, loc.col)
                        if issue_key not in reported:
                            reported.add(issue_key)
                            issues.append(Issue(
                                file=filename,
                                line=loc.line,
                                col=loc.col,
                                message=f"Variable '{name}' is used uninitialized.",
                                rule_id="uninitialized"
                            ))
                curr_uninit -= w
                
        return sorted(issues, key=lambda i: (i.line, i.col))
