"""Collection of real-model tests must require both opt-in controls."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('setting', ['neither', 'key_only', 'optin_only'])
def test_realmodel_requires_both_switches(setting):
    child_env = os.environ.copy()
    child_env.pop('DEEPSEEK_API_KEY', None)
    child_env.pop('CETACEA_REALMODEL', None)
    if setting == 'key_only':
        child_env['DEEPSEEK_API_KEY'] = 'fake-test-key'
    elif setting == 'optin_only':
        child_env['CETACEA_REALMODEL'] = '1'
    result = subprocess.run([sys.executable, '-m', 'pytest', 'tests/test_realmodel_optin.py', '-q', '-rs'],
                            cwd=ROOT, env=child_env, capture_output=True, text=True, timeout=60)
    # Pytest exits 5 when an entire module is skipped during collection.
    assert result.returncode in (0, 5)
    assert 'skipped' in result.stdout.lower()
