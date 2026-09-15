"""Server annotations must work without an incidental typing backport dependency."""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


class ServerCompatibility(unittest.TestCase):
    def test_import_schema_and_routes_without_type_backport(self):
        script = textwrap.dedent('''
            import sys
            sys.modules['eval_type_backport'] = None

            from fastapi.testclient import TestClient
            from server.app import IngestBody, app

            assert IngestBody(run_id='minimal').name is None
            assert IngestBody(run_id='nullable', name=None, status=None, started_at=None).status is None
            with TestClient(app) as client:
                schema = client.get('/openapi.json')
                assert schema.status_code == 200, schema.text
                assert '/api/runs' in schema.json()['paths']
                payload = {'run_id': 'compat', 'name': 'Compatibility', 'status': 'partial',
                           'started_at': '2026-09-14T00:00:00Z', 'spans': []}
                ingested = client.post('/ingest', json=payload)
                assert ingested.status_code == 200, ingested.text
                stored = client.get('/runs/compat')
                assert stored.status_code == 200, stored.text
                assert stored.json()['run']['name'] == 'Compatibility'
                listed = client.get('/api/runs')
                assert listed.status_code == 200, listed.text
                assert len(listed.json()['runs']) == 1
                filtered = client.get('/api/runs', params={'diagnosis_status': 'failure_detected', 'root_cause': 'loop'})
                assert filtered.status_code == 200, filtered.text
                assert filtered.json()['runs'] == []
        ''')
        with tempfile.TemporaryDirectory() as temporary:
            environment = dict(os.environ, AGENTLENS_DB=str(Path(temporary) / 'runs.db'),
                               PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-B', '-c', script],
                                    cwd=Path(__file__).resolve().parents[1], env=environment,
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
