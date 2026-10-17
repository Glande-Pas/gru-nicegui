import plistlib

import pytest

from gru_ui import autostart


@pytest.mark.parametrize('argument, expected', [
    ('/usr/bin/python3', '/usr/bin/python3'),
    ('/home/a b/gru', '"/home/a b/gru"'),
    ('say "hi"', '"say \\"hi\\""'),
    ('$HOME', '"\\$HOME"'),
    ('100%', '100%'),
    ('a b%', '"a b%%"'),
])
def test_desktop_quote(argument, expected):
    assert autostart.desktop_quote(argument) == expected


def test_desktop_entry():
    entry = autostart.desktop_entry(['/opt/my app/gru', '--tray'])
    assert 'Exec="/opt/my app/gru" --tray\n' in entry
    assert entry.startswith('[Desktop Entry]\nType=Application\n')


def test_desktop_file_toggle(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, '_autostart_file', lambda: tmp_path / 'autostart' / 'gru-tray.desktop')
    autostart._set_desktop_file(True)
    assert (tmp_path / 'autostart' / 'gru-tray.desktop').read_text().endswith('--tray\nTerminal=false\n'
                                                                              'X-GNOME-Autostart-enabled=true\n')
    autostart._set_desktop_file(False)
    autostart._set_desktop_file(False)  # already gone
    assert not (tmp_path / 'autostart' / 'gru-tray.desktop').exists()


def test_launch_agent(tmp_path, monkeypatch):
    path = tmp_path / 'agent.plist'
    monkeypatch.setattr(autostart, '_launch_agent_file', lambda: path)
    monkeypatch.setattr(autostart.os, 'getuid', lambda: 501, raising=False)
    monkeypatch.setattr(autostart.subprocess, 'run', lambda *a, **k: None)
    autostart._set_launch_agent(True)
    data = plistlib.loads(path.read_bytes())
    assert data['RunAtLoad'] and data['ProgramArguments'][-1] == '--tray'
    autostart._set_launch_agent(False)
    assert not path.exists()
