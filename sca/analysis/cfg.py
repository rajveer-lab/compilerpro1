from typing import List, Optional, Set
from sca.ast import nodes

def is_constant_true(expr: Optional[nodes.Node]) -> bool:
    """True for a nonzero integer literal condition such as `while (1)`."""
    if isinstance(expr, nodes.IntLiteral):
        value = parse_c_int(expr.text)
        return value is not None and value != 0
    return False

def parse_c_int(text: str) -> Optional[int]:
    """Parse a C integer literal (decimal, 0x hex, 0 octal, u/l suffixes); None if not one."""
    t = text.rstrip("uUlL")
    try:
        if t.lower().startswith("0x"):
            return int(t, 16)
        if len(t) > 1 and t.startswith("0"):
            return int(t, 8)
        return int(t, 10)
    except ValueError:
        return None

class BasicBlock:
    def __init__(self, bid: int):
        self.bid = bid
        self.statements: List[nodes.Node] = []
        self.preds: List['BasicBlock'] = []
        self.succs: List['BasicBlock'] = []

    def add_statement(self, stmt: nodes.Node):
        self.statements.append(stmt)

    def add_succ(self, succ: 'BasicBlock'):
        if succ not in self.succs:
            self.succs.append(succ)
        if self not in succ.preds:
            succ.preds.append(self)
            
    def __repr__(self):
        return f"BasicBlock({self.bid})"

class CFG:
    def __init__(self, func: nodes.FunctionDef):
        self.func = func
        self.entry: BasicBlock = BasicBlock(0)
        self.exit: BasicBlock = BasicBlock(1)
        self.blocks: List[BasicBlock] = [self.entry, self.exit]
        self._next_id = 2

    def new_block(self) -> BasicBlock:
        b = BasicBlock(self._next_id)
        self._next_id += 1
        self.blocks.append(b)
        return b

    def to_string(self) -> str:
        res = []
        for b in self.blocks:
            res.append(f"Block {b.bid}:")
            res.append(f"  Preds: {[p.bid for p in b.preds]}")
            res.append(f"  Succs: {[s.bid for s in b.succs]}")
            res.append(f"  Statements: {len(b.statements)}")
            for stmt in b.statements:
                res.append(f"    {stmt.__class__.__name__}")
        return "\n".join(res)

class CFGBuilder:
    def __init__(self, func: nodes.FunctionDef):
        self.cfg = CFG(func)
        self.current_block: Optional[BasicBlock] = self.cfg.entry
        
        self.break_targets: List[BasicBlock] = []
        self.continue_targets: List[BasicBlock] = []
        
        self.switch_headers: List[BasicBlock] = []
        self.has_default: List[bool] = []

    def build(self) -> CFG:
        self.visit(self.cfg.func.body)
        if self.current_block and self.current_block not in self.cfg.exit.preds:
            self.current_block.add_succ(self.cfg.exit)
        return self.cfg

    def visit(self, node: nodes.Node):
        if not node:
            return
        method_name = f'visit_{node.__class__.__name__}'
        visitor = getattr(self, method_name, self.generic_visit)
        visitor(node)

    def generic_visit(self, node: nodes.Node):
        if self.current_block is None:
            self.current_block = self.cfg.new_block()
        self.current_block.add_statement(node)

    def visit_Block(self, node: nodes.Block):
        for stmt in node.stmts:
            self.visit(stmt)

    def visit_If(self, node: nodes.If):
        if self.current_block is None:
            self.current_block = self.cfg.new_block()
        self.current_block.add_statement(node.cond)
        
        header = self.current_block
        then_b = self.cfg.new_block()
        merge_b = self.cfg.new_block()
        
        if header:
            header.add_succ(then_b)
            
        self.current_block = then_b
        self.visit(node.then_branch)
        if self.current_block:
            self.current_block.add_succ(merge_b)
            
        if node.else_branch:
            else_b = self.cfg.new_block()
            if header:
                header.add_succ(else_b)
            self.current_block = else_b
            self.visit(node.else_branch)
            if self.current_block:
                self.current_block.add_succ(merge_b)
        else:
            if header:
                header.add_succ(merge_b)
                
        self.current_block = merge_b

    def visit_While(self, node: nodes.While):
        if self.current_block is None:
            self.current_block = self.cfg.new_block()
            
        cond_b = self.cfg.new_block()
        body_b = self.cfg.new_block()
        merge_b = self.cfg.new_block()
        
        self.current_block.add_succ(cond_b)
            
        cond_b.add_statement(node.cond)
        cond_b.add_succ(body_b)
        # `while (1)` never exits through its condition, only through break/return,
        # so the loop exit is reachable only via a break edge.
        if not is_constant_true(node.cond):
            cond_b.add_succ(merge_b)

        self.break_targets.append(merge_b)
        self.continue_targets.append(cond_b)

        self.current_block = body_b
        self.visit(node.body)
        
        if self.current_block:
            self.current_block.add_succ(cond_b)
            
        self.break_targets.pop()
        self.continue_targets.pop()
        
        self.current_block = merge_b

    def visit_DoWhile(self, node: nodes.DoWhile):
        if self.current_block is None:
            self.current_block = self.cfg.new_block()
            
        body_b = self.cfg.new_block()
        cond_b = self.cfg.new_block()
        merge_b = self.cfg.new_block()
        
        self.current_block.add_succ(body_b)
            
        self.break_targets.append(merge_b)
        self.continue_targets.append(cond_b)
        
        self.current_block = body_b
        self.visit(node.body)
        
        if self.current_block:
            self.current_block.add_succ(cond_b)
            
        cond_b.add_statement(node.cond)
        cond_b.add_succ(body_b)
        cond_b.add_succ(merge_b)
        
        self.break_targets.pop()
        self.continue_targets.pop()
        
        self.current_block = merge_b

    def visit_For(self, node: nodes.For):
        if node.init:
            self.visit(node.init)
            
        if self.current_block is None:
            self.current_block = self.cfg.new_block()
            
        cond_b = self.cfg.new_block()
        body_b = self.cfg.new_block()
        step_b = self.cfg.new_block()
        merge_b = self.cfg.new_block()
        
        self.current_block.add_succ(cond_b)
            
        if node.cond:
            cond_b.add_statement(node.cond)
            cond_b.add_succ(body_b)
            cond_b.add_succ(merge_b)
        else:
            cond_b.add_succ(body_b)
            
        self.break_targets.append(merge_b)
        self.continue_targets.append(step_b)
        
        self.current_block = body_b
        self.visit(node.body)
        
        if self.current_block:
            self.current_block.add_succ(step_b)
            
        if node.step:
            step_b.add_statement(node.step)
        step_b.add_succ(cond_b)
            
        self.break_targets.pop()
        self.continue_targets.pop()
        
        self.current_block = merge_b

    def visit_Switch(self, node: nodes.Switch):
        if self.current_block is None:
            self.current_block = self.cfg.new_block()
        self.current_block.add_statement(node.expr)
            
        switch_header = self.current_block
        merge_b = self.cfg.new_block()
        
        self.break_targets.append(merge_b)
        self.switch_headers.append(switch_header)
        self.has_default.append(False)
        
        self.current_block = None # Unreachable until case
        
        self.visit(node.body)
        
        if not self.has_default[-1]:
            if switch_header:
                switch_header.add_succ(merge_b)
                
        self.has_default.pop()
        self.switch_headers.pop()
        
        if self.current_block:
            self.current_block.add_succ(merge_b)
            
        self.break_targets.pop()
        self.current_block = merge_b

    def visit_Case(self, node: nodes.Case):
        case_b = self.cfg.new_block()
        case_b.add_statement(node)
        
        if self.current_block:
            self.current_block.add_succ(case_b)
            
        if self.switch_headers and self.switch_headers[-1]:
            self.switch_headers[-1].add_succ(case_b)
            
        self.current_block = case_b

    def visit_Default(self, node: nodes.Default):
        def_b = self.cfg.new_block()
        def_b.add_statement(node)
        
        if self.current_block:
            self.current_block.add_succ(def_b)
            
        if self.switch_headers and self.switch_headers[-1]:
            self.switch_headers[-1].add_succ(def_b)
            self.has_default[-1] = True
            
        self.current_block = def_b

    def visit_Break(self, node: nodes.Break):
        if self.current_block is None:
            self.current_block = self.cfg.new_block()
        self.current_block.add_statement(node)
        if self.break_targets:
            self.current_block.add_succ(self.break_targets[-1])
        self.current_block = None

    def visit_Continue(self, node: nodes.Continue):
        if self.current_block is None:
            self.current_block = self.cfg.new_block()
        self.current_block.add_statement(node)
        if self.continue_targets:
            self.current_block.add_succ(self.continue_targets[-1])
        self.current_block = None
        
    def visit_Return(self, node: nodes.Return):
        if self.current_block is None:
            self.current_block = self.cfg.new_block()
        self.current_block.add_statement(node)
        self.current_block.add_succ(self.cfg.exit)
        self.current_block = None

def reachable_blocks(cfg: CFG) -> Set[int]:
    """Block ids reachable from the entry block."""
    reachable: Set[int] = set()
    worklist = [cfg.entry]
    while worklist:
        b = worklist.pop()
        if b.bid not in reachable:
            reachable.add(b.bid)
            worklist.extend(b.succs)
    return reachable

def build_cfg(func: nodes.FunctionDef) -> CFG:
    builder = CFGBuilder(func)
    return builder.build()
