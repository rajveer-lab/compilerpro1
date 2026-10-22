from typing import List, Set, Dict, Tuple
from sca.rules.base import Rule, Issue
from sca.ast import nodes
from sca.rules.uninitialized import extract_detailed_usage
from sca.analysis.cfg import parse_c_int

class UnusedFunctionRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        static_funcs: Dict[str, nodes.Node] = {}
        
        for item in ast.items:
            if isinstance(item, (nodes.FunctionDef, nodes.Prototype)):
                if item.storage == 'static' and item.name != 'main':
                    static_funcs[item.name] = item
                    
        used = set()
        def find_usages(n: nodes.Node):
            if not n: return
            if isinstance(n, nodes.Identifier):
                used.add(n.name)
            
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node):
                        find_usages(val)
                    elif isinstance(val, list):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                find_usages(i)
                                
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                find_usages(item.body)
            elif isinstance(item, nodes.DeclStmt):
                for decl in item.decls:
                    if isinstance(decl, nodes.VarDecl) and decl.init:
                        find_usages(decl.init)
                
        for name, node in static_funcs.items():
            if name not in used:
                issues.append(Issue(
                    file=filename,
                    line=node.loc.line,
                    col=node.loc.col,
                    message=f"Static function '{name}' is never called.",
                    rule_id="unused-function"
                ))
                
        return issues


class ShadowedVariableRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        
        globals = set()
        for item in ast.items:
            if isinstance(item, nodes.DeclStmt):
                for decl in item.decls:
                    if isinstance(decl, nodes.VarDecl) and decl.name:
                        globals.add(decl.name)
                
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                self.analyze_func(item, globals, filename, issues)
                
        return issues
        
    def analyze_func(self, func: nodes.FunctionDef, globals: Set[str], filename: str, issues: List[Issue]):
        scopes: List[Set[str]] = [globals.copy()]
        
        param_scope = set()
        for p in func.params:
            if p.name:
                if p.name in scopes[-1]:
                    issues.append(Issue(file=filename, line=p.loc.line, col=p.loc.col,
                                        message=f"Parameter '{p.name}' shadows a global variable.",
                                        rule_id="shadowed-variable"))
                param_scope.add(p.name)
        scopes.append(param_scope)
        
        def visit(n: nodes.Node):
            if not n: return
            
            if isinstance(n, nodes.Block):
                scopes.append(set())
                for stmt in n.stmts:
                    visit(stmt)
                scopes.pop()
                return

            # `for (int i = ...)` opens its own scope; i must not leak into the enclosing block.
            if isinstance(n, nodes.For):
                scopes.append(set())
                for part in (n.init, n.cond, n.step, n.body):
                    visit(part)
                scopes.pop()
                return

            if isinstance(n, nodes.VarDecl) and n.name:
                for s in scopes[:-1]:
                    if n.name in s:
                        issues.append(Issue(file=filename, line=n.loc.line, col=n.loc.col,
                                            message=f"Declaration of '{n.name}' shadows a variable from an enclosing scope.",
                                            rule_id="shadowed-variable"))
                        break
                scopes[-1].add(n.name)
                
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node) and not isinstance(n, nodes.Block):
                        visit(val)
                    elif isinstance(val, list) and not isinstance(n, nodes.Block):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                visit(i)
                                
        visit(func.body)


class ConstIndexOutOfBoundsRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []

        # Sizes are tracked per function (globals + that function's locals), so two
        # functions that each declare a `buf` of different sizes don't mix them up.
        array_sizes: Dict[str, int] = {}

        def record_arrays(n: nodes.Node):
            if not n: return
            if isinstance(n, nodes.VarDecl) and n.name:
                if isinstance(n.type, nodes.ArrayType):
                    size_expr = n.type.size
                    if isinstance(size_expr, nodes.IntLiteral):
                        size = parse_c_int(size_expr.text)
                        if size is not None:
                            array_sizes[n.name] = size

            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node):
                        record_arrays(val)
                    elif isinstance(val, list):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                record_arrays(i)
        
        def get_int_value(expr: nodes.Node):
            if isinstance(expr, nodes.IntLiteral):
                return parse_c_int(expr.text)
            if isinstance(expr, nodes.Unary) and expr.op == '-' and isinstance(expr.operand, nodes.IntLiteral):
                value = parse_c_int(expr.operand.text)
                return -value if value is not None else None
            return None

        def check_bounds(n: nodes.Node):
            if not n: return
            if isinstance(n, nodes.Index):
                if isinstance(n.base, nodes.Identifier):
                    idx = get_int_value(n.index)
                    if idx is not None:
                        name = n.base.name
                        if name in array_sizes:
                            sz = array_sizes[name]
                            if idx < 0 or idx >= sz:
                                issues.append(Issue(
                                    file=filename,
                                    line=n.loc.line,
                                    col=n.loc.col,
                                    message=f"Array index {idx} is out of bounds for array '{name}' of size {sz}.",
                                    rule_id="const-index-out-of-bounds"
                                ))
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node):
                        check_bounds(val)
                    elif isinstance(val, list):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                check_bounds(i)
                                
        for item in ast.items:
            if isinstance(item, nodes.DeclStmt):
                record_arrays(item)
        global_sizes = dict(array_sizes)

        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                array_sizes.clear()
                array_sizes.update(global_sizes)
                record_arrays(item.body)
                check_bounds(item.body)

        return issues
