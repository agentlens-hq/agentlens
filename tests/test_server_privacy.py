import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from agentlens_core.privacy import anonymize


class ServerPrivacy(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {'AGENTLENS_DB': str(Path(self.directory.name) / 'runs.db')}):
            self.server = importlib.import_module('server.app')
        self.db = patch.object(self.server, 'DB_PATH', Path(self.directory.name) / 'runs.db')
        self.db.start()
        self.server.init_db()

    def tearDown(self):
        self.db.stop()
        self.directory.cleanup()

    def test_rejects_same_adversarial_secrets_as_export(self):
        for value in [{'accessToken': 'private'}, '{"apiKey":"private"}', 'Bearer abc+def/ghi==', 'token=private', r'request failed: {\"accessToken\":\"private\"}']:
            with self.subTest(value=value):
                body = self.server.IngestBody(run_id='test', spans=[{'type': 'tool_call', 'output': value}])
                with self.assertRaises(HTTPException) as error:
                    self.server.ingest(body)
                self.assertEqual(error.exception.status_code, 422)
                clean = self.server.IngestBody(**anonymize(body.model_dump()))
                self.server.ingest(clean)

    def test_metadata_round_trip_and_partial_state(self):
        payload = {'run_id': 'round_trip', 'status': 'partial', 'parent_run_id': 'parent', 'ended_at': '2026-09-12T00:00:00Z', 'metadata': {'environment': 'local'}, 'spans': []}
        self.server.ingest(self.server.IngestBody(**payload))
        stored = self.server.get_run('round_trip')
        for field, value in payload.items():
            self.assertEqual(stored['run'][field], value)
        self.assertEqual(stored['execution_status'], 'partial')

    def test_malformed_schema_is_422(self):
        body = self.server.IngestBody(run_id='invalid', spans=[{'input_messages': 42}])
        with self.assertRaises(HTTPException) as error:
            self.server.ingest(body)
        self.assertEqual(error.exception.status_code, 422)
