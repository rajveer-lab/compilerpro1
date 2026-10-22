import json
import subprocess
import sys

from sca.misconceptions import MISCONCEPTIONS, RULE_MISCONCEPTIONS, diagnose, misconception_for
from sca.rules.registry import RULE_CATALOG
from sca.service import analyze_source


def test_every_mapping_points_at_a_known_rule_and_misconception():
    rule_ids = {r["id"] for r in RULE_CATALOG} | {"uninitialized-variable"}
    for rule_id, mid in RULE_MISCONCEPTIONS.items():
        assert rule_id in rule_ids, rule_id
        assert mid in MISCONCEPTIONS, mid
    for m in MISCONCEPTIONS.values():
        assert m.title and m.explanation and m.fix


def test_style_rules_have_no_misconception():
    assert misconception_for("magic-number") is None
    assert misconception_for("naming-convention") is None


def test_diagnose_groups_by_misconception():
    diags = [
        {"rule_id": "index-out-of-range", "line": 12},
        {"rule_id": "const-index-out-of-bounds", "line": 4},
        {"rule_id": "index-out-of-range", "line": 12},
        {"rule_id": "assignment-in-condition", "line": 7},
        {"rule_id": "magic-number", "line": 7},
    ]
    result = diagnose(diags)
    assert [m["id"] for m in result] == ["array-index-n", "assign-compares"]
    assert result[0]["lines"] == [12, 4]
    assert result[0]["rule_ids"] == ["index-out-of-range", "const-index-out-of-bounds"]


CODE = """
int main(void) {
    int marks[5];
    int sum;
    int x = 3;
    for (int i = 0; i <= 5; i++)
        marks[i] = i;
    if (x = 4)
        sum = sum + marks[0];
    return sum;
}
"""


def test_service_tags_diagnostics():
    result = analyze_source(CODE)
    ids = {m["id"] for m in result.misconceptions}
    assert {"array-index-n", "assign-compares", "auto-zero"} <= ids
    tagged = [d for d in result.diagnostics if d["rule_id"] == "index-out-of-range"]
    assert tagged and all(d["misconception"] == "array-index-n" for d in tagged)
    assert "misconceptions" in result.to_dict()


def test_cli_explain(tmp_path):
    c_file = tmp_path / "m.c"
    c_file.write_text(CODE)
    run = lambda *extra: subprocess.run(
        [sys.executable, "-m", "sca", "analyze", str(c_file), *extra],
        capture_output=True, text=True)
    plain = json.loads(run().stdout)
    assert all("misconception" not in d for d in plain)
    explained = json.loads(run("--explain").stdout)
    first = next(d for d in explained if d["rule_id"] == "assignment-in-condition")
    assert first["misconception"]["id"] == "assign-compares"
