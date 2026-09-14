"""Install a wheel without optional dependencies and exercise it outside the checkout."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path


def main() -> None:
    wheel = Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(wheel) as archive:
        fixtures = [name for name in archive.namelist() if '/corpus/' in name and name.endswith('.json')]
        assert len(fixtures) == 14, fixtures
        assert not any(name.startswith(('tests/', 'server/', '.agentlens/')) or name.endswith('codex.md') for name in archive.namelist())
    with tempfile.TemporaryDirectory(prefix='agentlens-wheel-') as temporary:
        root = Path(temporary)
        environment = root / 'venv'
        venv.EnvBuilder(with_pip=True).create(environment)
        binaries = environment / ('Scripts' if os.name == 'nt' else 'bin')
        python = binaries / 'python'
        cli = binaries / 'agentlens'
        env = {key: value for key, value in os.environ.items() if key not in ('PYTHONPATH', 'PYTHONHOME', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY')}
        def command(args):
            result = subprocess.run([str(a) for a in args], cwd=root, env=env, text=True, capture_output=True, check=True, timeout=90)
            print(result.stdout, end='')
            return result.stdout
        command([python, '-m', 'pip', 'install', '--no-deps', wheel])
        command([python, '-c', 'import agentlens, importlib.metadata; print(agentlens.__file__); assert importlib.metadata.version("runlens") == "0.1.3"; assert "site-packages" in agentlens.__file__'])
        command([cli, '--help'])
        assert 'Result: healthy' in command([cli, 'doctor'])
        env['OPENAI_API_KEY'] = env['ANTHROPIC_API_KEY'] = 'offline-test-no-network'
        assert 'tool_selection' in command([cli, 'demo', '--no-browser'])
        evaluation = command([cli, 'evaluate'])
        assert 'Fixture accuracy: 100%' in evaluation
        assert 'False positives / false negatives: 0 / 0' in evaluation
        command([cli, 'runs', 'list'])
        run_id = next((root / '.agentlens/runs').glob('*.json')).stem
        for args in [['runs', 'show', run_id], ['diagnose', run_id], ['anonymize', run_id], ['feedback-template', run_id]]:
            command([cli, *args])
        print(f'ARTIFACT PASS: Python {sys.version.split()[0]}, {wheel.name}, {len(fixtures)} packaged cases')


if __name__ == '__main__':
    main()
