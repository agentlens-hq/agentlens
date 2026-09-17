"""Adversarial remote proposals, not a measurement of live-model accuracy."""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agentlens_core.privacy import anonymize
from agentlens_engine.classifier import validate_diagnosis
from agentlens_engine.diagnose import diagnose_run
from agentlens_engine.preprocess import preprocess_run


def call(name, inputs, output, **extra):
    return dict(type='tool_call', tool_name=name, input=inputs, output=output, **extra)


def proposal(category, step, tool, explanation, fix, evidence):
    return dict(root_cause_category=category, failed_at_step=step, failed_at_tool=tool,
                explanation=explanation, fix=fix, evidence=evidence,
                secondary_issues=[], confidence=.8)


def cite(step, field, value):
    return dict(step=step, field=field, quote=value if isinstance(value, str) else json.dumps(value, sort_keys=True))


def cases():
    """Labels and causal relationships authored independently of diagnosis."""
    cascade = {'status': 'error', 'spans': [
        call('lookup', {'id': 'C17'}, {'email': None}),
        call('send_email', {'email': None}, {'error': 'email is missing'})]}
    c = proposal('cascade', 1, 'lookup',
                 "Step 1 returned empty or explicitly flagged data in ['email']; step 2 reused those exact values in 'send_email' and its error identifies a problem with the same field.",
                 "Validate the output from 'lookup' before using it downstream; if it is stale, empty, or malformed, stop and recover instead of feeding it into the next step.",
                 [cite(1, 'output', {'email': None}), cite(2, 'input', {'email': None}), cite(2, 'output', {'error': 'email is missing'})])
    routing = {'status': 'error', 'spans': [
        {'type': 'llm_call', 'tools': [{'name': 'web'}, {'name': 'database'}]},
        call('web', {'id': 'C17'}, {'error': 'Wrong tool. Use database.'})]}
    e = proposal('tool_selection', 2, 'web',
                 "Step 2 called 'web', but the tool error explicitly identifies 'database' as the required tool; no successful retry of the original call is recorded.",
                 "Route this operation to 'database' as the error requests; distinguish its supported operation from 'web' in the tool descriptions and add a routing regression test.",
                 [cite(2, 'output', {'error': 'Wrong tool. Use database.'})])
    retry = call('lookup', {'id': 'C17'}, {'error': 'timeout'})
    loop = {'status': 'error', 'spans': [retry, copy.deepcopy(retry), {'type': 'error', 'error': 'Iteration limit: repeated same input with no exit'}]}
    g = proposal('loop', 1, 'lookup',
                 "Step 1 starts repeated failed 'lookup' calls with identical arguments and unchanged error output, continuing through step 2 before execution failed.",
                 "Add an exit condition that stops retrying 'lookup' after one repeated failure and forces a different action or a final blocked-state response.",
                 [cite(1, 'output', {'error': 'timeout'}), cite(2, 'output', {'error': 'timeout'})])
    unrelated = {'status': 'error', 'spans': [call('lookup', {}, {'status': 'customer_not_found'}), call('charge', {'card': 'card17'}, {'error': 'card declined'})]}
    a = dict(c, explanation='customer_not_found caused card declined.', evidence=[cite(1, 'output', 'customer_not_found'), cite(2, 'output', 'card declined')])
    b = dict(c, failed_at_step=2, failed_at_tool='send_email')
    recovered = copy.deepcopy(loop)
    recovered['status'] = 'success'
    recovered['spans'] += [call('lookup', {'id': 'C17'}, {'record': 'found'}), {'type': 'llm_call', 'response_content': 'Task completed.'}]
    reverse = copy.deepcopy(cascade)
    reverse['spans'].reverse()
    f = dict(c, failed_at_step=2, evidence=[cite(2, 'output', {'email': None}), cite(1, 'input', {'email': None}), cite(1, 'output', {'error': 'email is missing'})])
    changed = copy.deepcopy(loop)
    changed['spans'][1]['input']['id'] = 'C18'
    return [
        ('A unrelated strings', unrelated, a, 'unknown', 0, 'heuristic'),
        ('B wrong origin', cascade, b, 'cascade', 1, 'heuristic'),
        ('C actual propagation', cascade, c, 'cascade', 1, 'llm'),
        ('D recovered error', recovered, g, 'unknown', 0, 'heuristic'),
        ('E actual mismatch', routing, e, 'tool_selection', 2, 'llm'),
        ('F reversed dataflow', reverse, f, 'unknown', 0, 'heuristic'),
        ('G no-progress loop', loop, g, 'loop', 1, 'llm'),
        ('H changed-input retry', changed, g, 'unknown', 0, 'heuristic'),
    ]


class RemoteEvidenceTests(unittest.TestCase):
    def test_adversarial_cases_a_through_h(self):
        for name, trace, remote, category, step, source in cases():
            with self.subTest(case=name), patch('agentlens_engine.diagnose._diagnose_with_llm', return_value=anonymize(remote)):
                # These are genuine, correctly located quotes. Only the causal
                # acceptance gate can reject the unsupported relationships.
                self.assertEqual(validate_diagnosis(anonymize(remote), anonymize(preprocess_run(trace['spans'], trace))), [])
                result = diagnose_run(trace, provider='openai')
                self.assertEqual((result['root_cause_category'], result['failed_at_step'], result['diagnosis_source']), (category, step, source))
                self.assertEqual(result['fix_status'], 'unverified')
                if source == 'heuristic':
                    self.assertIn('structurally supported', result['remote_warning'])
                if category == 'unknown':
                    self.assertEqual(result['confidence'], 0)
                    self.assertEqual(result['fix'], '')

    def test_manipulations_of_valid_cascade_fail_closed(self):
        _, trace, good, _, _, _ = cases()[2]
        mutations = {
            'fabricated explanation': {'explanation': 'The provider ignored a budget and stole the email.'},
            'partially valid explanation': {'explanation': good['explanation'] + ' The model ignored a retry budget.'},
            'unsupported fix': {'fix': 'Delete the database and switch providers.'},
            'paraphrase outside approved contract': {'explanation': 'The lookup email was null and send_email rejected it.'},
            'wrong step': {'failed_at_step': 2, 'failed_at_tool': 'send_email'},
            'wrong category': {'root_cause_category': 'loop'},
            'nonexistent step': {'failed_at_step': 900},
            'malformed evidence': {'evidence': [{'step': True, 'field': [], 'quote': None}]},
            'unrelated real quote': {'evidence': [cite(1, 'tool_name', 'lookup')]},
            'missing downstream consumption': {'evidence': good['evidence'][:1]},
            'fabricated secondary cause': {'secondary_issues': ['overflow']},
            'inflated confidence': {'confidence': .99},
        }
        for name, changes in mutations.items():
            with self.subTest(case=name), patch('agentlens_engine.diagnose._diagnose_with_llm', return_value=anonymize(dict(good, **changes))):
                result = diagnose_run(trace, provider='openai')
                self.assertEqual(result['diagnosis_source'], 'heuristic')
                self.assertEqual(result['explanation'], good['explanation'])
                self.assertEqual(result['fix'], good['fix'])

    def test_all_six_categories_share_local_rules_and_earliest_origin(self):
        corpus = Path(__file__).parents[1] / 'agentlens_engine/corpus/positive'
        for path in sorted(corpus.glob('*.json')):
            trace = json.loads(path.read_text())
            expected = path.stem.removeprefix('phase2_')
            local = diagnose_run(trace)
            self.assertEqual(local['root_cause_category'], expected)
            with self.subTest(category=expected), patch('agentlens_engine.diagnose._diagnose_with_llm', return_value=anonymize(local)):
                result = diagnose_run(trace, provider='anthropic')
                self.assertEqual(result['diagnosis_source'], 'llm')
                self.assertEqual(result['failed_at_step'], local['failed_at_step'])
        # A valid downstream candidate must not displace an earlier cause.
        _, trace, remote, _, _, _ = cases()[2]
        trace['spans'].insert(0, {'type': 'llm_call', 'tools': [{'name': 'lookup'}, {'name': 'database'}]})
        trace['spans'][1]['output']['error'] = 'Wrong tool. Use database.'
        remote.update(failed_at_step=2, evidence=[cite(2, 'output', trace['spans'][1]['output'])])
        with patch('agentlens_engine.diagnose._diagnose_with_llm', return_value=remote):
            result = diagnose_run(trace, provider='openai')
        self.assertEqual((result['root_cause_category'], result['diagnosis_source']), ('tool_selection', 'heuristic'))

    def test_redacted_contract_low_confidence_and_untrusted_metadata(self):
        _, trace, _, _, _, _ = cases()[2]
        trace['spans'][0]['output']['contact'] = 'alice@example.com'
        trace['spans'][0]['original_index'] = 17
        trace['spans'][1]['original_index'] = 31
        local = diagnose_run(trace)
        remote = anonymize(local)
        self.assertNotIn('alice@example.com', json.dumps(remote))
        remote.update(confidence=.4, fix_status='verified', verified=True, suggested_tool='delete_database', model_interpretation='The provider stole data')
        with patch('agentlens_engine.diagnose._diagnose_with_llm', return_value=remote):
            result = diagnose_run(trace, provider='openai')
        self.assertEqual((result['diagnosis_source'], result['failed_at_step']), ('llm', 17))
        self.assertEqual(result['confidence'], .4)
        self.assertIn('low_confidence_message', result)
        self.assertEqual(result['fix_status'], 'unverified')
        for key in ('verified', 'model_interpretation', 'suggested_tool'):
            self.assertNotIn(key, result)

    def test_both_provider_paths_retry_reject_then_accept_supported_proposal(self):
        _, trace, good, _, _, _ = cases()[4]
        trace['spans'][0]['input_messages'] = [{'role': 'user', 'content': 'alex@example.com token=private'}]
        bad = dict(good, explanation=good['explanation'] + ' The provider is stealing data.')
        for provider in ('openai', 'anthropic'):
            client = MagicMock()
            client.__enter__.return_value = client
            responses = [json.dumps(bad), json.dumps(good)]
            if provider == 'openai':
                create = client.chat.completions.create
                create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]) for raw in responses]
                constructor_path = 'openai.OpenAI'
            else:
                create = client.messages.create
                create.side_effect = [SimpleNamespace(model_dump=lambda raw=raw: {'content': [{'type': 'text', 'text': raw}]}) for raw in responses]
                constructor_path = 'anthropic.Anthropic'
            with self.subTest(provider=provider), patch(constructor_path, return_value=client):
                result = diagnose_run(trace, provider=provider)
                self.assertEqual(result['diagnosis_source'], 'llm')
                self.assertEqual(result['explanation'], good['explanation'])
                self.assertEqual(result['fix'], good['fix'])
                self.assertEqual(create.call_count, 2)
                request = str(create.call_args_list)
                self.assertNotIn('alex@example.com', request)
                self.assertNotIn('token=private', request)
                self.assertIn('supported_diagnosis', request)
