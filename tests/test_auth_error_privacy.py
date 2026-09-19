"""Synthetic error capture only: no real credentials or provider requests."""
import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import anthropic
import httpx
import openai

from agentlens_core.privacy import anonymize, redact_credentials, residual
from agentlens_engine.diagnose import diagnose_run
from agentlens_sdk import collector as c

REPO = Path(__file__).resolve().parents[1]
CASES = (
    ('full', 'Incorrect API key provided: sk-proj-SYNTHETIC_NOT_A_REAL_KEY. Check credentials.', ('sk-proj-SYNTHETIC_NOT_A_REAL_KEY',)),
    ('masked', 'Incorrect API key provided: sk-proj-FAKEHEAD****FAKETAIL. Check credentials.', ('FAKEHEAD', 'FAKETAIL')),
    ('ellipsis', 'Rejected sk-FAKEHEAD...FAKETAIL credential.', ('FAKEHEAD', 'FAKETAIL')),
    ('partial', 'API key ending in FAKE_LAST_FOUR is invalid.', ('FAKE_LAST_FOUR',)),
    ('prefix', 'Credential hint: FAKE_HINT_VALUE; authentication failed.', ('FAKE_HINT_VALUE',)),
    ('bearer', 'Request rejected: Bearer FAKE_BEARER_VALUE+tail/==', ('FAKE_BEARER_VALUE', 'tail/==')),
    ('header', 'Authorization: Basic FAKE_BASIC_VALUE\nHTTP status 401', ('FAKE_BASIC_VALUE',)),
    ('nested', 'Error code: 401 - ' + repr({'error': {'message': 'Incorrect API key provided: sk-FAKEHEAD****FAKETAIL', 'details': {'Authorization': 'Bearer FAKE_NESTED_VALUE'}, 'type': 'authentication_error'}}), ('FAKEHEAD', 'FAKETAIL', 'FAKE_NESTED_VALUE')),
    ('escaped', 'Error: ' + json.dumps({'message': 'API key suffix: FAKE_SUFFIX', 'api_key': 'FAKE_ESCAPED'}).replace('"', '\\"'), ('FAKE_SUFFIX', 'FAKE_ESCAPED')),
    ('hint_field', 'Error: ' + repr({'api_key_hint': 'FAKE_FIELD_HINT', 'token_last4': 'FAKE_LAST4'}), ('FAKE_FIELD_HINT', 'FAKE_LAST4')),
    ('split_mask', 'Incorrect API key provided: sk-FAKEHEAD **** FAKETAIL.', ('FAKEHEAD', 'FAKETAIL')),
    ('unicode_mask', 'Rejected sk-FAKEHEAD\u2026FAKETAIL credential.', ('FAKEHEAD', 'FAKETAIL')),
    ('label_verbs', 'API key prefix is FAKE_PREFIX; key ending in FAKE_LAST.', ('FAKE_PREFIX', 'FAKE_LAST')),
    ('digest', 'Authorization: Digest username="FAKE_USER", response="FAKE_RESPONSE"', ('FAKE_USER', 'FAKE_RESPONSE')),
    ('split_bearer', 'Bearer FAKEHEAD **** FAKETAIL', ('FAKEHEAD', 'FAKETAIL')),
)


class AuthenticationErrorPrivacy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = Path.cwd()
        os.chdir(self.tmp.name)
        self.token = c._current_run.set(None)
        self.names = patch('agentlens_core.privacy._name_model', return_value=None)
        self.names.start()

    def tearDown(self):
        self.names.stop()
        c._current_run.reset(self.token)
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def assert_safe(self, value, secrets):
        text = value if isinstance(value, str) else json.dumps(value)
        for secret in secrets:
            self.assertNotIn(secret, text)

    def capture(self, name, message, asynchronous=False, stream=False):
        run_id = None
        def broken():
            raise RuntimeError(message)
        def chunks():
            yield {'choices': []}
            broken()
        @c.run(name)
        def sync_work():
            nonlocal run_id
            run_id = c.current_run()['run_id']
            result = c._capture_sync(lambda: chunks() if stream else broken(),
                                     {'model': 'test', 'messages': [], 'stream': stream}, 'openai', 'chat')
            if stream:
                list(result)
        @c.run(name)
        async def async_work():
            nonlocal run_id
            run_id = c.current_run()['run_id']
            async def rejected():
                broken()
            await c._capture_async(rejected, {'model': 'test', 'messages': []}, 'openai', 'chat')
        with self.assertRaises(RuntimeError):
            asyncio.run(async_work()) if asynchronous else sync_work()
        path = Path('.agentlens/runs') / (run_id + '.json')
        return path, json.loads(path.read_text())

    def test_synthetic_credentials_absent_from_raw_saved_errors(self):
        for name, message, secrets in CASES:
            with self.subTest(name=name):
                path, data = self.capture(name, message)
                self.assert_safe(path.read_text(), secrets)
                self.assertEqual(data['status'], 'error')
                self.assertEqual(len(data['spans']), 3)
                self.assertEqual(data['spans'][0]['provider'], 'openai')
                self.assertIn('[REDACTED]', data['error'])

    def test_async_and_interrupted_stream_errors_are_safe(self):
        for kwargs in ({'asynchronous': True}, {'stream': True}):
            with self.subTest(kwargs=kwargs):
                path, _ = self.capture('async-stream', CASES[1][1], **kwargs)
                self.assert_safe(path.read_text(), CASES[1][2])

    def test_openai_authentication_exception_via_local_transport(self):
        c.init()
        body = {'error': {'message': CASES[1][1], 'type': 'invalid_request_error', 'code': 'invalid_api_key'}}
        def reject(request):
            return httpx.Response(401, json=body, headers={'x-request-id': 'req_synthetic_safe'}, request=request)
        @c.run('mock-openai-auth')
        def work():
            with openai.OpenAI(api_key='synthetic-not-used', max_retries=0,
                               http_client=httpx.Client(transport=httpx.MockTransport(reject))) as client:
                client.chat.completions.create(model='test', messages=[])
        with self.assertRaises(openai.AuthenticationError):
            work()
        data = json.loads(next(Path('.agentlens/runs').glob('*.json')).read_text())
        self.assert_safe(data, CASES[1][2])
        self.assertEqual(data['spans'][0]['status'], 'error')
        self.assertIn('401', data['error'])
        self.assertIn('invalid_api_key', data['error'])
        self.assertEqual(data['spans'][0]['status_code'], 401)
        self.assertEqual(data['spans'][0]['error_type'], 'AuthenticationError')
        self.assertEqual(data['spans'][0]['request_id'], 'req_synthetic_safe')

    def test_nested_context_and_manual_save(self):
        run_data = c.start_run('nested')
        run_data['error'] = {'message': CASES[1][1], 'headers': {'Authorization': 'Bearer FAKE_CONTEXT_VALUE'}}
        run_data['spans'] = [{'type': 'error', 'error': {'inner': [CASES[3][1]]}}]
        path = c.save_run(run=run_data)
        self.assert_safe(path.read_text(), ('FAKEHEAD', 'FAKETAIL', 'FAKE_CONTEXT_VALUE', 'FAKE_LAST_FOUR'))

    def test_opaque_hints_in_typed_auth_errors_are_omitted(self):
        for provider, code in (('openai', 401), ('openai', 403), ('anthropic', 401)):
            with self.subTest(provider=provider, code=code):
                request = httpx.Request('POST', 'https://synthetic.invalid')
                response = httpx.Response(code, request=request, headers={'x-request-id': 'req_synthetic_safe'})
                error_type = (openai.AuthenticationError if code == 401 else openai.PermissionDeniedError) if provider == 'openai' else anthropic.AuthenticationError
                error = error_type('Unrecognized opaque hint FAKE_OPAQUE_MATERIAL', response=response,
                                   body={'error': {'message': 'FAKE_OPAQUE_MATERIAL', 'type': 'authentication_error'}})
                @c.run('opaque')
                def work():
                    def fail():
                        raise error
                    c._capture_sync(fail, {'model': 'test', 'messages': []}, provider, 'chat')
                with self.assertRaises(error_type) as caught:
                    work()
                self.assertIs(caught.exception, error)  # Do not change what the application catches.
                for saved in Path('.agentlens/runs').glob('*.json'):
                    self.assert_safe(saved.read_text(), ('FAKE_OPAQUE_MATERIAL',))

    def test_capture_redaction_preserves_non_sensitive_json_and_metrics(self):
        value = {'error': 'HTTP 429: retry later', 'content': '{"result":1}',
                 'input_tokens': 23, 'output_tokens': 17, 'email': 'synthetic@example.test'}
        self.assertEqual(redact_credentials(value), value)
        self.assertEqual(redact_credentials(redact_credentials(value)), value)

    def test_error_context_is_safe_before_save(self):
        c.capture_error(CASES[1][1], {'inner': {'api_key_hint': 'FAKE_CONTEXT_HINT',
                                              'headers': {'Authorization': 'Bearer FAKE_CONTEXT_HEADER'}}})
        self.assert_safe(c.current_run(), ('FAKEHEAD', 'FAKETAIL', 'FAKE_CONTEXT_HINT', 'FAKE_CONTEXT_HEADER'))
        self.assert_safe(c.save_run().read_text(), ('FAKEHEAD', 'FAKETAIL', 'FAKE_CONTEXT_HINT', 'FAKE_CONTEXT_HEADER'))

    def test_normal_error_and_debugging_metadata_survive(self):
        message = 'HTTP 429: rate limit exceeded; request_id=req_synthetic_safe. Retry later.'
        path, data = self.capture('ordinary', message)
        self.assertEqual(data['error'], message)
        self.assertIn(message, path.read_text())
        self.assertEqual(data['spans'][0]['model'], 'test')
        self.assertIsInstance(data['spans'][0]['latency_ms'], (int, float))

    def test_anonymizer_and_residual_share_masked_hint_policy(self):
        for name, message, secrets in CASES:
            with self.subTest(name=name):
                self.assertTrue(residual(message))
                cleaned = anonymize({'error': message, 'input_tokens': 11, 'output_tokens': 5})
                self.assert_safe(cleaned, secrets)
                self.assertEqual(cleaned['input_tokens'], 11)
                self.assertEqual(cleaned['output_tokens'], 5)
                self.assertEqual(residual(cleaned), [])
                self.assertEqual(anonymize(cleaned), cleaned)

    def test_cli_exports_and_diagnosis_input(self):
        path, data = self.capture('boundaries', CASES[1][1])
        secrets = CASES[1][2]
        run_id = data['run_id']
        for command in (['runs', 'show', run_id], ['anonymize', run_id], ['upload', 'prepare', run_id], ['diagnose', run_id]):
            proc = subprocess.run([sys.executable, '-B', str(REPO/'agentlens.py'), *command],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assert_safe(proc.stdout + proc.stderr, secrets)
        for saved in Path('.').rglob('*.json'):
            self.assert_safe(saved.read_text(), secrets)
        self.assertTrue(Path(run_id + '.anonymized.json').exists())
        self.assertTrue((Path('.agentlens/upload') / (run_id + '.anonymized.json')).exists())
        from agentlens_engine.preprocess import preprocess_run
        with patch('agentlens_engine.diagnose.preprocess_run', wraps=preprocess_run) as preprocess:
            diagnosis = diagnose_run(data)
        self.assert_safe(preprocess.call_args.args, secrets)
        self.assert_safe(diagnosis, secrets)
        self.assertEqual(diagnosis['root_cause_category'], 'unknown')
        with patch('agentlens_engine.diagnose._diagnose_with_llm', return_value=None) as remote:
            diagnose_run(data, provider='openai')
        self.assert_safe(remote.call_args.args, secrets)

    def test_legacy_trace_is_safe_on_read_and_diagnosis(self):
        from agentlens_core.trace import read_run
        legacy = {'run_id': 'legacy', 'spans': [{'type': 'error', 'error': CASES[1][1]}]}
        Path('legacy.json').write_text(json.dumps(legacy))
        self.assert_safe(read_run(Path('legacy.json')), CASES[1][2])
        from agentlens_engine.preprocess import preprocess_run
        with patch('agentlens_engine.diagnose.preprocess_run', wraps=preprocess_run) as preprocess:
            diagnose_run(legacy)
        self.assert_safe(preprocess.call_args.args, CASES[1][2])

    def test_agentlens_warning_does_not_echo_persistence_exception(self):
        output = io.StringIO()
        with patch.object(c, 'save_run', side_effect=OSError(CASES[1][1])), contextlib.redirect_stderr(output), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            data = c.start_run('save-failure')
            data['status'] = 'success'
            c._finalize_run(data)
        self.assertEqual(len(caught), 1)
        self.assert_safe(str(caught[0].message), CASES[1][2])
        self.assert_safe(output.getvalue(), CASES[1][2])


if __name__ == '__main__':
    unittest.main()
