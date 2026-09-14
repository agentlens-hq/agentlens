import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentlens_sdk import collector as c


class TraceContractTests(unittest.TestCase):
    def setUp(self):
        self.token = c._current_run.set(c.start_run())

    def tearDown(self):
        c._current_run.reset(self.token)

    def test_idempotent_results_and_none_completion(self):
        c.append_span({'type': 'tool_call', 'tool_name': 'lookup', 'tool_use_id': 'a', 'input': {}, 'output': None})
        for output in (None, {'result': 1}, {'result': 2}):
            c.record_tool_result('lookup', output, tool_use_id='a')
        self.assertEqual(len(c.current_run()['spans']), 1)
        self.assertEqual(c.current_run()['spans'][0]['output'], {'result': 2})
        self.assertTrue(c.current_run()['spans'][0]['completed'])
        c.record_tool_result('lookup', None, tool_use_id='b')
        self.assertEqual(len(c.current_run()['spans']), 2)
        self.assertTrue(c.current_run()['spans'][1]['completed'])

    def test_save_error_does_not_mask_result_or_context(self):
        outer = c.current_run()
        @c.run('ok')
        def work():
            return 42
        with patch.object(c, 'save_run', side_effect=OSError('disk full')), self.assertWarns(RuntimeWarning):
            self.assertEqual(work(), 42)
        self.assertIs(c.current_run(), outer)

    def test_cancellation_is_preserved(self):
        saved = []
        @c.run('cancel')
        async def work():
            raise asyncio.CancelledError()
        with patch.object(c, 'save_run', side_effect=lambda **kw: saved.append(kw['run'])):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(work())
        self.assertEqual(saved[0]['status'], 'cancelled')

    def test_partial_save_does_not_finalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            c.save_run(str(Path(tmp) / 'run.json'))
        self.assertEqual(c.current_run()['status'], 'running')
        self.assertIsNone(c.current_run()['ended_at'])

    def test_partial_stream_and_pending_tool_do_not_appear_completed(self):
        for span in [{'type': 'llm_call', 'status': 'partial'}, {'type': 'tool_call', 'output': None, 'completed': False}]:
            saved = []
            @c.run('partial')
            def work():
                c.append_span(span)
            with patch.object(c, 'save_run', side_effect=lambda **kw: saved.append(kw['run'])):
                work()
            self.assertEqual(saved[0]['status'], 'partial')

    def test_load_rejects_shapes_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(c, 'RUNS_DIR', Path(tmp)):
            for value in ([], 42, {'spans': [{'type': 'llm_call', 'input_messages': 42}]}):
                Path(tmp, 'a.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    c.load_run('a')
            for run_id in ('../a', '/tmp/a', '..\\a', ''):
                with self.assertRaises(ValueError):
                    c.load_run(run_id)

    def test_unrelated_corrupt_file_does_not_block_prefix(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(c, 'RUNS_DIR', Path(tmp)):
            Path(tmp, 'bad.json').write_text('{')
            Path(tmp, 'good-123.json').write_text(json.dumps({'run_id': 'good-123', 'spans': []}))
            self.assertEqual(c.load_run('good')['run_id'], 'good-123')
