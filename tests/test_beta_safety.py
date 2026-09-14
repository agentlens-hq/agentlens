import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentlens_engine.diagnose import diagnose_run
from agentlens_sdk.collector import (
    AmbiguousRunIdError,
    append_span,
    load_run,
    load_runs,
    run,
)


class TempCwdTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp.name)

    def tearDown(self) -> None:
        os.chdir(self._old_cwd)
        self._tmp.cleanup()


class RunDecoratorTests(TempCwdTestCase):
    def test_sync_run_is_grouped_and_saved(self) -> None:
        @run(name="sync_agent")
        def run_agent() -> str:
            append_span({"type": "llm_call", "provider": "test"})
            return "ok"

        self.assertEqual(run_agent(), "ok")
        runs = load_runs()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["name"], "sync_agent")
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(runs[0]["spans"][0]["run_id"], runs[0]["run_id"])

    def test_async_run_is_awaited_grouped_and_saved(self) -> None:
        @run(name="async_agent")
        async def run_agent() -> str:
            await asyncio.sleep(0)
            append_span({"type": "llm_call", "provider": "test"})
            return "ok"

        self.assertEqual(asyncio.run(run_agent()), "ok")
        runs = load_runs()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["name"], "async_agent")
        self.assertEqual(runs[0]["status"], "success")
        self.assertEqual(len(runs[0]["spans"]), 1)

    def test_async_run_error_is_captured_and_saved(self) -> None:
        @run(name="async_error_agent")
        async def run_agent() -> None:
            await asyncio.sleep(0)
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            asyncio.run(run_agent())
        runs = load_runs()

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "error")
        self.assertEqual(runs[0]["error"], "boom")
        self.assertEqual(runs[0]["spans"][0]["type"], "error")


class DiagnosisSourceTests(unittest.TestCase):
    def test_heuristic_source_is_set_for_fallback(self) -> None:
        diagnosis = diagnose_run({"run_id": "empty", "spans": []}, use_llm=False)

        self.assertEqual(diagnosis["diagnosis_source"], "heuristic")

    def test_llm_source_is_set_when_llm_diagnosis_validates(self) -> None:
        llm_diagnosis = {
            "root_cause_category": "tool_selection",
            "confidence": 0.9,
            "failed_at_step": 1,
            "failed_at_tool": "search_web",
            "explanation": "The wrong tool was selected.",
            "fix": "Rewrite the tool descriptions.",
            "secondary_issues": [],
            'evidence': [{'step': 1, 'field': 'output', 'quote': 'wrong tool'}],
        }

        with patch("agentlens_engine.diagnose._diagnose_with_llm", return_value=llm_diagnosis):
            diagnosis = diagnose_run({"run_id": "llm", "spans": [{'type': 'tool_call', 'tool_name': 'search_web', 'output': 'wrong tool'}]}, provider='openai')

        self.assertEqual(diagnosis["diagnosis_source"], "llm")


class RunIdLookupTests(TempCwdTestCase):
    def test_ambiguous_prefix_raises_with_matching_ids(self) -> None:
        runs_dir = Path(".agentlens") / "runs"
        runs_dir.mkdir(parents=True)
        for run_id in ["abc111", "abc222"]:
            (runs_dir / f"{run_id}.json").write_text(
                json.dumps({"run_id": run_id, "name": "case", "spans": []}),
                encoding="utf-8",
            )

        with self.assertRaises(AmbiguousRunIdError) as context:
            load_run("abc")

        self.assertEqual(context.exception.prefix, "abc")
        self.assertCountEqual(context.exception.matches, ["abc111", "abc222"])


if __name__ == "__main__":
    unittest.main()
