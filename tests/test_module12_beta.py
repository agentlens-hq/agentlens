"""Focused recorded-evidence improvements, not live-provider validation."""
import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agentlens
from agentlens_core.privacy import anonymize, residual
from agentlens_core.state import format_state_diff, state_diff
from agentlens_engine.evaluate import _evaluate_directory, _summarize
from agentlens_engine.hallucination import detect_hallucinations
from agentlens_engine.similarity import _fix_outcome, find_similar_failures
from agentlens_sdk import collector as c
from agentlens_sdk.streams import Stream


class RecordedEvidenceTests(unittest.TestCase):
    def test_stream_eof_without_provider_completion_is_partial(self):
        events = [
            ('openai', 'chat', [{'choices': [{'index': 0, 'delta': {'content': 'unfinished'}}]}]),
            ('anthropic', 'messages', [{'type': 'message_start', 'message': {'content': [], 'stop_reason': None}}]),
            ('openai', 'responses', [{'type': 'response.output_text.delta', 'delta': 'unfinished'}])]
        for provider, api, chunks in events:
            with self.subTest(provider=provider, api=api):
                captured = []
                stream = Stream(iter(chunks), provider, api, lambda chunk: chunk,
                                lambda *result: captured.append(result))
                self.assertEqual(list(stream), chunks)
                stream.close()
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0][1], 'partial')

    def test_state_comparison_is_not_display_comparison(self):
        before = {'nested': {'a/b': 1, 'removed': None}, 'long': 'x' * 500 + 'a', 'flag': True}
        after = {'nested': {'a/b': 2, 'added': [1, 2]}, 'long': 'x' * 500 + 'b', 'flag': 1}
        changes = state_diff(before, after)
        self.assertEqual({c['path'] for c in changes}, {'/nested/a~1b', '/nested/removed', '/nested/added', '/long', '/flag'})
        self.assertEqual(next(c for c in changes if c['path'] == '/long')['after'], after['long'])
        self.assertIn('[display truncated]', format_state_diff(before, after))
        self.assertEqual(state_diff({'a': None}, {'a': None}), [])

    def test_memory_is_copied_and_export_redacts_state(self):
        token = c._current_run.set(c.start_run('state'))
        try:
            state = {'account': {'email': 'person@example.com', 'password': 'sample-secret'}, 'input_tokens': 4}
            c.record_memory_snapshot('before', state)
            state['account']['email'] = 'changed@example.com'
            c.record_memory_snapshot('after', state)
            spans = c.current_run()['spans']
            self.assertEqual(spans[0]['state']['account']['email'], 'person@example.com')
            clean = anonymize(c.current_run())
            self.assertFalse(residual(clean))
            self.assertNotIn('sample-secret', json.dumps(clean))
            self.assertNotIn('person@example.com', json.dumps(clean))
            self.assertEqual(clean['spans'][0]['state']['input_tokens'], 4)
        finally:
            c._current_run.reset(token)

    def test_replay_back_full_and_state_diff(self):
        run = {'run_id': 'r', 'spans': [
            {'type': 'memory_snapshot', 'original_index': 3, 'state': {'count': 1}},
            {'type': 'memory_snapshot', 'original_index': 7, 'state': {'count': 2}},
            {'type': 'llm_call', 'original_index': 8, 'response_content': {'choices': [{'message': {'content': 'FULL_RESPONSE'}}]}},
            {'type': 'error', 'original_index': 10, 'error': 'recorded only'}]}
        output = io.StringIO()
        commands = ['', '', 'd', 'b', '', '', 'f', '', 'b', 'q']
        with patch.object(agentlens, '_load_run_or_report', return_value=run), patch('builtins.input', side_effect=commands), contextlib.redirect_stdout(output):
            agentlens._replay_run('r')
        self.assertEqual(output.getvalue().count('Step 3 (span'), 2)
        for expected in ('changed /count', 'FULL_RESPONSE', 'Step 10', 'recorded only'):
            self.assertIn(expected, output.getvalue())

    def test_schemas_are_applied_in_recorded_order(self):
        def definition(field):
            return {'name': 'lookup', 'input_schema': {'properties': {field: {}}, 'required': [field], 'additionalProperties': False}}
        spans = [
            {'type': 'llm_call', 'tools': [definition('legacy_id')]},
            {'type': 'tool_call', 'tool_name': 'lookup', 'input': {'legacy_id': 1}},
            {'type': 'llm_call', 'tools': [definition('account_id')]},
            {'type': 'tool_call', 'tool_name': 'lookup', 'input': {'account_id': 1}}]
        self.assertEqual(detect_hallucinations(spans, [definition('account_id')]), [])
        spans[-1]['input'] = {'legacy_id': 1}
        findings = detect_hallucinations(spans)
        self.assertEqual({f['step'] for f in findings}, {4})
        self.assertEqual({f['type'] for f in findings}, {'invented_param', 'missing_required'})

    def test_nested_async_hierarchy_and_partial_child_snapshot(self):
        token = c._current_run.set(None)
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(c, 'RUNS_DIR', Path(tmp)):
                @c.run('grandchild')
                async def grandchild():
                    c.record_memory_snapshot('start', {'phase': 'running'})
                    path = c.save_run()
                    self.assertEqual(json.loads(path.read_text())['status'], 'running')
                    raise ValueError('local child failure')

                @c.run('child-a')
                async def child_a():
                    await grandchild()

                @c.run('child-b')
                async def child_b():
                    c.record_memory_snapshot('done', {'phase': 'done'})

                @c.run('parent')
                async def parent():
                    await asyncio.gather(child_a(), child_b(), return_exceptions=True)

                asyncio.run(parent())
                runs = c.load_runs()
                named = {r['name']: r for r in runs}
                self.assertEqual(len(runs), 4)
                for child in ('child-a', 'child-b'):
                    self.assertEqual(named[child]['parent_run_id'], named['parent']['run_id'])
                self.assertEqual(named['grandchild']['parent_run_id'], named['child-a']['run_id'])
                self.assertEqual(named['child-a']['status'], 'error')
                self.assertEqual(named['child-b']['status'], 'success')
                self.assertEqual(named['parent']['status'], 'success')
                output = io.StringIO()
                with patch.object(agentlens, '_load_run_or_report', return_value=named['parent']), patch.object(agentlens, 'load_runs', return_value=runs), contextlib.redirect_stdout(output):
                    agentlens._print_stitch(named['parent']['run_id'])
                self.assertIn('grandchild', output.getvalue())
        finally:
            c._current_run.reset(token)

    def test_outcome_does_not_verify_a_new_similar_suggestion(self):
        feedback = {'fix': 'Retry after refreshing the session', 'status': 'resolved', 'source': 'developer', 'recorded_at': '2026-09-16'}
        self.assertEqual(_fix_outcome({'metadata': {'fix_feedback': feedback}}), feedback)
        self.assertIsNone(_fix_outcome({'metadata': {'fix_feedback': {'status': 'resolved'}}}))
        run = {'run_id': 'past', 'metadata': {'fix_feedback': feedback}, 'spans': []}
        fingerprint = {'category': 'loop', 'failed_tool': 'lookup', 'tools': frozenset({'lookup'}), 'error_keywords': frozenset(), 'provider': None, 'cached_fix': 'A new suggestion'}
        with patch('agentlens_engine.similarity._fingerprint', return_value=fingerprint), patch('agentlens_engine.similarity._fingerprint_from_run', return_value=fingerprint):
            results = find_similar_failures({}, {'run_id': 'now'}, [run])
        self.assertEqual(results[0]['fix_status'], 'unverified')
        self.assertEqual(results[0]['developer_fix_outcome']['fix'], feedback['fix'])
        stream = io.StringIO()
        with patch.object(agentlens, '_load_run_or_report', return_value=run), patch.object(agentlens, 'diagnose_run', return_value={}), patch.object(agentlens, 'load_runs', return_value=[run]), patch.object(agentlens, 'find_similar_failures', return_value=results), contextlib.redirect_stdout(stream):
            agentlens._print_similar('past')
        self.assertIn('Suggested fix (unverified): A new suggestion', stream.getvalue())
        self.assertNotIn('Fix used:', stream.getvalue())
        self.assertIn('Change actually tried: Retry after refreshing the session', stream.getvalue())

    def test_evaluation_population_does_not_follow_folder_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'trace.json').write_text(json.dumps({'spans': [], 'expected': {'root_cause_category': 'unknown', 'failed_at_step': 0}}))
            report = _summarize(_evaluate_directory(path, {}, 'real_world'))
        self.assertEqual(report['populations']['external_developer']['total'], 0)
        self.assertEqual(report['populations']['unclassified']['abstained'], 1)

    def test_trust_metrics_keep_partial_wrong_and_abstentions(self):
        row = {'population': 'external_developer', 'source': 'real_world', 'provider_group': 'test', 'path': 'case.json', 'run_id': 'case', 'expected_category': 'loop', 'expected_step': 2, 'actual_category': 'loop', 'actual_step': 3, 'confidence': .85, 'latency_ms': 1, 'scored': True, 'correct': False}
        rows = [row, dict(row, actual_category='unknown', actual_step=0, confidence=0), dict(row, actual_category='cascade')]
        metrics = _summarize(rows)['populations']['external_developer']
        self.assertEqual((metrics['partial'], metrics['wrong'], metrics['abstained']), (1, 1, 1))
        self.assertEqual((metrics['high_confidence_wrong'], metrics['high_confidence']), (2, 2))
