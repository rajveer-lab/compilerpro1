import json
import pytest
from sca.web.app import create_app

@pytest.fixture
def client():
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client

def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["status"] == "healthy"
    assert data["cparse"]["found"] is True

def test_rules_endpoint(client):
    res = client.get("/api/rules")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert len(data["rules"]) == 21  # 18 original + 3 interval-analysis rules
    rule_ids = {r["id"] for r in data["rules"]}
    assert "unused-variable" in rule_ids
    assert "missing-return" in rule_ids

def test_examples_list(client):
    res = client.get("/api/examples")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert len(data["examples"]) >= 2
    example_ids = {e["id"] for e in data["examples"]}
    assert "clean.c" in example_ids
    assert "smelly.c" in example_ids

def test_example_detail_valid(client):
    res = client.get("/api/examples/clean.c")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "int main()" in data["code"]

def test_example_detail_not_found(client):
    res = client.get("/api/examples/nonexistent_file_999.c")
    assert res.status_code == 404
    data = res.get_json()
    assert data["ok"] is False
    assert data["error"]["code"] == "NOT_FOUND"

def test_example_path_traversal_blocked(client):
    res = client.get("/api/examples/..%2F..%2Fetc%2Fpasswd")
    assert res.status_code in (400, 404)
    data = res.get_json()
    assert data["ok"] is False

def test_analyze_clean(client):
    code = "int main() {\n    return 0;\n}\n"
    res = client.post("/api/analyze", json={"code": code})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["parse_errors"] == []
    assert data["diagnostics"] == []
    assert data["score"]["value"] == 100
    assert data["score"]["grade"] == "A (Excellent)"
    assert data["projected_score"] == 100
    assert len(data["metrics"]) == 1

def test_analyze_smelly(client):
    code = "int main() {\n    int unused_x;\n    return 0;\n}\n"
    res = client.post("/api/analyze", json={"code": code})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["parse_errors"] == []
    assert len(data["diagnostics"]) == 1
    assert data["diagnostics"][0]["rule_id"] == "unused-variable"
    assert data["score"]["value"] == 98
    assert data["projected_score"] == 100
    assert len(data["recommendations"]) == 1
    assert data["recommendations"][0]["safety"] == "safe"

def test_analyze_disabled_rules(client):
    code = "int main() {\n    int unused_x;\n    return 0;\n}\n"
    res = client.post("/api/analyze", json={"code": code, "disabled_rules": ["unused-variable"]})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["diagnostics"] == []
    assert data["score"]["value"] == 100

def test_analyze_syntax_error(client):
    code = "int main( {"
    res = client.post("/api/analyze", json={"code": code})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert len(data["parse_errors"]) > 0
    assert data["diagnostics"] == []
    assert data["score"] is None
    assert data["recommendations"] == []

def test_analyze_invalid_json_body(client):
    res = client.post("/api/analyze", data="not json", content_type="application/json")
    assert res.status_code == 400
    data = res.get_json()
    assert data["ok"] is False
    assert data["error"]["code"] == "BAD_REQUEST"

def test_analyze_missing_code_field(client):
    res = client.post("/api/analyze", json={"not_code": "xyz"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["ok"] is False
    assert "code" in data["error"]["message"]

def test_analyze_oversized_payload(client):
    large_code = "int main() {\n" + "    int x = 0;\n" * 8000 + "    return 0;\n}\n"
    assert len(large_code.encode("utf-8")) > 100 * 1024
    res = client.post("/api/analyze", json={"code": large_code})
    assert res.status_code == 413
    data = res.get_json()
    assert data["ok"] is False
    assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"

def test_ast_endpoint(client):
    code = "int main() { return 0; }"
    res = client.post("/api/ast", json={"code": code})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "ast" in data
    assert "unit" in data["ast"]

def test_cfg_endpoint(client):
    code = "int main() { if (1) { return 1; } return 0; }"
    res = client.post("/api/cfg", json={"code": code, "function": "main"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["function"] == "main"
    assert len(data["blocks"]) >= 3
    assert len(data["edges"]) >= 2

def test_cfg_function_not_found(client):
    code = "int main() { return 0; }"
    res = client.post("/api/cfg", json={"code": code, "function": "nonexistent"})
    assert res.status_code == 404
    data = res.get_json()
    assert data["ok"] is False

def test_404_error_formatting(client):
    res = client.get("/api/nonexistent_route")
    assert res.status_code == 404
    data = res.get_json()
    assert data["ok"] is False
    assert data["error"]["code"] == "NOT_FOUND"

def test_index_page(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "SCA Analyzer" in html
    assert "main.c" in html
    assert "code-editor" in html

def test_static_assets_served(client):
    # CSS
    res_css = client.get("/css/app.css")
    assert res_css.status_code == 200
    assert "text-main" in res_css.get_data(as_text=True)

    # JS Modules
    for js_path in ["/js/app.js", "/js/editor.js", "/js/panels.js", "/js/theme.js", "/js/api.js"]:
        res_js = client.get(js_path)
        assert res_js.status_code == 200

    # Offline Vendored CodeMirror 5
    res_cm = client.get("/vendor/codemirror/codemirror.js")
    assert res_cm.status_code == 200
    assert "CodeMirror" in res_cm.get_data(as_text=True)
