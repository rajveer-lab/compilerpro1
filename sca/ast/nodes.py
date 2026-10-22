from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union, Any

@dataclass
class Loc:
    line: int
    col: int
    end_line: int
    end_col: int

class Type: pass

@dataclass
class BaseType(Type):
    name: str
    is_const: bool

@dataclass
class PointerType(Type):
    to: Type
    is_const: bool

@dataclass
class ArrayType(Type):
    of: Type
    size: Optional['Node']

@dataclass
class StructType(Type):
    name: Optional[str]
    fields: Optional[List['VarDecl']]

@dataclass
class TypedefType(Type):
    name: str

@dataclass
class FunctionType(Type):
    returns: Type
    params: List['Node']

class Node:
    loc: Loc

# Statements
class Stmt(Node): pass

@dataclass
class Block(Stmt):
    loc: Loc
    stmts: List[Stmt]

@dataclass
class DeclStmt(Stmt):
    loc: Loc
    decls: List['Decl']

@dataclass
class ExprStmt(Stmt):
    loc: Loc
    expr: 'Expr'

@dataclass
class EmptyStmt(Stmt):
    loc: Loc

@dataclass
class If(Stmt):
    loc: Loc
    cond: 'Expr'
    then_branch: Stmt
    else_branch: Optional[Stmt]

@dataclass
class While(Stmt):
    loc: Loc
    cond: 'Expr'
    body: Stmt

@dataclass
class DoWhile(Stmt):
    loc: Loc
    body: Stmt
    cond: 'Expr'

@dataclass
class For(Stmt):
    loc: Loc
    init: Optional[Union['DeclStmt', 'ExprStmt']]
    cond: Optional['Expr']
    step: Optional['Expr']
    body: Stmt

@dataclass
class Switch(Stmt):
    loc: Loc
    expr: 'Expr'
    body: Stmt

@dataclass
class Case(Stmt):
    loc: Loc
    value: 'Expr'

@dataclass
class Default(Stmt):
    loc: Loc

@dataclass
class Break(Stmt):
    loc: Loc

@dataclass
class Continue(Stmt):
    loc: Loc

@dataclass
class Return(Stmt):
    loc: Loc
    value: Optional['Expr']

# Expressions
class Expr(Node): pass

@dataclass
class Identifier(Expr):
    loc: Loc
    name: str

@dataclass
class IntLiteral(Expr):
    loc: Loc
    text: str

@dataclass
class FloatLiteral(Expr):
    loc: Loc
    text: str

@dataclass
class CharLiteral(Expr):
    loc: Loc
    text: str

@dataclass
class StringLiteral(Expr):
    loc: Loc
    text: str

@dataclass
class Unary(Expr):
    loc: Loc
    op: str
    operand: Expr

@dataclass
class Postfix(Expr):
    loc: Loc
    op: str
    operand: Expr

@dataclass
class Binary(Expr):
    loc: Loc
    op: str
    left: Expr
    right: Expr

@dataclass
class Assign(Expr):
    loc: Loc
    op: str
    target: Expr
    value: Expr

@dataclass
class Ternary(Expr):
    loc: Loc
    cond: Expr
    then_branch: Expr
    else_branch: Expr

@dataclass
class Call(Expr):
    loc: Loc
    callee: Expr
    args: List[Expr]

@dataclass
class Index(Expr):
    loc: Loc
    base: Expr
    index: Expr

@dataclass
class Member(Expr):
    loc: Loc
    base: Expr
    name: str
    arrow: bool

@dataclass
class Cast(Expr):
    loc: Loc
    type: Type
    operand: Expr

@dataclass
class Sizeof(Expr):
    loc: Loc
    operand: Optional[Expr]
    type: Optional[Type]

@dataclass
class InitList(Expr):
    loc: Loc
    items: List[Expr]

# Declarations
class Decl(Node): pass

@dataclass
class Param(Decl):
    loc: Loc
    name: Optional[str]
    type: Type

@dataclass
class VarDecl(Decl):
    loc: Loc
    name: Optional[str]
    type: Type
    storage: Optional[str]
    init: Optional[Expr]
    is_global: bool

@dataclass
class TypedefDecl(Decl):
    loc: Loc
    name: str
    type: Type

@dataclass
class StructDef(Decl):
    loc: Loc
    name: Optional[str]
    fields: List[VarDecl]

@dataclass
class Prototype(Decl):
    loc: Loc
    name: str
    return_type: Type
    params: List[Param]
    storage: Optional[str]

@dataclass
class FunctionDef(Decl):
    loc: Loc
    name: str
    return_type: Type
    params: List[Param]
    storage: Optional[str]
    body: Block

@dataclass
class TranslationUnit:
    items: List[Decl]
    # Object-like `#define NAME value` macros (from the JSON `directives`), name -> raw value text.
    defines: Dict[str, str] = field(default_factory=dict)
