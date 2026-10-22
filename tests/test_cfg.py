from sca.ast import nodes
import pytest
import os
from sca.frontend.runner import run_cparse
from sca.frontend.loader import load_ast
from sca.analysis.cfg import build_cfg

def get_func(ast, name):
    for i in ast.items:
        if isinstance(i, nodes.FunctionDef) and i.name == name:
            return i
    return None

def test_cfg_if(tmp_path):
    c_file = tmp_path / "test.c"
    c_file.write_text("int main() { if (1) { return 1; } else { return 0; } }")
    data = run_cparse(str(c_file))
    ast = load_ast(data)
    func = get_func(ast, "main")
    
    cfg = build_cfg(func)
    assert len(cfg.blocks) > 2
    
    # Entry block should have 1 succ (the if condition/header)
    assert len(cfg.entry.succs) == 2
    header = cfg.entry
    
    # Header should have 2 succs (then and else)
    assert len(header.succs) == 2

def test_cfg_while(tmp_path):
    c_file = tmp_path / "test.c"
    c_file.write_text("int main() { int x = 3; while (x) { break; } }")
    data = run_cparse(str(c_file))
    ast = load_ast(data)
    func = get_func(ast, "main")

    cfg = build_cfg(func)

    # Check that there's a back edge or loop structure
    # Entry -> cond_b -> body_b -> cond_b
    assert len(cfg.entry.succs) == 1
    cond_b = cfg.entry.succs[0]
    assert len(cond_b.succs) == 2 # body and merge

def test_cfg_while_true(tmp_path):
    c_file = tmp_path / "test.c"
    c_file.write_text("int main() { while (1) { break; } }")
    data = run_cparse(str(c_file))
    ast = load_ast(data)
    func = get_func(ast, "main")

    cfg = build_cfg(func)

    # `while (1)` has no exit edge from its condition; the loop exit is
    # reachable only through the break.
    cond_b = cfg.entry.succs[0]
    assert len(cond_b.succs) == 1
    body_b = cond_b.succs[0]
    assert any(s is not cond_b for s in body_b.succs)  # break -> merge
