import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agentlens
from agentlens_core.privacy import _name_model
from agentlens_engine.timeline import _embed


class SecurityRegressions(unittest.TestCase):
    def test_script_boundaries(self):
        for text in ('</script>', '</SCRIPT>', '</ScRiPt><script>x</script>', '<tag>', '&>\u2028\u2029'):
            with self.subTest(text=text):
                value = {'spans': [{'output': [text], 'error': text}]}
                embedded = _embed(value)
                self.assertNotIn('<', embedded)
                self.assertEqual(json.loads(embedded), value)

    def test_redaction_roundtrip(self):
        for key in ('api_key', 'apiKey', 'API_KEY', 'accessToken', 'access_token', 'bearer', 'authorization', 'password', 'passwd', 'client_secret', 'refreshToken', 'token'):
            with self.subTest(key=key):
                value = {'output': json.dumps({key: 'credential+suffix/=='}), key: 'credential+suffix/==', 'input_tokens': 23, 'output_tokens': 17}
                cleaned = agentlens._anonymize_value(value)
                self.assertNotIn('credential', json.dumps(cleaned))
                self.assertEqual(cleaned['input_tokens'], 23)
                self.assertEqual(cleaned['output_tokens'], 17)
                self.assertEqual(agentlens._residual_pii(cleaned), [])

    def test_bearer_and_url(self):
        for value in ('Bearer abcdefghijkl+SUFFIX/==', 'https://alice:credential@example.test/path', 'password="credential"', '{"nested":"{\\"accessToken\\":\\"credential\\"}"}'):
            with self.subTest(value=value):
                cleaned = agentlens._anonymize_value(value)
                self.assertNotIn('SUFFIX', cleaned)
                self.assertNotIn('credential', cleaned)

    def test_residual_credentials(self):
        for value in ({'accessToken': 'credential'}, {'output': '{"password":"credential"}'}, {'text': 'Bearer abcdefghijkl+suffix/=='}, {'token': 'short'}):
            self.assertTrue(agentlens._residual_pii(value))

    def test_escaped_credentials_inside_error_fragments(self):
        for key in ('accessToken', 'secretAccessKey', 'sessionToken', 'proxyAuthorization', 'cookie'):
            for escapes in (1, 2):
                fragment = json.dumps({key: 'private-example+tail/==', 'input_tokens': 23})
                fragment = fragment.replace('"', '\\' * escapes + '"')
                value = 'request failed: ' + fragment + ' (provider response)'
                with self.subTest(key=key, escapes=escapes):
                    self.assertTrue(agentlens._residual_pii(value))
                    cleaned = agentlens._anonymize_value(value)
                    self.assertNotIn('private-example', cleaned)
                    self.assertNotIn('tail', cleaned)
                    self.assertIn('input_tokens', cleaned)
                    self.assertIn('23', cleaned)
                    self.assertEqual(agentlens._residual_pii(cleaned), [])

    def test_reject_export_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            for run_id in ('../../foo', '/tmp/foo', '..\\foo', 'x/../../foo', '%2e%2e%2ffoo', ''):
                with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                    agentlens._write_anonymized_run({'run_id': run_id, 'spans': []}, Path(tmp))

    def test_optional_name_model_setup_hint(self):
        _name_model.cache_clear()
        try:
            with patch.dict('sys.modules', {'spacy': SimpleNamespace(load=Mock(side_effect=OSError('model missing')))}):
                with self.assertWarnsRegex(RuntimeWarning, r'runlens\[pii\].*python -m spacy download en_core_web_sm'):
                    self.assertIsNone(_name_model())
        finally:
            _name_model.cache_clear()
