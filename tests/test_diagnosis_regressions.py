import copy
import os
import unittest
from unittest.mock import patch

from agentlens_engine.classifier import validate_diagnosis
from agentlens_engine.diagnose import diagnose_run


def healthy_cases():
    return {
        'weather': [{'type': 'llm_call', 'input_messages': [{'role': 'user', 'content': 'What is the weather?'}], 'response_content': 'Sunny weather.'}],
        'conflicting_reports': [{'type': 'llm_call', 'input_messages': [{'role': 'user', 'content': 'Summarize conflicting reports'}], 'response_content': 'The reports disagree.'}],
        'polling': [{'type': 'tool_call', 'tool_name': 'poll', 'tool_use_id': str(i), 'input': {'job': 'a'}, 'output': {'status': status}} for i, status in enumerate(('pending', 'complete'))],
        'long_answer': [{'type': 'llm_call', 'response_content': 'x' * 5000}],
        'long_run': [{'id': str(i), 'type': 'llm_call', 'response_content': 'Done'} for i in range(201)],
        'search_records': [{'type': 'llm_call', 'tools': [{'name': 'search_customer_records', 'description': 'Search our private CRM records'}, {'name': 'query_inventory', 'description': 'Warehouse quantities'}], 'input_messages': [{'role': 'user', 'content': 'Find customer records'}]}, {'type': 'tool_call', 'tool_name': 'search_customer_records', 'input': {}, 'output': {'result': 'found'}}],
        'partial': [{'type': 'llm_call', 'response_content': 'Working'}],
        'repeated_success': [{'id': str(i), 'type': 'tool_call', 'tool_use_id': str(i), 'tool_name': 'lookup', 'input': {'id': 1}, 'output': {'result': 'ok'}} for i in range(4)],
    }


class DiagnosisRegressions(unittest.TestCase):
    def test_recovered_retries_are_not_a_loop(self):
        spans = [{'type': 'tool_call', 'tool_use_id': str(i), 'tool_name': 'lookup', 'input': {'id': 1}, 'output': {'error': 'timeout'}} for i in range(3)]
        spans += [{'type': 'tool_call', 'tool_use_id': 'recovered', 'tool_name': 'lookup', 'input': {'id': 1}, 'output': {'result': 'found'}}, {'type': 'error', 'error': 'Unrelated export permission failure'}]
        self.assertEqual(diagnose_run({'status': 'error', 'spans': spans})['root_cause_category'], 'unknown')

    def test_healthy_abstention(self):
        for name, spans in healthy_cases().items():
            with self.subTest(case=name):
                result = diagnose_run({'status': 'running' if name == 'partial' else 'success', 'spans': spans}, use_llm=False)
                self.assertEqual(result['root_cause_category'], 'unknown')
                self.assertEqual(result['failed_at_step'], 0)

    def test_env_does_not_enable_remote(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test', 'ANTHROPIC_API_KEY': 'test'}), patch('agentlens_engine.diagnose._diagnose_with_llm', side_effect=AssertionError('remote adapter called')):
            diagnose_run({'spans': []})

    def test_original_step_and_causal_precedence(self):
        spans = [None, {'type': 'llm_call', 'tools': [{'name': 'web', 'description': 'Public pages'}, {'name': 'database', 'description': 'Private data'}]}, {'type': 'tool_call', 'tool_name': 'web', 'input': {'id': 1}, 'output': {'error': 'Wrong tool. Use database instead.'}, 'tool_use_id': 'a'}, {'type': 'tool_call', 'tool_name': 'web', 'input': {'id': 1}, 'output': {'error': 'Wrong tool. Use database instead.'}, 'tool_use_id': 'b'}, {'type': 'error', 'error': 'Repeated with no exit condition'}]
        result = diagnose_run({'status': 'error', 'spans': spans}, use_llm=False)
        self.assertEqual(result['root_cause_category'], 'tool_selection')
        self.assertEqual(result['failed_at_step'], 3)

    def test_reject_bad_llm_schema(self):
        base = {'root_cause_category': 'loop', 'confidence': .8, 'failed_at_step': 999, 'failed_at_tool': 'invented', 'explanation': {}, 'fix': None, 'secondary_issues': []}
        self.assertTrue(validate_diagnosis(base))
        for number in (float('nan'), float('inf'), True):
            bad = copy.deepcopy(base)
            bad['confidence'] = number
            self.assertTrue(validate_diagnosis(bad))
