import pytest
import os
from sca.frontend.runner import run_cparse
from sca.frontend.loader import load_ast
from sca.ast import nodes

def test_loader_simple(tmp_path):
    c_file = tmp_path / "test.c"
    c_file.write_text("int main() { return 0; }")
    data = run_cparse(str(c_file))
    
    ast = load_ast(data)
    assert isinstance(ast, nodes.TranslationUnit)
    assert len(ast.items) == 1
    func = ast.items[0]
    assert isinstance(func, nodes.FunctionDef)
    assert func.name == "main"
    assert isinstance(func.return_type, nodes.BaseType)
    assert func.return_type.name == "int"
    assert len(func.params) == 0
    
    assert isinstance(func.body, nodes.Block)
    assert len(func.body.stmts) == 1
    ret = func.body.stmts[0]
    assert isinstance(ret, nodes.Return)
    assert isinstance(ret.value, nodes.IntLiteral)
    assert ret.value.text == "0"

def _load(tmp_path, code):
    c_file = tmp_path / "test.c"
    c_file.write_text(code)
    return load_ast(run_cparse(str(c_file)))

def test_loader_void_parameter_list_means_no_params(tmp_path):
    ast = _load(tmp_path, "int f(void);\nint main(void) { return 0; }")
    funcs = [i for i in ast.items if isinstance(i, (nodes.FunctionDef, nodes.Prototype))]
    assert [f.name for f in funcs if isinstance(f, nodes.FunctionDef)] == ["main"]
    assert all(f.params == [] for f in funcs)

def test_loader_static_void_function_has_no_params(tmp_path):
    ast = _load(tmp_path, "static void report(void) { }\nint main() { report(); return 0; }")
    assert ast.items[0].name == "report"
    assert ast.items[0].params == []

def test_loader_void_pointer_parameter_is_kept(tmp_path):
    ast = _load(tmp_path, "int first(void *p) { return p != 0; }")
    params = ast.items[0].params
    assert len(params) == 1
    assert params[0].name == "p"
    assert isinstance(params[0].type, nodes.PointerType)

def test_loader_named_parameters_are_kept(tmp_path):
    ast = _load(tmp_path, "int add(int a, int b) { return a + b; }")
    assert [p.name for p in ast.items[0].params] == ["a", "b"]
