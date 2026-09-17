"""Distinct beta trust probes. Known failures deliberately remain failing.

Ground truth below is authored before diagnosis. These are constructed regression
probes, NOT natural failures, external developers, or live-provider results.
"""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from agentlens_engine.diagnose import diagnose_run


def tool(name='lookup', output=None, **kwargs):
    return {'type': 'tool_call', 'tool_name': name, 'input': {'id': 'C17'}, 'output': output, **kwargs}


def audit_cases():
    definitions = {'type': 'llm_call', 'tools': [{'name': 'web', 'description': 'Find customer information'}, {'name': 'database', 'description': 'Find customer information'}]}
    failed = tool(output={'error': 'timeout'})
    recovered = tool(output={'record': 'found'})
    cases = [
        ('recovered_retry', 'unknown', 0, [failed, recovered], 'error'),
        ('tool_selection_then_cascade', 'tool_selection', 2, [definitions, tool('web', {'error': 'Wrong tool. Use database.', 'customer_id': ''}), tool('charge', {'error': 'customer_id is missing'}, input={'customer_id': ''})], 'error'),
        ('partial_run', 'unknown', 0, [tool(output=None, completed=False)], 'running'),
        ('malformed_tool_output', 'unknown', 0, [tool(output=[None, 'unexpected'])], 'error'),
        ('subtle_wrong_tool_insufficient_evidence', 'unknown', 0, [definitions, tool('web', {'text': 'Public profile'})], 'error'),
        ('overlapping_tools_correct_success', 'unknown', 0, [definitions, tool('database', {'record': 'found'})], 'success'),
        ('unrelated_warning_then_failure', 'unknown', 0, [tool(output={'warning': 'Invalid policy discussed in user notes', 'customer_id': 'C17'}), tool('charge', {'error': 'Payment provider unavailable'}, input={'customer_id': 'C17'})], 'error'),
        ('justified_retry', 'unknown', 0, [failed, failed, recovered, {'type': 'error', 'error': 'Unrelated export permission failure'}], 'error'),
        ('external_dependency', 'unknown', 0, [failed, {'type': 'error', 'error': 'HTTP 503 upstream unavailable'}], 'error'),
        ('insufficient_evidence', 'unknown', 0, [None, {'type': 'llm_call', 'response_content': None}], 'partial'),
        ('tool_error_then_loop', 'loop', 1, [failed, failed, {'type': 'error', 'error': 'Iteration limit: repeated same input with no exit'}], 'error'),
    ]
    with (Path(__file__).parents[1] / 'agentlens_engine/corpus/positive/phase2_state_drift.json').open() as handle:
        drift = json.load(handle)
    drift['spans'] += [{'type': 'llm_call', 'response_content': 'I restored the refund task.'}, tool('query_db', {'refund_status': 'completed'}), {'type': 'llm_call', 'response_content': 'Your refund is completed.'}]
    cases.append(('state_change_then_recovery', 'unknown', 0, drift['spans'], 'error'))
    return [(name, category, step, {'status': status, 'spans': copy.deepcopy(spans)}) for name, category, step, spans, status in cases]


class BetaTrustTests(unittest.TestCase):
    def test_distinct_offline_regressions(self):
        for name, category, step, trace in audit_cases():
            with self.subTest(name=name):
                result = diagnose_run(trace)
                self.assertEqual((result['root_cause_category'], result['failed_at_step']), (category, step))

    def test_remote_quote_is_not_enough_to_establish_causality(self):
        trace = {'status': 'success', 'spans': [tool(output={'record': 'found'})]}
        invented = {'root_cause_category': 'loop', 'confidence': .99, 'failed_at_step': 1, 'failed_at_tool': 'lookup',
                    'explanation': 'The agent looped forever because the model ignored a retry budget.',
                    'fix': 'Delete lookup and switch providers.', 'secondary_issues': [],
                    'evidence': [{'step': 1, 'field': 'output', 'quote': 'found'}]}
        with patch('agentlens_engine.diagnose._diagnose_with_llm', return_value=invented):
            result = diagnose_run(trace, provider='openai')
        self.assertEqual(result['root_cause_category'], 'unknown')
        self.assertEqual(result['diagnosis_source'], 'heuristic')

    def test_state_drift_precedes_wrong_tool(self):
        with (Path(__file__).parents[1] / 'agentlens_engine/corpus/positive/phase2_state_drift.json').open() as handle:
            trace = json.load(handle)
        trace['spans'][0]['tools'] = [{'name': 'weather_api'}, {'name': 'query_db'}]
        trace['spans'][1]['output'] = {'error': 'Wrong tool. Use query_db.'}
        result = diagnose_run(trace)
        self.assertEqual((result['root_cause_category'], result['failed_at_step']), ('state_drift', 1))
        self.assertIn('tool_selection', result['secondary_issues'])

    def test_conflicting_tool_evidence_does_not_choose_arbitrary_target(self):
        trace = {'status': 'error', 'spans': [
            {'type': 'llm_call', 'tools': [{'name': 'web'}, {'name': 'billing'}, {'name': 'crm'}]},
            tool('web', {'error': 'Wrong tool. Use billing.', 'expected_tool': 'crm'})]}
        result = diagnose_run(trace)
        self.assertEqual(result['root_cause_category'], 'unknown')


if __name__ == '__main__':
    unittest.main()
