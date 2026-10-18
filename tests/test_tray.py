import json

import pytest

from gru_ui import tray


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tray, 'user_cache', lambda *a: tmp_path.joinpath(*a))
    return tmp_path


def test_count_roundtrip(cache):
    tray.publish_count(3)
    assert tray.read_count(0) == 3
    assert tray.read_count(9e12) is None


def test_count_unreadable(cache):
    assert tray.read_count(0) is None
    (cache / 'tray-updates.json').write_text('{')
    assert tray.read_count(0) is None
    (cache / 'tray-updates.json').write_text(json.dumps({'count': 'x', 'time': 1}))
    assert tray.read_count(0) is None


def test_single_helper(cache):
    first = tray._acquire_lock()
    assert first is not None
    assert tray.is_running()
    first.close()
    assert not tray.is_running()


@pytest.mark.parametrize('count', [0, 5, 42, 100])
def test_badge_icon(count):
    pytest.importorskip('PIL')
    assert tray.badge_icon(count).size == (64, 64)


def test_run_does_nothing_when_disabled(cache, monkeypatch):
    monkeypatch.setattr(tray, 'enabled', lambda config=None: False)
    tray.run()
    assert not (cache / 'tray.lock').exists()
