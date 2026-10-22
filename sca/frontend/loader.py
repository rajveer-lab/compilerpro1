from sca.ast import nodes
from typing import Dict, Any, List

def load_loc(data: Dict[str, Any]) -> nodes.Loc:
    return nodes.Loc(
        line=data["line"],
        col=data["col"],
        end_line=data["end_line"],
        end_col=data["end_col"]
    )

def load_type(data: Dict[str, Any]) -> nodes.Type:
    if data is None:
        return None
    tk = data["tk"]
    if tk == "base":
        return nodes.BaseType(name=data["name"], is_const=data.get("const", False))
    elif tk == "pointer":
        return nodes.PointerType(to=load_type(data["to"]), is_const=data.get("const", False))
    elif tk == "array":
        size = load_node(data["size"]) if data.get("size") else None
        return nodes.ArrayType(of=load_type(data["of"]), size=size)
    elif tk == "struct":
        fields = [load_node(f) for f in data["fields"]] if data.get("fields") else None
        return nodes.StructType(name=data.get("name"), fields=fields)
    elif tk == "typedef":
        return nodes.TypedefType(name=data["name"])
    elif tk == "function":
        params = [load_node(p) for p in data["params"]] if data.get("params") else []
        return nodes.FunctionType(returns=load_type(data["returns"]), params=params)
    raise ValueError(f"Unknown type kind: {tk}")

def load_node(data: Dict[str, Any]) -> nodes.Node:
    if data is None:
        return None
    kind = data["kind"]
    loc = load_loc(data) if "line" in data else None
    
    if kind == "FunctionDef":
        return nodes.FunctionDef(
            loc=loc,
            name=data["name"],
            return_type=load_type(data["return_type"]),
            params=[load_node(p) for p in data.get("params", [])],
            storage=data.get("storage"),
            body=load_node(data["body"])
        )
    elif kind == "Prototype":
        return nodes.Prototype(
            loc=loc,
            name=data["name"],
            return_type=load_type(data["return_type"]),
            params=[load_node(p) for p in data.get("params", [])],
            storage=data.get("storage")
        )
    elif kind == "VarDecl":
        return nodes.VarDecl(
            loc=loc,
            name=data.get("name"),
            type=load_type(data["type"]),
            storage=data.get("storage"),
            init=load_node(data.get("init")),
            is_global=data.get("is_global", False)
        )
    elif kind == "TypedefDecl":
        return nodes.TypedefDecl(
            loc=loc,
            name=data["name"],
            type=load_type(data["type"])
        )
    elif kind == "StructDef":
        return nodes.StructDef(
            loc=loc,
            name=data.get("name"),
            fields=[load_node(f) for f in data.get("fields", [])]
        )
    elif kind == "Param":
        return nodes.Param(
            loc=loc,
            name=data.get("name"),
            type=load_type(data["type"])
        )
    elif kind == "Block":
        return nodes.Block(loc=loc, stmts=[load_node(s) for s in data.get("stmts", [])])
    elif kind == "DeclStmt":
        return nodes.DeclStmt(loc=loc, decls=[load_node(d) for d in data.get("decls", [])])
    elif kind == "ExprStmt":
        return nodes.ExprStmt(loc=loc, expr=load_node(data["expr"]))
    elif kind == "EmptyStmt":
        return nodes.EmptyStmt(loc=loc)
    elif kind == "If":
        return nodes.If(
            loc=loc,
            cond=load_node(data["cond"]),
            then_branch=load_node(data["then"]),
            else_branch=load_node(data.get("else")) if data.get("else") else None
        )
    elif kind == "While":
        return nodes.While(loc=loc, cond=load_node(data["cond"]), body=load_node(data["body"]))
    elif kind == "DoWhile":
        return nodes.DoWhile(loc=loc, body=load_node(data["body"]), cond=load_node(data["cond"]))
    elif kind == "For":
        return nodes.For(
            loc=loc,
            init=load_node(data.get("init")),
            cond=load_node(data.get("cond")),
            step=load_node(data.get("step")),
            body=load_node(data["body"])
        )
    elif kind == "Switch":
        return nodes.Switch(loc=loc, expr=load_node(data["expr"]), body=load_node(data["body"]))
    elif kind == "Case":
        return nodes.Case(loc=loc, value=load_node(data["value"]))
    elif kind == "Default":
        return nodes.Default(loc=loc)
    elif kind == "Break":
        return nodes.Break(loc=loc)
    elif kind == "Continue":
        return nodes.Continue(loc=loc)
    elif kind == "Return":
        return nodes.Return(loc=loc, value=load_node(data.get("value")))
    elif kind == "Identifier":
        return nodes.Identifier(loc=loc, name=data["name"])
    elif kind == "IntLiteral":
        return nodes.IntLiteral(loc=loc, text=data["text"])
    elif kind == "FloatLiteral":
        return nodes.FloatLiteral(loc=loc, text=data["text"])
    elif kind == "CharLiteral":
        return nodes.CharLiteral(loc=loc, text=data["text"])
    elif kind == "StringLiteral":
        return nodes.StringLiteral(loc=loc, text=data["text"])
    elif kind == "Unary":
        return nodes.Unary(loc=loc, op=data["op"], operand=load_node(data["operand"]))
    elif kind == "Postfix":
        return nodes.Postfix(loc=loc, op=data["op"], operand=load_node(data["operand"]))
    elif kind == "Binary":
        return nodes.Binary(loc=loc, op=data["op"], left=load_node(data["left"]), right=load_node(data["right"]))
    elif kind == "Assign":
        return nodes.Assign(loc=loc, op=data["op"], target=load_node(data["target"]), value=load_node(data["value"]))
    elif kind == "Ternary":
        return nodes.Ternary(
            loc=loc,
            cond=load_node(data["cond"]),
            then_branch=load_node(data["then"]),
            else_branch=load_node(data["else"])
        )
    elif kind == "Call":
        return nodes.Call(
            loc=loc,
            callee=load_node(data["callee"]),
            args=[load_node(a) for a in data.get("args", [])]
        )
    elif kind == "Index":
        return nodes.Index(loc=loc, base=load_node(data["base"]), index=load_node(data["index"]))
    elif kind == "Member":
        return nodes.Member(
            loc=loc,
            base=load_node(data["base"]),
            name=data["name"],
            arrow=data.get("arrow", False)
        )
    elif kind == "Cast":
        return nodes.Cast(loc=loc, type=load_type(data["type"]), operand=load_node(data["operand"]))
    elif kind == "Sizeof":
        return nodes.Sizeof(
            loc=loc,
            operand=load_node(data.get("operand")),
            type=load_type(data.get("type"))
        )
    elif kind == "InitList":
        return nodes.InitList(loc=loc, items=[load_node(i) for i in data.get("items", [])])
    
    raise ValueError(f"Unknown AST node kind: {kind}")

def load_translation_unit(data: Dict[str, Any]) -> nodes.TranslationUnit:
    if data is None or "items" not in data:
        return nodes.TranslationUnit(items=[])
    return nodes.TranslationUnit(items=[load_node(i) for i in data["items"]])

def load_ast(data: Dict[str, Any]) -> nodes.TranslationUnit:
    if "unit" in data and data["unit"]:
        unit = load_translation_unit(data["unit"])
    else:
        unit = nodes.TranslationUnit(items=[])
    directives = data.get("directives") or {}
    for d in directives.get("defines", []):
        if d.get("name") and d.get("value") is not None:
            unit.defines[d["name"]] = d["value"]
    return unit
