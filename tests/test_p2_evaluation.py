"""Evaluation must retain bad/unlabeled cases and count negatives by ground truth."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentlens_engine.evaluate import (
    _evaluate_directory,
    _expected_for,
    _summarize,
    print_evaluation,
)


class EvaluationHonestyTests(unittest.TestCase):
    def row(self, **changes):
        row = {"source": "real_world", "provider_group": "test", "path": "case.json",
               "run_id": "case", "expected_category": "unknown", "expected_step": 0,
               "actual_category": "tool_selection", "actual_step": 2, "confidence": 0.85,
               "latency_ms": 1.0, "scored": True, "correct": False}
        row.update(changes)
        return row

    def test_external_negative_counts_false_positive_and_confident_wrong(self):
        report = _summarize([self.row()])
        self.assertEqual(report["healthy_cases"], 1)
        self.assertEqual(report["false_positives"], 1)
        self.assertEqual(report["confident_wrong"], 1)
        self.assertEqual(report["high_confidence_cases"], 1)

    def test_partial_and_completed_controls_are_distinguished(self):
        report = _summarize([
            self.row(execution_status="completed", actual_category="unknown", actual_step=0, confidence=0.2, correct=True),
            self.row(execution_status="partial", actual_category="unknown", actual_step=0, confidence=0.2, correct=True)])
        self.assertEqual(report["control_statuses"], {"completed": 1, "partial": 1})
        self.assertEqual(report["low_confidence_cases"], 2)
        self.assertEqual(report["diagnosed_cases"], 2)

    def test_invalid_expectation_fields_are_actionable(self):
        invalid = [([], 0), ("not_a_category", 1), ("loop", True), ("loop", -1),
                   ("unknown", 1), ("loop", 0), ("loop", 99)]
        for category, step in invalid:
            with self.subTest(category=category, step=step), self.assertRaisesRegex(ValueError, "expectation.*(root_cause_category|failed_at_step)"):
                _expected_for({"spans": [{"original_index": 2}], "expected": {
                    "root_cause_category": category, "failed_at_step": step}}, None)

    def test_bad_files_retained_and_identified(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "broken.json").write_text("{", encoding="utf-8")
            (directory / "unlabeled.json").write_text(json.dumps({"run_id": "unlabeled", "spans": []}), encoding="utf-8")
            results = _evaluate_directory(directory, {}, "real_world")
        report = _summarize(results)
        self.assertEqual(report["total_cases"], 2)
        self.assertEqual(report["case_errors"], 1)
        self.assertEqual(report["unscored_cases"], 2)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            print_evaluation(report)
        self.assertIn("broken.json", stream.getvalue())
        self.assertIn("Errors / unscored", stream.getvalue())

    def test_diagnosis_failure_cannot_disappear(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "case.json"
            path.write_text(json.dumps({"run_id": "case", "spans": [], "expected": {
                "root_cause_category": "unknown", "failed_at_step": 0}}), encoding="utf-8")
            with patch("agentlens_engine.evaluate.diagnose_run", side_effect=ValueError("diagnosis failed")):
                report = _summarize(_evaluate_directory(Path(temp), {}, "real_world"))
        self.assertEqual(report["total_cases"], 1)
        self.assertEqual(report["scored_cases"], 1)
        self.assertEqual(report["overall_accuracy"], 0)
        self.assertEqual(report["case_errors"], 1)

    def test_abstention_and_wrong_step_stay_in_denominator(self):
        report = _summarize([
            self.row(expected_category="loop", expected_step=2, actual_category="unknown", actual_step=0, confidence=0.2),
            self.row(expected_category="loop", expected_step=2, actual_category="loop", actual_step=3)])
        self.assertEqual(report["scored_cases"], 2)
        self.assertEqual(report["category_matches"], 1)
        self.assertEqual(report["step_matches"], 0)
        self.assertEqual(report["false_negatives"], 1)
        self.assertEqual(report["abstentions"], 1)
        self.assertEqual(report["confident_wrong"], 1)

    def test_bad_sibling_expectation_is_retained_with_file_and_field(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "case.json").write_text(json.dumps({"run_id": "case", "spans": []}), encoding="utf-8")
            (directory / "expected_diagnosis.json").write_text(json.dumps({"root_cause_category": [], "failed_at_step": 0}), encoding="utf-8")
            results = _evaluate_directory(directory, {}, "real_world")
        self.assertEqual(len(results), 1)
        self.assertIn("expected_diagnosis.json", results[0]["error"])
        self.assertIn("root_cause_category", results[0]["error"])
