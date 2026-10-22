"""JSON API endpoints for SCA web interface."""

import os
import re
from typing import Dict, Any, List
from flask import Blueprint, request, jsonify, current_app
from sca.service import analyze_source, MAX_SOURCE_SIZE
from sca.rules.registry import RULE_CATALOG
from sca.frontend.runner import get_cparse_bin, run_cparse
from sca.frontend.loader import load_ast
from sca.analysis.cfg import build_cfg
from sca.ast.nodes import FunctionDef

api_bp = Blueprint("api", __name__, url_prefix="/api")

BUILTIN_EXAMPLES: Dict[str, Dict[str, str]] = {
    "clean.c": {
        "title": "Clean Program",
        "description": "Standard clean C program with 0 issues and 100/100 score.",
        "code": """int main() {
    return 0;
}
"""
    },
    "smelly.c": {
        "title": "Unused Variable",
        "description": "Simple unused variable declaration eligible for safe one-click removal.",
        "code": """int main() {
    int x;
    return 0;
}
"""
    },
    "security_bugs.c": {
        "title": "Security Vulnerabilities",
        "description": "Unsafe C standard library functions vulnerable to buffer overflows.",
        "code": """int main() {
    char buf[16];
    gets(buf);
    return 0;
}
"""
    },
    "flow_issues.c": {
        "title": "Control Flow & Dataflow",
        "description": "Missing return paths, uninitialized variable usage, and unreachable code.",
        "code": """int compute(int x) {
    if (x > 0)
        return x * 2;
}

int main() {
    int uninit_var;
    return uninit_var;
    int unreachable_var = 10;
}
"""
    },
    "complex_refactor.c": {
        "title": "Complexity & Style",
        "description": "Assignment in condition, stray semicolon empty body, deep nesting, and parameter count.",
        "code": """int compute_values(int a, int b, int c, int d, int e, int f) {
    if (a = b);

    if (a > 10) {
        if (b > 20) {
            if (c > 30) {
                if (d > 40) {
                    if (e > 50) {
                        return 42;
                    }
                }
            }
        }
    }
    return 0;
}

int main() {
    return 0;
}
"""
    },
    "interval_demo.c": {
        "title": "Interval Analysis",
        "description": "Off-by-one loop, division by zero, and a dead branch that gcc -Wall does not report.",
        # Same program as examples/interval_demo.c
        "code": """#include <stdio.h>

#define STUDENTS 5

/* Compiles cleanly with `gcc -Wall -Wextra`, yet every function has a bug that
 * interval analysis finds by tracking the range of values each variable can hold. */

int total_marks(void) {
    int marks[STUDENTS];
    int total = 0;
    for (int i = 0; i <= STUDENTS; i++) {   /* i reaches 5: one past the end */
        marks[i] = i * 10;
        total += marks[i];
    }
    return total;
}

int average(int total) {
    int count = 0;                            /* never updated */
    return total / count;
}

int grade(void) {
    int score = 72;
    if (score > 100)                          /* score is always 72 */
        return -1;
    return score / 10;
}

int main(void) {
    int total = total_marks();
    printf("%d %d %d\\n", total, average(total), grade());
    return 0;
}
"""
    }
}

@api_bp.route("/health", methods=["GET"])
def health():
    """Health check endpoint confirming service status and cparse availability."""
    cparse_path = None
    cparse_found = False
    try:
        cparse_path = get_cparse_bin()
        cparse_found = os.path.exists(cparse_path) and os.access(cparse_path, os.X_OK)
    except Exception:
        cparse_found = False

    return jsonify({
        "ok": True,
        "status": "healthy",
        "cparse": {
            "found": cparse_found,
            "path": cparse_path if cparse_found else None,
        }
    })

@api_bp.route("/rules", methods=["GET"])
def list_rules():
    """Return all rules with severities, descriptions, and tiers."""
    return jsonify({
        "ok": True,
        "rules": RULE_CATALOG
    })

@api_bp.route("/examples", methods=["GET"])
def list_examples():
    """List available C example programs."""
    examples_list = []
    for name, item in BUILTIN_EXAMPLES.items():
        examples_list.append({
            "id": name,
            "title": item["title"],
            "description": item["description"],
        })
    return jsonify({
        "ok": True,
        "examples": examples_list
    })

@api_bp.route("/examples/<name>", methods=["GET"])
def get_example(name: str):
    """Return code for a specific example program."""
    # Guard against directory traversal
    if not re.match(r'^[a-zA-Z0-9_.-]+$', name) or ".." in name:
        return jsonify({
            "ok": False,
            "error": {"code": "BAD_REQUEST", "message": "Invalid example name"}
        }), 400

    if name in BUILTIN_EXAMPLES:
        return jsonify({
            "ok": True,
            "name": name,
            "title": BUILTIN_EXAMPLES[name]["title"],
            "description": BUILTIN_EXAMPLES[name]["description"],
            "code": BUILTIN_EXAMPLES[name]["code"]
        })

    # Check on disk in examples/
    examples_dir = os.path.join(os.getcwd(), "examples")
    target_path = os.path.join(examples_dir, name)
    if os.path.exists(target_path) and os.path.isfile(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                code_content = f.read()
            return jsonify({
                "ok": True,
                "name": name,
                "title": name,
                "description": f"File from examples/{name}",
                "code": code_content
            })
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": {"code": "READ_ERROR", "message": str(e)}
            }), 500

    return jsonify({
        "ok": False,
        "error": {"code": "NOT_FOUND", "message": f"Example '{name}' not found"}
    }), 404

@api_bp.route("/analyze", methods=["POST"])
def analyze():
    """Analyze C source code and return diagnostics, metrics, score, and recommendations."""
    if not request.is_json:
        return jsonify({
            "ok": False,
            "error": {"code": "BAD_REQUEST", "message": "Request body must be JSON"}
        }), 400

    data = request.get_json()
    if not isinstance(data, dict) or "code" not in data:
        return jsonify({
            "ok": False,
            "error": {"code": "BAD_REQUEST", "message": "JSON body must contain a 'code' field"}
        }), 400

    code = data.get("code")
    if not isinstance(code, str):
        return jsonify({
            "ok": False,
            "error": {"code": "BAD_REQUEST", "message": "'code' field must be a string"}
        }), 400

    # Payload size check
    code_bytes = code.encode("utf-8")
    if len(code_bytes) > MAX_SOURCE_SIZE:
        return jsonify({
            "ok": False,
            "error": {"code": "PAYLOAD_TOO_LARGE", "message": f"Code size ({len(code_bytes)} bytes) exceeds 100 KB limit"}
        }), 413

    disabled_rules = data.get("disabled_rules")
    options = {}
    if isinstance(disabled_rules, list):
        options["disable"] = disabled_rules

    try:
        res = analyze_source(code, filename="main.c", options=options)
        return jsonify(res.to_dict()), 200
    except ValueError as ve:
        return jsonify({
            "ok": False,
            "error": {"code": "BAD_REQUEST", "message": str(ve)}
        }), 400
    except Exception:
        return jsonify({
            "ok": False,
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to analyze source code"}
        }), 500

@api_bp.route("/ast", methods=["POST"])
def get_ast():
    """Return JSON AST from cparse for the given C code."""
    if not request.is_json:
        return jsonify({
            "ok": False,
            "error": {"code": "BAD_REQUEST", "message": "Request body must be JSON"}
        }), 400

    data = request.get_json()
    if not isinstance(data, dict) or "code" not in data or not isinstance(data["code"], str):
        return jsonify({
            "ok": False,
            "error": {"code": "BAD_REQUEST", "message": "JSON body must contain a 'code' string"}
        }), 400

    code = data["code"]
    if len(code.encode("utf-8")) > MAX_SOURCE_SIZE:
        return jsonify({
            "ok": False,
            "error": {"code": "PAYLOAD_TOO_LARGE", "message": "Code exceeds 100 KB limit"}
        }), 413

    import tempfile, shutil
    temp_dir = tempfile.mkdtemp(prefix="sca_ast_")
    temp_file = os.path.join(temp_dir, "main.c")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code)
        cparse_data = run_cparse(temp_file)
        return jsonify({
            "ok": True,
            "ast": cparse_data
        })
    except Exception:
        return jsonify({
            "ok": False,
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to generate AST"}
        }), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@api_bp.route("/cfg", methods=["POST"])
def get_cfg():
    """Return CFG basic blocks and directional edges for a function."""
    if not request.is_json:
        return jsonify({
            "ok": False,
            "error": {"code": "BAD_REQUEST", "message": "Request body must be JSON"}
        }), 400

    data = request.get_json()
    if not isinstance(data, dict) or "code" not in data or not isinstance(data["code"], str):
        return jsonify({
            "ok": False,
            "error": {"code": "BAD_REQUEST", "message": "JSON body must contain a 'code' string"}
        }), 400

    code = data["code"]
    func_name = data.get("function", "main")

    if len(code.encode("utf-8")) > MAX_SOURCE_SIZE:
        return jsonify({
            "ok": False,
            "error": {"code": "PAYLOAD_TOO_LARGE", "message": "Code exceeds 100 KB limit"}
        }), 413

    import tempfile, shutil
    temp_dir = tempfile.mkdtemp(prefix="sca_cfg_")
    temp_file = os.path.join(temp_dir, "main.c")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code)
        cparse_data = run_cparse(temp_file)
        if "unit" not in cparse_data or cparse_data["unit"] is None:
            return jsonify({
                "ok": False,
                "error": {"code": "PARSE_ERROR", "message": "Source failed to parse"}
            }), 400

        ast = load_ast(cparse_data)
        target_func = None
        for item in ast.items:
            if isinstance(item, FunctionDef) and item.name == func_name:
                target_func = item
                break

        if not target_func:
            return jsonify({
                "ok": False,
                "error": {"code": "NOT_FOUND", "message": f"Function '{func_name}' not found in source"}
            }), 404

        cfg = build_cfg(target_func)
        blocks_data = []
        for b in cfg.blocks:
            blocks_data.append({
                "id": b.bid,
                "label": f"Block {b.bid}" if b not in (cfg.entry, cfg.exit) else ("ENTRY" if b == cfg.entry else "EXIT"),
                "statements_count": len(b.statements),
                "is_entry": b == cfg.entry,
                "is_exit": b == cfg.exit,
            })

        edges_data = []
        for b in cfg.blocks:
            for succ in b.succs:
                edges_data.append({
                    "from": b.bid,
                    "to": succ.bid
                })

        return jsonify({
            "ok": True,
            "function": func_name,
            "blocks": blocks_data,
            "edges": edges_data
        })
    except Exception:
        return jsonify({
            "ok": False,
            "error": {"code": "INTERNAL_ERROR", "message": "Failed to generate CFG"}
        }), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
