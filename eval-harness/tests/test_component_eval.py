"""component_eval.py: what is planted, what is staged, how the Validator's answer is scored. No AWS."""
import json
import random

import component_eval as ce
from fixtures import make_run


def _calcs():
    return {
        "r1": {"id": "r1", "value": 100.0, "importance": "high", "source_file": "./data/x.csv"},
        "r2": {"id": "r2", "value": 2987, "importance": "high", "source_file": "./data/x.csv"},
        "r3": {"id": "r3", "value": 5.0, "importance": "medium", "source_file": "./data/x.csv"},
        "d1": {"id": "d1", "value": 3.39, "importance": "high", "source_file": "./artifacts/media_agg.csv"},
        "d2": {"id": "d2", "value": "n/a", "importance": "high", "source_file": "./artifacts/media_agg.csv"},
    }


def test_pick_plants_splits_raw_and_derived():
    ids, kinds = ce.pick_plants(_calcs(), {"r1": True, "r2": True, "r3": True}, "x.csv", 4, random.Random(0))
    assert sorted(ids) == ["d1", "r1", "r2"]                    # r3 is medium, d2 is not a number
    assert kinds == {"r1": "raw", "r2": "raw", "d1": "derived"}
    ids, _ = ce.pick_plants(_calcs(), {"r1": True, "r2": False}, "x.csv", 2, random.Random(0))
    assert sorted(ids) == ["d1", "r1"]                          # r2 was not confirmed right


def test_planted_value_keeps_the_type_and_differs():
    assert ce.planted_value(2987) == 3286 and isinstance(ce.planted_value(2987), int)
    assert ce.planted_value(3.39) == 3.729 and ce.planted_value(0) == 1 and ce.planted_value(5) == 6


def test_stage_removes_later_outputs_and_plants(tmp_path):
    run = make_run.make_clean_run(tmp_path / "run")
    src = run / "artifacts"
    (src / "code").mkdir(exist_ok=True)
    (src / "code" / "validator_step1.py").write_text("x")
    (src / "code" / "coder_step1.py").write_text("x")
    meta = json.loads((src / "calculation_metadata.json").read_text(encoding="utf-8"))
    cid = meta["calculations"][0]["id"]
    ce.stage(src, tmp_path / "staged", {cid: {"planted": 1.0}})
    staged = tmp_path / "staged"
    assert not (staged / "citations.json").exists() and not (staged / "final_report_with_citations.docx").exists()
    assert not (staged / "code" / "validator_step1.py").exists() and (staged / "code" / "coder_step1.py").exists()
    assert json.loads((staged / "calculation_metadata.json").read_text(encoding="utf-8"))["calculations"][0]["value"] == 1.0


def test_score(tmp_path):
    cites = {"citations": [
        {"citation_id": "[1]", "calculation_id": "r1", "value": 110.0, "verification_status": "needs_review"},
        {"citation_id": "[2]", "calculation_id": "d1", "value": 3.39, "verification_status": "verified"},   # missed, and "corrected"
        {"citation_id": "[3]", "calculation_id": "ok", "value": 7, "verification_status": "needs_review"},   # right value flagged
        {"citation_id": "[4]", "calculation_id": "ok2", "value": 8, "verification_status": "verified"},
    ]}
    (tmp_path / "citations.json").write_text(json.dumps(cites))
    plants = {"r1": {"planted": 110.0}, "d1": {"planted": 3.729}, "r2": {"planted": 3286}}
    r = ce.score(tmp_path, plants, {"r1": "raw", "d1": "derived", "r2": "raw"}, ["ok", "ok2", "r1"])
    assert (r["caught"], r["missed"], r["not_checked"], r["value_changed"]) == (1, 1, 1, 1)
    assert r["recall"] == 0.5 and r["by_kind"]["derived"]["missed"] == 1
    assert (r["false_alarm"], r["right_checked"]) == (1, 2)
