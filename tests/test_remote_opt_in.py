import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agentlens_engine.diagnose import diagnose_run


class RemoteOptIn(unittest.TestCase):
    def test_redacted_request_bounded_retry_and_grounded_fix_preserved(self):
        run = {'status': 'error', 'spans': [{'type': 'llm_call', 'input_messages': [{'role': 'user', 'content': 'email alex@example.com token=private'}], 'tools': [{'name': 'wrong'}, {'name': 'correct'}]}, {'type': 'tool_call', 'tool_name': 'wrong', 'output': {'error': 'Use correct'}}]}
        result = {'root_cause_category': 'tool_selection', 'confidence': .8, 'failed_at_step': 2, 'failed_at_tool': 'wrong', 'explanation': 'Tool error directs operation to correct', 'fix': 'Change the selected function from wrong to correct at this call site.', 'secondary_issues': [], 'evidence': [{'step': 2, 'field': 'output', 'quote': 'Use correct'}]}
        client = MagicMock()
        client.__enter__.return_value = client
        client.chat.completions.create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='not json'))]), SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))])]
        with patch('openai.OpenAI', return_value=client) as constructor:
            diagnosis = diagnose_run(run, provider='openai')
        self.assertEqual(diagnosis['diagnosis_source'], 'llm')
        self.assertEqual(diagnosis['fix'], result['fix'])
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertEqual(constructor.call_args.kwargs['max_retries'], 0)
        self.assertEqual(constructor.call_args.kwargs['timeout'].connect, 3)
        self.assertEqual(constructor.call_args.kwargs['timeout'].read, 10)
        request = str(client.chat.completions.create.call_args)
        self.assertNotIn('alex@example.com', request)
        self.assertNotIn('token=private', request)

    def test_provider_error_is_one_attempt_and_fallback(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.chat.completions.create.side_effect = OSError('offline')
        with patch('openai.OpenAI', return_value=client):
            diagnosis = diagnose_run({'spans': []}, provider='openai')
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(diagnosis['diagnosis_source'], 'heuristic')
        self.assertEqual(diagnosis['confidence'], 0)

    def test_oversized_remote_input_never_transmits(self):
        spans = [{'type': 'llm_call', 'input_messages': [{'role': 'user', 'content': 'x' * 2000}], 'response_content': 'y' * 2000} for _ in range(200)]
        with patch('openai.OpenAI', side_effect=AssertionError('oversized request sent')):
            diagnosis = diagnose_run({'spans': spans}, provider='openai')
        self.assertEqual(diagnosis['diagnosis_source'], 'heuristic')
