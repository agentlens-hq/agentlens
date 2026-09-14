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
from agentlens_core.storage import atomic_write
from agentlens_engine.status import run_status


class CliBoundaries(unittest.TestCase):
    def test_bad_files_and_missing_run_exit(self):
        for value in ['{', '[]', '{"spans":[3]}', '{"spans":[{"input_messages":42}]}']:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / '.agentlens/runs'
                target.mkdir(parents=True)
                (target / 'broken.json').write_text(value)
                env = dict(os.environ, PYTHONPATH=str(Path(agentlens.__file__).parent))
                for command in [['runs', 'show', 'broken'], ['runs', 'show', 'missing']]:
                    bootstrap = f'import sys; sys.path.insert(0, {str(Path(agentlens.__file__).parent)!r}); import agentlens; agentlens.main()'
                    result = subprocess.run([sys.executable, '-B', '-c', bootstrap, *command], cwd=directory, env=env, text=True, capture_output=True)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertNotIn('Traceback', result.stderr)

    def test_partial_status_is_not_completed_or_healthy(self):
        for status in ['running', 'partial', 'cancelled', 'unknown']:
            result = run_status({'status': status, 'spans': [{'type': 'llm_call', 'response_content': 'hello'}]})
            self.assertEqual(result['execution_status'], status)
            self.assertNotEqual(result['diagnosis_status'], 'healthy')

    def test_failed_health_commands_exit_nonzero(self):
        for args, target, value in [
            (['agentlens', 'doctor'], '_doctor_evaluation', ('FAIL', 'bad fixture')),
            (['agentlens', 'evaluate'], 'evaluate_cases', {'fixture_cases': 0, 'fixture_accuracy': 0, 'scored_cases': 0, 'overall_accuracy': 0}),
        ]:
            with patch.object(sys, 'argv', args), patch.object(agentlens, target, return_value=value), patch.object(agentlens, 'print_evaluation'), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    agentlens.main()
                self.assertNotEqual(caught.exception.code, 0)

    def test_headless_view_is_honest(self):
        with patch.object(agentlens, '_load_run_or_report', return_value={'run_id': 'x', 'spans': []}), patch('webbrowser.open', return_value=False), contextlib.redirect_stdout(io.StringIO()) as output:
            agentlens._open_timeline('x')
        self.assertIn('could not open', output.getvalue())

    def test_stitch_cycle(self):
        item = {'run_id': 'x', 'parent_run_id': 'x', 'spans': []}
        with patch.object(agentlens, '_load_run_or_report', return_value=item), patch.object(agentlens, 'load_runs', return_value=[item]), contextlib.redirect_stdout(io.StringIO()) as output:
            agentlens._print_stitch('x')
        self.assertIn('Cycle', output.getvalue())

    def test_atomic_failure_keeps_old_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.json'
            atomic_write(path, {'old': True})
            with patch('os.replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    atomic_write(path, {'new': True})
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertEqual(list(Path(directory).iterdir()), [path])
