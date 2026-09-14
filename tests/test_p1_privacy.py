import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agentlens
from agentlens_core.privacy import anonymize, key_kind, residual

REPO = Path(__file__).resolve().parents[1]
SECRET = 'synthetic-credential-value-not-for-authentication'
KEYS = (
    'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
    'aws_access_key_id', 'aws_secret_access_key', 'aws_session_token',
    'awsAccessKeyId', 'awsSecretAccessKey', 'awsSessionToken',
    'aws.access.key.id', 'aws-secret-access-key', 'aws.session.token',
    'service_client_secret', 'service_private_key', 'service_refresh_token',
)


class P1Privacy(unittest.TestCase):
    def test_provider_prefixed_keys_nested_and_serialized(self):
        metrics = {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30,
                   'cached_tokens': 5, 'token_count': 30, 'token_limit': 100,
                   'tokens_per_second': 4, 'session_token_count': 2}
        for key in KEYS:
            with self.subTest(key=key):
                self.assertEqual(key_kind(key), 'credential')
                payload = {'config': [{key: SECRET}], 'metrics': metrics}
                for value in (payload, json.dumps(payload), f'request failed: {key}="{SECRET}"'):
                    self.assertTrue(residual(value))
                    cleaned = anonymize(value)
                    self.assertNotIn(SECRET, json.dumps(cleaned))
                    self.assertEqual(residual(cleaned), [])
                self.assertEqual(anonymize(payload)['metrics'], metrics)
        self.assertEqual(residual(metrics), [])

    def test_export_gate_rejects_unsanitized_and_accepts_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key in KEYS:
                run = {'run_id': 'privacy', 'spans': [], 'metadata': {key: SECRET}}
                with self.subTest(key=key), patch.object(agentlens, '_anonymize_value', side_effect=lambda value: value), contextlib.redirect_stdout(io.StringIO()):
                    self.assertIsNone(agentlens._write_anonymized_run(run, root))
            self.assertEqual(list(root.iterdir()), [])
            run = {'run_id': 'privacy', 'spans': [], 'metadata': {key: SECRET for key in KEYS}}
            path = agentlens._write_anonymized_run(run, root)
            self.assertIsNotNone(path)
            self.assertNotIn(SECRET, path.read_text())

    def test_actual_upload_preparation_writes_only_redacted_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = root / '.agentlens/runs'
            runs.mkdir(parents=True)
            (runs / 'privacy.json').write_text(json.dumps({
                'run_id': 'privacy', 'spans': [], 'metadata': {key: SECRET for key in KEYS}}))
            result = subprocess.run(
                [sys.executable, '-B', str(REPO / 'agentlens.py'), 'upload', 'prepare', 'privacy'],
                cwd=root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            exported = (root / '.agentlens/upload/privacy.anonymized.json').read_text()
            self.assertNotIn(SECRET, exported)
            self.assertEqual(residual(json.loads(exported)), [])
