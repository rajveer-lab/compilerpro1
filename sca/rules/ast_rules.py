from typing import List, Set, Any, Iterator, Tuple
from sca.rules.base import Rule, Issue
from sca.ast import nodes
import re

class FunctionTooLongRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                if item.loc and item.loc.end_line - item.loc.line > 50:
                    issues.append(Issue(
                        file=filename,
                        line=item.loc.line,
                        col=item.loc.col,
                        message=f"Function '{item.name}' body exceeds limit of 50 lines.",
                        rule_id="function-too-long"
                    ))
        return issues

CONTROL_NODES = (nodes.If, nodes.While, nodes.For, nodes.DoWhile, nodes.Switch)

def control_depths(body: nodes.Node) -> Iterator[Tuple[nodes.Node, int]]:
    """Yield (control statement, nesting depth) for every if/loop/switch under body.

    An `else if` is a flat chain in source, so it stays at its parent if's depth
    instead of nesting one level deeper per arm.
    """
    def visit(n: nodes.Node, depth: int, is_else_if: bool = False) -> Iterator[Tuple[nodes.Node, int]]:
        if not n: return
        new_depth = depth
        if isinstance(n, CONTROL_NODES):
            new_depth = depth if is_else_if else depth + 1
            yield n, new_depth
        if hasattr(n, '__dataclass_fields__'):
            for field in n.__dataclass_fields__:
                val = getattr(n, field)
                if isinstance(val, nodes.Node):
                    chained = isinstance(n, nodes.If) and field == 'else_branch' and isinstance(val, nodes.If)
                    yield from visit(val, new_depth, chained)
                elif isinstance(val, list):
                    for i in val:
                        if isinstance(i, nodes.Node):
                            yield from visit(i, new_depth)

    yield from visit(body, 0)

class DeepNestingRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        max_depth = 4
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                for n, depth in control_depths(item.body):
                    # Report where nesting first crosses the limit, not again at every deeper level.
                    if depth == max_depth + 1:
                        issues.append(Issue(
                            file=filename,
                            line=n.loc.line,
                            col=n.loc.col,
                            message=f"Max nesting of blocks/loops/conditionals exceeds limit of {max_depth}.",
                            rule_id="deep-nesting"
                        ))

        return issues

class TooManyParamsRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        for item in ast.items:
            if isinstance(item, nodes.FunctionDef):
                if len(item.params) > 5:
                    issues.append(Issue(
                        file=filename,
                        line=item.loc.line,
                        col=item.loc.col,
                        message=f"Function '{item.name}' has {len(item.params)} parameters (exceeds limit of 5).",
                        rule_id="too-many-params"
                    ))
        return issues

class MagicNumberRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        allowed = {'0', '1', '-1', '2'}
        
        def visit(n: nodes.Node, is_exempt: bool):
            if not n: return
            
            if isinstance(n, nodes.IntLiteral) or isinstance(n, nodes.FloatLiteral):
                if not is_exempt and n.text not in allowed:
                    issues.append(Issue(
                        file=filename,
                        line=n.loc.line,
                        col=n.loc.col,
                        message=f"Magic number '{n.text}' used.",
                        rule_id="magic-number"
                    ))
                    
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    
                    exempt_child = is_exempt
                    if isinstance(n, nodes.VarDecl) and getattr(n.type, 'is_const', False):
                        exempt_child = True
                    if isinstance(n, nodes.ArrayType):
                        exempt_child = True
                    if isinstance(n, nodes.Case):
                        exempt_child = True
                        
                    if isinstance(val, nodes.Node):
                        visit(val, exempt_child)
                    elif isinstance(val, list):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                visit(i, exempt_child)
                                
        visit(ast, False)
        return issues

class NamingConventionRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        snake_case = re.compile(r'^[a-z_][a-z0-9_]*$')
        upper_case = re.compile(r'^[A-Z_][A-Z0-9_]*$')
        
        def check(name, regex, kind, loc):
            if name and not regex.match(name) and name != 'main':
                issues.append(Issue(
                    file=filename,
                    line=loc.line,
                    col=loc.col,
                    message=f"{kind} '{name}' violates naming convention.",
                    rule_id="naming-convention"
                ))
                
        def visit(n: nodes.Node):
            if not n: return
            if isinstance(n, nodes.FunctionDef) or isinstance(n, nodes.Prototype):
                check(n.name, snake_case, "Function", n.loc)
            elif isinstance(n, nodes.VarDecl):
                if getattr(n.type, 'is_const', False):
                    check(n.name, upper_case, "Constant variable", n.loc)
                else:
                    check(n.name, snake_case, "Variable", n.loc)
                    
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node):
                        visit(val)
                    elif isinstance(val, list):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                visit(i)
                                
        visit(ast)
        return issues

class UnsafeFunctionRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        banned = {
            'gets': 'fgets',
            'strcpy': 'strncpy',
            'strcat': 'strncat',
            'sprintf': 'snprintf',
            'scanf': 'fscanf'
        }
        
        def visit(n: nodes.Node):
            if not n: return
            if isinstance(n, nodes.Call):
                if isinstance(n.callee, nodes.Identifier):
                    name = n.callee.name
                    if name in banned:
                        if name == 'scanf':
                            # Check for bare %s
                            if n.args and isinstance(n.args[0], nodes.StringLiteral):
                                if '%s' in n.args[0].text and '%*s' not in n.args[0].text:
                                    issues.append(Issue(
                                        file=filename,
                                        line=n.loc.line,
                                        col=n.loc.col,
                                        message=f"Call to unsafe function 'scanf' with '%s'. Use width limits.",
                                        rule_id="unsafe-function"
                                    ))
                        else:
                            issues.append(Issue(
                                file=filename,
                                line=n.loc.line,
                                col=n.loc.col,
                                message=f"Call to banned function '{name}'. Use '{banned[name]}' instead.",
                                rule_id="unsafe-function"
                            ))
                            
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node):
                        visit(val)
                    elif isinstance(val, list):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                visit(i)
                                
        visit(ast)
        return issues

class AssignmentInConditionRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        
        def check_cond(cond: nodes.Node):
            if isinstance(cond, nodes.Assign) and cond.op == '=':
                issues.append(Issue(
                    file=filename,
                    line=cond.loc.line,
                    col=cond.loc.col,
                    message="Assignment '=' used as condition.",
                    rule_id="assignment-in-condition"
                ))
        
        def visit(n: nodes.Node):
            if not n: return
            if isinstance(n, (nodes.If, nodes.While, nodes.DoWhile)):
                if n.cond:
                    check_cond(n.cond)
            elif isinstance(n, nodes.For):
                if n.cond:
                    check_cond(n.cond)
            elif isinstance(n, nodes.Ternary):
                if n.cond:
                    check_cond(n.cond)
                    
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node):
                        visit(val)
                    elif isinstance(val, list):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                visit(i)
                                
        visit(ast)
        return issues

class EmptyBodyRule(Rule):
    def analyze(self, ast: nodes.TranslationUnit, filename: str) -> List[Issue]:
        issues = []
        
        def is_empty(stmt: nodes.Node):
            if stmt is None:
                return True
            if isinstance(stmt, getattr(nodes, 'EmptyStmt', type(None))):
                return True
            if isinstance(stmt, nodes.Block) and not stmt.stmts:
                return True
            return False
            
        def visit(n: nodes.Node):
            if not n: return
            if isinstance(n, (nodes.If, nodes.While, nodes.For)):
                body = getattr(n, 'then_branch', getattr(n, 'body', None))
                if is_empty(body):
                    issues.append(Issue(
                        file=filename,
                        line=n.loc.line,
                        col=n.loc.col,
                        message="Control statement has an empty body.",
                        rule_id="empty-body"
                    ))
                    
            if hasattr(n, '__dataclass_fields__'):
                for field in n.__dataclass_fields__:
                    val = getattr(n, field)
                    if isinstance(val, nodes.Node):
                        visit(val)
                    elif isinstance(val, list):
                        for i in val:
                            if isinstance(i, nodes.Node):
                                visit(i)
                                
        visit(ast)
        return issues
