import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agentlens
from agentlens_core.storage import atomic_write
from agentlens_core.watch import SnapshotWatcher
from agentlens_engine.classifier import validate_diagnosis
from agentlens_engine.clustering import _fingerprint_run
from agentlens_engine.diagnose import diagnose_run
from agentlens_engine.evaluate import evaluate_cases
from agentlens_engine.hallucination import detect_hallucinations
from agentlens_engine.preprocess import preprocess_run
from agentlens_engine.similarity import _fingerprint_from_run
from agentlens_sdk.pricing import compute_cost_usd


class EngineBoundaries(unittest.TestCase):
    def test_hallucination_negation_and_field_association(self):
        tool = {'type': 'tool_call', 'tool_name': 'lookup', 'output': {'customer_id': 'C17', 'balance': 100, 'age': 30}}
        for text in ['C17 balance: 100; age: 30', 'There were 110 requests.', 'Other customer C18 balance: 110']:
            with self.subTest(text=text):
                self.assertEqual(detect_hallucinations([tool, {'type': 'llm_call', 'response_content': {'choices': [{'message': {'content': text}}]}}]), [])
        events = detect_hallucinations([tool, {'type': 'llm_call', 'original_index': 7, 'response_content': {'choices': [{'message': {'content': 'C17 balance: 110'}}]}}])
        self.assertEqual(events[0]['step'], 7)
        self.assertEqual(events[0]['evidence']['field'], 'balance')
        not_found = dict(tool, output={'customer_id': 'C17', 'status': 'not_found'})
        self.assertEqual(detect_hallucinations([not_found, {'type': 'llm_call', 'response_content': 'C17 record was not found'}]), [])
        self.assertTrue(detect_hallucinations([not_found, {'type': 'llm_call', 'response_content': 'C17 record was found'}]))

    def test_schema_additional_properties(self):
        tool = {'name': 'f', 'input_schema': {'type': 'object', 'properties': {'x': {}}, 'required': ['x']}}
        span = {'type': 'tool_call', 'tool_name': 'f', 'input': {'x': 1, 'y': 2}}
        self.assertEqual(detect_hallucinations([span], [tool]), [])
        tool['input_schema']['additionalProperties'] = False
        self.assertEqual(detect_hallucinations([span], [tool])[0]['type'], 'invented_param')
        span['input'] = {}
        self.assertEqual(detect_hallucinations([span], [tool])[0]['type'], 'missing_required')

    def test_grounded_validation_all_invalid_types(self):
        compact = preprocess_run([{'type': 'tool_call', 'tool_name': 'f', 'output': 'error'}])
        valid = {'root_cause_category': 'loop', 'confidence': .8, 'failed_at_step': 1, 'failed_at_tool': 'f', 'explanation': 'Observed error', 'fix': 'Stop after the retry limit', 'secondary_issues': [], 'evidence': [{'step': 1, 'field': 'output', 'quote': 'error'}]}
        self.assertEqual(validate_diagnosis(valid, compact), [])
        mutations = {'root_cause_category': [[], {}, 'fake', None], 'confidence': [float('nan'), float('inf'), True, None], 'failed_at_step': [999, [], None], 'failed_at_tool': ['invented', {}], 'explanation': [{}, None], 'fix': [None], 'evidence': [5, None, [{'step': 1, 'field': 'output', 'quote': 'invented'}]]}
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertTrue(validate_diagnosis(dict(valid, **{field: value}), compact))

    def test_shared_category_and_corpus(self):
        report = evaluate_cases()
        self.assertEqual(report['false_positives'], 0)
        self.assertEqual(report['false_negatives'], 0)
        self.assertEqual(report['category_matches'], report['scored_cases'])
        for result in report['results']:
            run = json.loads(Path(result['path']).read_text())
            category = diagnose_run(run)['root_cause_category']
            self.assertEqual(_fingerprint_run(run)['category'], category)
            self.assertEqual(_fingerprint_from_run(run)['category'], category)

    def test_cost_is_llm_only_and_unknown(self):
        self.assertEqual(agentlens._extract_cost_usd({'type': 'tool_call', 'output': {'total_cost': 12000}}), 0)
        self.assertIsNone(compute_cost_usd('unknown-model', {'input_tokens': 100}))
        self.assertEqual(compute_cost_usd('gpt-4o', {'input_tokens': 0, 'output_tokens': 0}), 0)
        summary = agentlens._summarize_run({'spans': [{'type': 'llm_call', 'cost_usd': None}]})
        self.assertEqual(summary['unknown_cost_calls'], 1)

    def test_watch_same_size_replace_shrink_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'x.json'
            watcher = SnapshotWatcher(Path(directory))
            atomic_write(path, {'run_id': 'x', 'name': 'a', 'spans': []})
            self.assertEqual(len(watcher.poll()), 1)
            with patch('agentlens_core.watch.read_run', side_effect=AssertionError('unchanged file read')):
                self.assertEqual(watcher.poll(), [])
            atomic_write(path, {'run_id': 'x', 'name': 'b', 'spans': []})
            self.assertEqual(watcher.poll()[0][1]['name'], 'b')
            atomic_write(path, {'spans': []})
            self.assertEqual(len(watcher.poll()), 1)
            path.unlink()
            self.assertEqual(watcher.poll(), [])
        for interval in [0, -1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                agentlens._watch_runs(interval)
