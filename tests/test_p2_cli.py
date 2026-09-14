"""Regression coverage for beta-facing CLI reporting defects."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agentlens


class CLIReportingTests(unittest.TestCase):
    def setUp(self):
        self.run = {"run_id": "report", "name": "report", "spans": [
            {"type": "memory_snapshot", "original_index": 42},
            {"type": "llm_call", "original_index": 99, "latency_ms": 25,
             "system": "Keep account data private", "instructions": "Use verified sources",
             "input_messages": [
                 {"role": "user", "content": [{"type": "text", "text": None}]},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call1", "content": "ACCOUNT_PAYLOAD"}]},
                 {"type": "function_call_output", "call_id": "call2", "output": "RESPONSES_PAYLOAD"}],
             "tools": [{"name": "lookup", "input_schema": {"required": ["account_id"]}}],
             "response_content": [{"type": "text", "text": None}],
             "usage": {"input_tokens": 10, "prompt_tokens": 10,
                       "output_tokens": 20, "completion_tokens": 20}},
            {"type": "tool_call", "original_index": 104, "usage": {"input_tokens": 900}}]}

    def output(self, function, *args):
        stream = io.StringIO()
        with patch.object(agentlens, "_load_run_or_report", return_value=self.run), patch("builtins.input", return_value=""), contextlib.redirect_stdout(stream):
            function(*args)
        return stream.getvalue()

    def test_prompt_preserves_captured_context_and_handles_null(self):
        output = self.output(agentlens._print_prompt_viewer, "report", 99)
        for expected in ("Step 99", "Keep account data private", "Use verified sources",
                         "ACCOUNT_PAYLOAD", "RESPONSES_PAYLOAD", "account_id", "null", "10 in / 20 out"):
            self.assertIn(expected, output)

    def test_replay_preserves_original_steps_and_handles_null(self):
        output = self.output(agentlens._replay_run, "report")
        for step in (42, 99, 104):
            self.assertIn(f"Step {step}", output)

    def test_stats_count_llm_aliases_once_and_preserve_original_step(self):
        summary = agentlens._summarize_run(self.run)
        self.assertEqual((summary["input_tokens"], summary["output_tokens"], summary["total_tokens"]), (10, 20, 30))
        self.assertIn("99", summary["slowest_step"])

    def test_usage_zero_and_output_only(self):
        span = self.run["spans"][1]
        span["usage"] = {"input_tokens": 0, "prompt_tokens": 900, "completion_tokens": 5, "total_tokens": 0}
        summary = agentlens._summarize_run(self.run)
        self.assertEqual((summary["input_tokens"], summary["output_tokens"], summary["total_tokens"]), (0, 5, 0))
        self.assertIn("0 in / 5 out", self.output(agentlens._print_prompt_viewer, "report"))

    def test_evaluation_errors_and_unscored_cases_fail_cli_and_doctor(self):
        for field in ("case_errors", "unscored_cases"):
            report = {"fixture_cases": 6, "scored_cases": 16, "overall_accuracy": 1,
                      "healthy_cases": 8, "fixture_accuracy": 1, "low_confidence_rate": 0.5, field: 1}
            with patch.object(agentlens, "evaluate_cases", return_value=report), patch.object(agentlens, "print_evaluation"), patch("sys.argv", ["agentlens", "evaluate"]):
                with self.assertRaises(SystemExit) as result:
                    agentlens.main()
                self.assertEqual(result.exception.code, 1)
                self.assertEqual(agentlens._doctor_evaluation()[0], "FAIL")

    def test_upload_preparation_refusal_is_nonzero(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(agentlens, "_load_run_or_report", return_value=self.run), patch.object(agentlens, "_write_anonymized_run", return_value=None), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                agentlens._prepare_anonymized_upload("report", Path(temp))
            self.assertEqual(result.exception.code, 1)
            self.assertFalse(list(Path(temp).glob("*.anonymized.json")))

    def test_feedback_resolves_run_before_reporting_success(self):
        with patch.object(agentlens, "_load_run_or_report", side_effect=SystemExit(1)), contextlib.redirect_stdout(io.StringIO()) as stream:
            with self.assertRaises(SystemExit):
                agentlens._print_feedback_template("missing")
            self.assertNotIn("# AgentLens Feedback", stream.getvalue())
