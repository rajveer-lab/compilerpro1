import sys
import json
import argparse
from sca.frontend.runner import run_cparse, run_cparse_tokens
from sca.frontend.loader import load_ast
from sca.service import analyze_file

def main():
    parser = argparse.ArgumentParser(prog="sca", description="Static Code Quality Analyzer for C")
    subparsers = parser.add_subparsers(dest="command")

    parser_tokens = subparsers.add_parser("tokens", help="Dump tokens")
    parser_tokens.add_argument("file", help="Path to the C file")

    parser_parse = subparsers.add_parser("parse", help="Dump AST")
    parser_parse.add_argument("file", help="Path to the C file")

    parser_cfg = subparsers.add_parser("cfg", help="Dump CFG for a function")
    parser_cfg.add_argument("file", help="Path to the C file")
    parser_cfg.add_argument("func", help="Function name")

    parser_liveness = subparsers.add_parser("liveness", help="Dump Liveness IN/OUT sets for a function")
    parser_liveness.add_argument("file", help="Path to the C file")
    parser_liveness.add_argument("func", help="Function name")

    parser_ranges = subparsers.add_parser("ranges", help="Dump interval-analysis value ranges for a function")
    parser_ranges.add_argument("file", help="Path to the C file")
    parser_ranges.add_argument("func", help="Function name")

    parser_score = subparsers.add_parser("score", help="Calculate a code quality score")
    parser_score.add_argument("file", help="Path to the C file")

    parser_metrics = subparsers.add_parser("metrics", help="Show code metrics per function")
    parser_metrics.add_argument("file", help="Path to the C file")
    parser_metrics.add_argument("--json", action="store_true", help="Output metrics as JSON")

    parser_analyze = subparsers.add_parser("analyze", help="Analyze code quality")
    parser_analyze.add_argument("file", help="Path to the C file")
    parser_analyze.add_argument("--rule", action="append", help="Only run these rules")
    parser_analyze.add_argument("--disable", action="append", help="Disable these rules")
    parser_analyze.add_argument("--fail-on", default="error,warning", help="Comma-separated severities to exit 1 on")

    parser_web = subparsers.add_parser("web", help="Start the web UI server")
    parser_web.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser_web.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser_web.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()

    if args.command == "tokens":
        try:
            data = run_cparse_tokens(args.file)
        except Exception:
            data = run_cparse(args.file)
        print(json.dumps(data, indent=2))

    elif args.command == "parse":
        data = run_cparse(args.file)
        if "unit" not in data or data["unit"] is None:
            print(json.dumps(data, indent=2))
            sys.exit(2)
        ast = load_ast(data)
        import pprint
        pprint.pprint(ast)

    elif args.command == "cfg":
        data = run_cparse(args.file)
        if "unit" not in data or data["unit"] is None:
            sys.exit(2)
        ast = load_ast(data)
        from sca.analysis.cfg import build_cfg
        from sca.ast.nodes import FunctionDef
        found = False
        for item in ast.items:
            if isinstance(item, FunctionDef) and item.name == args.func:
                cfg = build_cfg(item)
                print(cfg.to_string())
                found = True
                break
        if not found:
            print(f"Function {args.func} not found.")

    elif args.command == "liveness":
        data = run_cparse(args.file)
        if "unit" not in data or data["unit"] is None:
            sys.exit(2)
        ast = load_ast(data)
        from sca.analysis.cfg import build_cfg
        from sca.analysis.liveness import LivenessAnalysis
        from sca.ast.nodes import FunctionDef
        found = False
        for item in ast.items:
            if isinstance(item, FunctionDef) and item.name == args.func:
                cfg = build_cfg(item)
                analysis = LivenessAnalysis(cfg)
                analysis.run()
                for b in cfg.blocks:
                    print(f"Block {b.bid}:")
                    print(f"  IN:  {analysis.in_sets[b.bid]}")
                    print(f"  OUT: {analysis.out_sets[b.bid]}")
                found = True
                break
        if not found:
            print(f"Function {args.func} not found.")

    elif args.command == "ranges":
        data = run_cparse(args.file)
        if "unit" not in data or data["unit"] is None:
            sys.exit(2)
        ast = load_ast(data)
        from sca.analysis.intervals import analyze_function
        from sca.ast.nodes import FunctionDef
        found = False
        for item in ast.items:
            if isinstance(item, FunctionDef) and item.name == args.func:
                print(analyze_function(ast, item).describe())
                found = True
                break
        if not found:
            print(f"Function {args.func} not found.")

    elif args.command == "score":
        try:
            result = analyze_file(args.file)
        except Exception:
            print("Failed to parse file.")
            sys.exit(2)

        if result.score is None or result.parse_errors:
            print("Failed to parse file.")
            sys.exit(2)

        print(result.score.format_cli())

    elif args.command == "metrics":
        try:
            result = analyze_file(args.file)
        except Exception as e:
            print(f"Failed to analyze metrics: {e}")
            sys.exit(2)

        if result.parse_errors:
            print(json.dumps(result.parse_errors, indent=2))
            sys.exit(2)

        if getattr(args, "json", False):
            print(json.dumps(result.metrics, indent=2))
        else:
            if not result.metrics:
                print("No functions found.")
            else:
                print(f"{'Function':<20} {'LOC':<6} {'Params':<8} {'Max Nesting':<12} {'Cyclomatic':<10}")
                print("-" * 60)
                for m in result.metrics:
                    print(f"{m['function']:<20} {m['loc']:<6} {m['params']:<8} {m['max_nesting']:<12} {m['cyclomatic']:<10}")

    elif args.command == "analyze":
        try:
            result = analyze_file(args.file, options={
                "rule": getattr(args, "rule", None),
                "disable": getattr(args, "disable", None),
            })
        except Exception as e:
            print(json.dumps({"error": str(e)}, indent=2))
            sys.exit(2)

        if result.parse_errors:
            print(json.dumps(result.parse_errors, indent=2))
            sys.exit(2)

        out = []
        for diag in result.diagnostics:
            out.append({
                "file": diag["file"],
                "line": diag["line"],
                "col": diag["col"],
                "message": diag["message"],
                "rule_id": diag["rule_id"]
            })

        print(json.dumps(out, indent=2))

        fail_on = {s.strip() for s in args.fail_on.split(",") if s.strip()}
        if any(diag["severity"] in fail_on for diag in result.diagnostics):
            sys.exit(1)

    elif args.command == "web":
        from sca.web.app import create_app
        print(f"Starting SCA Web Server at http://{args.host}:{args.port}")
        app = create_app()
        app.run(host=args.host, port=args.port, debug=args.debug)

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
