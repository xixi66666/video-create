import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "agent-runtime" / "evals"
spec = importlib.util.spec_from_file_location("score_review", EVALS / "score_review.py")
score_review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score_review)


def test_scenario_export_has_three_distinct_cases_per_role(tmp_path):
    output = tmp_path / "cases.json"
    subprocess.run([sys.executable, "-X", "utf8", str(EVALS / "expert_scenarios.py"),
                    "--root", str(ROOT), "--output", str(output)], check=True)
    cases = json.loads(output.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 57
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(sum(c["role"] == case["role"] for c in cases) == 3 for case in cases)
    assert all(any(c["role"] == case["role"] and c["id"].endswith("-adversarial") for c in cases) for case in cases)
    assert all(len(case["humanReviewExpected"]) >= 2 and len(case["humanReviewForbidden"]) >= 2 for case in cases)


def test_human_review_requires_complete_evidence_and_matches_candidate():
    case = {"id": "case", "humanReviewExpected": ["分析"], "humanReviewForbidden": ["编造"]}
    candidate = {"body": "示例"}
    review = score_review.make_template(case, candidate)
    with pytest.raises(ValueError):
        score_review.evaluate(case, candidate, review)
    review.update(reviewer="reviewer", model="model", modelConfiguration="temperature=0",
                  profileVersion="1.1.0", profileSha256="a" * 64, limitations="无媒体", unresolvedIssues="无")
    review["criteria"][0].update(score=1, evidence="覆盖部分内容")
    review["forbidden"][0].update(observed=False, evidence="未发现")
    report = score_review.evaluate(case, candidate, review)
    assert (report["score"], report["maximum"], report["violations"]) == (1, 2, [])
    with pytest.raises(ValueError, match="校验和"):
        score_review.evaluate(case, {"body": "被更改"}, review)
    review["criteria"][0]["score"] = True
    with pytest.raises(ValueError, match="评分"):
        score_review.evaluate(case, candidate, review)
    review["criteria"][0]["score"] = 2
    review["forbidden"][0]["observed"] = True
    assert score_review.evaluate(case, candidate, review)["violations"] == ["编造"]
    review["criteria"][0]["criterion"] = "篡改标准"
    with pytest.raises(ValueError, match="标准"):
        score_review.evaluate(case, candidate, review)


def test_live_smoke_case_selection_covers_every_exported_case_without_network(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(EVALS))
    spec = importlib.util.spec_from_file_location("deepseek_runtime_smoke", EVALS / "deepseek_runtime_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    output = tmp_path / "cases.json"
    subprocess.run([sys.executable, "-X", "utf8", str(EVALS / "expert_scenarios.py"),
                    "--root", str(ROOT), "--output", str(output)], check=True)
    cases = json.loads(output.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        selected = smoke.resolve_case(case["id"])
        assert all(selected[key] == case[key] for key in ("role", "nodeId", "input", "humanReviewExpected", "humanReviewForbidden"))
    with pytest.raises(ValueError, match="未知评测场景"):
        smoke.resolve_case("offline-unknown")
