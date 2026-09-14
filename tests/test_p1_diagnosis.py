import copy
import unittest

from agentlens_engine.diagnose import diagnose_run
from agentlens_engine.evaluate import evaluate_cases


def tool(name, arguments, output, call_id):
    return {'type': 'tool_call', 'tool_name': name, 'input': arguments,
            'output': output, 'tool_use_id': call_id}


def session_run():
    return {'status': 'success', 'spans': [
        {'type': 'llm_call', 'tools': [
            {'name': 'lookup_account', 'description': 'Get account status by ID.'},
            {'name': 'refresh_session', 'description': 'Renew an expired API session.'}],
         'input_messages': [{'role': 'user', 'content': 'Get account C17 status.'}]},
        tool('lookup_account', {'id': 'C17'},
             {'error': 'Session expired. Use refresh_session before retrying this request.'}, 'a1'),
        tool('refresh_session', {}, {'status': 'ok'}, 'a2'),
        tool('lookup_account', {'id': 'C17'}, {'id': 'C17', 'status': 'active'}, 'a3'),
        {'type': 'llm_call', 'response_content': 'Account C17 is active.'},
    ]}


class P1ToolSelection(unittest.TestCase):
    def assert_abstains(self, run):
        result = diagnose_run(run)
        self.assertEqual(result['root_cause_category'], 'unknown', result)
        self.assertEqual(result['failed_at_step'], 0)
        self.assertEqual(result['confidence'], 0)
        self.assertEqual(result['fix'], '')

    def test_expired_session_recovery_is_not_wrong_tool(self):
        self.assert_abstains(session_run())

    def test_unrecovered_prerequisite_is_not_wrong_tool_either(self):
        run = session_run()
        run['status'] = 'error'
        run['spans'] = run['spans'][:2] + [{'type': 'error', 'error': 'Session renewal unavailable.'}]
        self.assert_abstains(run)

    def test_routing_wording_alone_is_not_mismatch_evidence(self):
        run = session_run()
        run['spans'][1]['output'] = {'error': 'Use refresh_session to inspect the session.'}
        self.assert_abstains(run)

    def test_successful_retry_outweighs_an_earlier_routing_hint(self):
        run = session_run()
        run['spans'][1]['output'] = {'error': 'Wrong tool. Use refresh_session instead.'}
        self.assert_abstains(run)
        run['status'] = 'error'
        run['spans'].append({'type': 'error', 'error': 'Unrelated export permission failure.'})
        self.assert_abstains(run)

    def test_explicit_mismatch_is_still_strong_without_recovery(self):
        for output in (
            {'error': 'Wrong tool. Use refresh_session instead.'},
            {'error': 'This operation is only available in refresh_session.'},
            {'error': 'Unsupported operation.', 'expected_tool': 'refresh_session'},
        ):
            with self.subTest(output=output):
                run = session_run()
                run['status'] = 'error'
                run['spans'] = run['spans'][:2]
                run['spans'][1]['output'] = copy.deepcopy(output)
                result = diagnose_run(run)
                self.assertEqual(result['root_cause_category'], 'tool_selection')
                self.assertEqual(result['failed_at_step'], 2)
                self.assertGreaterEqual(result['confidence'], .8)
                self.assertIn('refresh_session', result['fix'])

    def test_existing_corpus_categories_and_steps_are_preserved(self):
        report = evaluate_cases()
        self.assertEqual(report['category_matches'], report['scored_cases'])
        self.assertEqual(report['step_matches'], report['scored_cases'])


def purchase_run(output, arguments=None, error='Payment declined: insufficient funds.'):
    return {'status': 'error', 'spans': [
        {'type': 'llm_call', 'input_messages': [{'role': 'user', 'content': 'Buy the requested book.'}]},
        tool('find_book', {'title': 'Requested book'}, output, 'b1'),
        tool('purchase_book', arguments or {'book_id': 'B17'}, {'error': error}, 'b2'),
        {'type': 'error', 'error': error},
    ]}


class P1Cascade(unittest.TestCase):
    def test_ordinary_content_never_flags_upstream_data(self):
        for word in ('invalid', 'error', 'failed', 'null', 'missing', 'malformed', 'stale', 'corrupt'):
            with self.subTest(word=word):
                result = diagnose_run(purchase_run({'book_id': 'B17', 'title': f'Repair {word} JSON'}))
                self.assertEqual(result['root_cause_category'], 'unknown', result)
                self.assertEqual(result['confidence'], 0)

    def test_flagged_field_does_not_explain_unrelated_payment_failure(self):
        result = diagnose_run(purchase_run({'book_id': 'B17', 'warning': 'invalid book_id'}))
        self.assertEqual(result['root_cause_category'], 'unknown', result)

    def test_bad_value_must_be_the_value_consumed(self):
        result = diagnose_run(purchase_run(
            {'book_id': 'bad', 'warning': 'invalid book_id'},
            {'book_id': 'different'}, 'invalid book_id'))
        self.assertEqual(result['root_cause_category'], 'unknown', result)

    def test_truncation_does_not_make_distinct_values_look_propagated(self):
        prefix = 'x' * 1100
        run = purchase_run({'book_id': prefix + 'source', 'warning': 'invalid book_id'},
                           {'book_id': prefix + 'other'}, 'invalid book_id')
        self.assertEqual(diagnose_run(run)['root_cause_category'], 'unknown')

    def test_real_malformed_and_empty_values_propagate(self):
        outputs = [{'book_id': 'bad', 'warning': 'malformed book_id'},
                   {'book_id': 'bad', 'status': 'error', 'error': 'invalid book_id'}]
        outputs.extend({'book_id': value} for value in (None, '', [], {}))
        for output in outputs:
            with self.subTest(output=output):
                result = diagnose_run(purchase_run(output, {'book_id': output['book_id']}, 'book_id is invalid'))
                self.assertEqual(result['root_cause_category'], 'cascade', result)
                self.assertEqual(result['failed_at_step'], 2)
                self.assertGreaterEqual(result['confidence'], .8)
                self.assertIn('find_book', result['fix'])
                self.assertTrue(any(e['step'] == 3 and e['field'] == 'output' for e in result['evidence']))

    def test_successful_retry_does_not_leave_a_cascade_failure(self):
        run = purchase_run({'book_id': None}, {'book_id': None}, 'book_id must not be null')
        run['status'] = 'success'
        run['spans'].extend([
            tool('purchase_book', {'book_id': None}, {'status': 'ok', 'note': 'Default book selected.'}, 'b3'),
            {'type': 'llm_call', 'response_content': 'Purchase completed.'}])
        self.assertEqual(diagnose_run(run)['root_cause_category'], 'unknown')

    def test_ambiguous_id_errors_do_not_name_a_causal_field(self):
        run = purchase_run({'book_id': 'bad', 'author_id': 'A1', 'warning': 'invalid id'},
                           {'book_id': 'bad', 'author_id': 'A1'}, 'invalid id')
        self.assertEqual(diagnose_run(run)['root_cause_category'], 'unknown')
