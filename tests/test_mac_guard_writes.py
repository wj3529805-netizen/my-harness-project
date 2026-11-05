"""Device-boundary regressions for the read-only Mac validation write guard."""
import errno
import importlib.util
import os
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'guard_common', Path(__file__).resolve().parents[1] / 'scripts/mac/r_common.py')
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


@pytest.fixture
def devices(tmp_path, monkeypatch):
    """Give an ordinary directory its own device without mounting any disk."""
    volume = tmp_path / 'destination-volume'; volume.mkdir()
    target = volume / 'run'; target.mkdir()
    home = tmp_path / 'home'; home.mkdir()
    card = tmp_path / 'card'; card.mkdir()
    (card / 'source.NEF').write_bytes(b'original')
    original_stat = Path.stat
    target_device = original_stat(volume).st_dev + 1
    mounted = [True]

    def stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if mounted[0] and path.absolute().is_relative_to(volume):
            fields = list(result); fields[2] = target_device
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, 'stat', stat)
    return volume, target, home, card, mounted


def test_home_device_does_not_guard_entire_boot_disk(devices, tmp_path):
    volume, target, home, card, mounted = devices
    outside_home = tmp_path / 'boot-work'
    with common.guard_writes([target, home], [card]):
        os.mkdir(outside_home)
        fd = os.open(outside_home / 'file', os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        os.mkdir(home / 'logs')
        os.mkdir(target / 'library')
    assert outside_home.is_dir() and (home / 'logs').is_dir()


@pytest.mark.parametrize('operation', ['mkdir', 'open', 'rename'])
def test_destination_device_outside_run_still_rejected(devices, operation):
    volume, target, home, card, mounted = devices
    inside = target / 'inside'; inside.write_bytes(b'safe')
    outside = volume / 'outside'
    with common.guard_writes([target, home], [card]):
        with pytest.raises(PermissionError, match='Write outside allowed test roots'):
            if operation == 'mkdir': os.mkdir(outside)
            elif operation == 'open': os.open(outside, os.O_CREAT | os.O_WRONLY, 0o600)
            else: os.rename(inside, outside)
    assert inside.read_bytes() == b'safe' and not outside.exists()


@pytest.mark.parametrize('operation', ['open', 'unlink', 'chmod', 'rename'])
def test_card_remains_protected_on_boot_device(devices, operation):
    volume, target, home, card, mounted = devices
    source = card / 'source.NEF'
    with common.guard_writes([target, home], [card]):
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW); os.close(fd)
        with pytest.raises(PermissionError, match='Protected source'):
            if operation == 'open': os.open(source, os.O_WRONLY)
            elif operation == 'unlink': os.unlink(source)
            elif operation == 'chmod': os.chmod(source, 0o600)
            else: os.rename(source, target / 'stolen')
    assert source.read_bytes() == b'original'


def test_missing_target_does_not_create_fallback_on_boot(devices):
    volume, target, home, card, mounted = devices
    with common.guard_writes([target, home], [card]):
        mounted[0] = False
        with pytest.raises(OSError) as failure:
            os.mkdir(target / 'library')
        assert failure.value.errno == errno.ENODEV
        assert 'Destination device changed or disappeared' in str(failure.value)
        # Recursive mkdir must not create the volume's ancestor outside the run.
        with pytest.raises(PermissionError, match='Write outside allowed test roots'):
            os.mkdir(volume / 'outside')
        os.mkdir(home / 'logs')
    assert not (target / 'library').exists()


def test_target_walkup_to_boot_ancestor_keeps_real_device_error(devices):
    volume, target, home, card, mounted = devices
    with common.guard_writes([target, home], [card]):
        mounted[0] = False
        # Simulate a vanished run directory: path lookup walks up to the boot
        # device, while the saved destination boundary remains authoritative.
        original_exists = Path.exists
        def exists(path):
            if path == target or path.is_relative_to(target): return False
            return original_exists(path)
        from unittest.mock import patch
        with patch.object(Path, 'exists', exists):
            with pytest.raises(OSError) as failure:
                os.mkdir(target / 'library' / 'temp')
        assert failure.value.errno == errno.ENODEV
