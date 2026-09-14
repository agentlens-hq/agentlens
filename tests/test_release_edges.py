import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import agentlens
from agentlens_core.storage import atomic_write, safe_path
from agentlens_core.trace import normalize_run
from agentlens_engine.diagnose import diagnose_run
from agentlens_engine.impact import compute_impact
from agentlens_engine.preprocess import preprocess_run
from agentlens_engine.timeline import generate_html
from agentlens_sdk import collector as c


class ReleaseEdges(unittest.TestCase):
    def test_import_without_engine_or_providers(self):
        code = '''import sys
class Block:
 def find_spec(self, fullname, *args):
  if fullname.startswith(('agentlens_engine', 'openai', 'anthropic', 'spacy')): raise ImportError('blocked')
sys.meta_path.insert(0, Block())
import agentlens
agentlens.init()
assert callable(agentlens.run)
assert not any(n.startswith('agentlens_engine') for n in sys.modules)
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_demo_offline_with_keys(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(c, 'RUNS_DIR', Path(directory)), patch.object(agentlens, 'RUNS_DIR', Path(directory)), patch.dict(os.environ, {'OPENAI_API_KEY': 'test', 'ANTHROPIC_API_KEY': 'test'}), patch('agentlens_engine.diagnose._diagnose_with_llm', side_effect=AssertionError('remote called')), contextlib.redirect_stdout(io.StringIO()) as output:
            agentlens._run_demo(open_browser=False)
            self.assertEqual(len(list(Path(directory).glob('*.json'))), 1)
            self.assertIn('tool_selection', output.getvalue())

    def test_concurrent_writes_and_symlink_containment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'shared.json'
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda n: atomic_write(path, {'n': n, 'data': str(n) * 10000}), range(30)))
            value = json.loads(path.read_text())
            self.assertEqual(value['data'], str(value['n']) * 10000)
            (root / 'escape.json').symlink_to(root.parent / 'outside.json')
            with self.assertRaises(ValueError):
                safe_path(root, 'escape')

    def test_canonical_prompt_timeline_and_impact(self):
        item = normalize_run({'run_id': 'identity', 'spans': [None, {'type': 'tool_call'}, {'type': 'llm_call', 'response_content': '__TITLE__ /*__DIAG__*/null', 'usage': {'input_tokens': 10}, 'cost_usd': .1}]})
        self.assertEqual(preprocess_run(item['spans'])['diagnostic_steps'][-1]['step'], 3)
        with patch.object(agentlens, '_load_run_or_report', return_value=item), contextlib.redirect_stdout(io.StringIO()) as output:
            agentlens._print_prompt_viewer('identity', step=3)
        self.assertIn('Step 3', output.getvalue())
        html = generate_html(item)
        self.assertIn('__TITLE__ /*__DIAG__*/null', html)
        self.assertEqual(compute_impact(item['spans'], {'failed_at_step': 3})['wasted_tokens'], 10)

    def test_bad_remote_falls_back_and_is_labeled(self):
        invalid = {'root_cause_category': 'loop', 'failed_at_step': 999, 'confidence': .99, 'fix': 'invented', 'explanation': 'invented', 'failed_at_tool': 'invented', 'secondary_issues': [], 'evidence': []}
        with patch('agentlens_engine.diagnose._diagnose_with_llm', return_value=invalid):
            diagnosis = diagnose_run({'spans': []}, provider='openai')
        self.assertEqual(diagnosis['root_cause_category'], 'unknown')
        self.assertEqual(diagnosis['diagnosis_source'], 'heuristic')
        self.assertIn('remote_warning', diagnosis)
