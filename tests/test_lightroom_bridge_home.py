"""Harness-isolated HOME must not hide the operator's Lightroom bridge token.

The token file is created only as a non-empty placeholder. Tests never read it.
"""
import sys
from pathlib import Path

import pytest

from cetacea.lightroom.real_mcp import RealLightroomMcpAdapter, bridge_env
from mcp.client.stdio import get_default_environment


def test_session_runner_keeps_operator_home_for_the_bridge():
    text = Path('harness/run_session.sh').read_text()
    assert text.index('CETACEA_BRIDGE_HOME="$HOME"') < text.index('HOME=$WORK')
    assert 'CETACEA_BRIDGE_HOME=$CETACEA_BRIDGE_HOME' in text


def test_prompt_treats_waiting_approval_after_approve_as_ready_to_execute():
    text = Path('harness/overlay/cetacea-deepseek.patch.yml').read_text()
    assert 'leaves the state at WAITING_APPROVAL and run_count at 0' in text
    assert 'photo_execute_import' in text


def test_unset_bridge_home_does_not_override_home(monkeypatch):
    monkeypatch.delenv('CETACEA_BRIDGE_HOME', raising=False)
    assert bridge_env() == {'LIGHTROOM_MCP_TOOLSETS': 'develop'}


def test_bridge_home_overrides_isolated_home_without_copying_token(tmp_path, monkeypatch):
    bridge = tmp_path / 'operator-home'
    token = bridge / '.config' / 'lightroom-mcp' / 'token'
    token.parent.mkdir(parents=True)
    token.write_bytes(b'placeholder-token-not-read\n')
    isolated = tmp_path / 'harness-workspace'
    isolated.mkdir()
    monkeypatch.setenv('HOME', str(isolated))
    monkeypatch.setenv('CETACEA_BRIDGE_HOME', str(bridge))
    explicit = bridge_env(testing=False)
    assert explicit['HOME'] == str(bridge)
    assert 'placeholder-token-not-read' not in explicit.values()
    merged = get_default_environment() | explicit
    assert merged['HOME'] == str(bridge)
    assert merged['LIGHTROOM_MCP_TOOLSETS'] == 'develop'
    assert set(explicit) == {'HOME', 'LIGHTROOM_MCP_TOOLSETS'}


def test_missing_token_is_not_described_as_a_port_conflict(tmp_path):
    with pytest.raises(RuntimeError, match='CETACEA_BRIDGE_HOME') as caught:
        bridge_env({'CETACEA_BRIDGE_HOME': str(tmp_path)}, testing=False)
    message = str(caught.value)
    assert 'MIDI2LR' not in message
    assert 'token value was not read' in message
    assert 'Restarting Lightroom does not fix this' in message


@pytest.mark.parametrize('value', ['relative-home', ''])
def test_relative_bridge_home_is_rejected(tmp_path, value):
    if value == '':
        target = tmp_path / 'link'
        target.symlink_to(tmp_path)
        value = str(target)
    with pytest.raises(ValueError, match='absolute directory'):
        bridge_env({'CETACEA_BRIDGE_HOME': value})


def test_call_tool_uses_bridge_home(tmp_path, monkeypatch):
    bridge = tmp_path / 'operator-home'
    bridge.mkdir()
    monkeypatch.setenv('CETACEA_BRIDGE_HOME', str(bridge))
    captured = {}

    class Stop:
        def __init__(self, params):
            captured['env'] = dict(params.env)
        async def __aenter__(self):
            raise RuntimeError('stop before launch')
        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr('cetacea.lightroom.real_mcp.stdio_client', Stop)
    adapter = RealLightroomMcpAdapter(test_command=[sys.executable, 'fake'])
    with pytest.raises(RuntimeError, match='stop before launch'):
        adapter.call_tool('list_develop_presets', {'limit': 0})
    assert captured['env']['HOME'] == str(bridge)
    assert captured['env']['LIGHTROOM_MCP_TOOLSETS'] == 'develop'
