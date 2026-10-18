# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Start the tray helper (`gru-app --tray`) at login, the native way for each platform:
an XDG autostart entry on Linux, the Background portal in a Flatpak, the Run registry key on Windows
and a LaunchAgent on macOS. The Microsoft Store build declares a startup task in its manifest instead; the user turns it on in Windows Settings."""

import os
import pathlib
import plistlib
import re
import subprocess
import sys

from gru.channel import Channel, detect as detect_channel

from . import tray

NAME = 'Gru'
APP_ID = 'io.github.Glande_Pas.Gru'
ARGS = ['--tray']
_LAUNCH_AGENT = APP_ID + '.tray'


class AutostartError(Exception):
    pass


def supported() -> bool:
    return detect_channel() != Channel.MSSTORE and (os.name == 'nt' or sys.platform in ('darwin', 'linux'))


def managed_by_system() -> bool:
    """Whether starting at login is only switched in the system's settings (the Microsoft Store build)."""
    return os.name == 'nt' and detect_channel() == Channel.MSSTORE


def open_system_settings() -> None:
    os.startfile('ms-settings:startupapps')  # type: ignore[attr-defined]


def _command() -> list[str]:
    command = tray.launch_command()
    if os.name == 'nt' and not getattr(sys, 'frozen', False):
        windowless = pathlib.Path(sys.executable).with_name('pythonw.exe')
        if windowless.exists():
            command[0] = str(windowless)
    return command + ARGS


def _autostart_file() -> pathlib.Path:
    if detect_channel() == Channel.FLATPAK:  # written by the portal in the host's config dir, visible via --filesystem=home
        return pathlib.Path.home() / '.config' / 'autostart' / (APP_ID + '.desktop')
    base = os.environ.get('XDG_CONFIG_HOME') or str(pathlib.Path.home() / '.config')
    return pathlib.Path(base) / 'autostart' / 'gru-tray.desktop'


def _launch_agent_file() -> pathlib.Path:
    return pathlib.Path.home() / 'Library' / 'LaunchAgents' / (_LAUNCH_AGENT + '.plist')


def desktop_quote(argument: str) -> str:
    """`argument` as one argument of a .desktop Exec line."""
    if not re.search(r'[\s"\'\\><~|&;$*?#()`]', argument):
        return argument
    return '"' + re.sub(r'(["`$\\])', r'\\\1', argument).replace('%', '%%') + '"'


def desktop_entry(command: list[str]) -> str:
    return '\n'.join([
        '[Desktop Entry]',
        'Type=Application',
        'Name=' + NAME,
        'Comment=Tray icon showing pending add-on updates',
        'Exec=' + ' '.join(desktop_quote(a) for a in command),
        'Terminal=false',
        'X-GNOME-Autostart-enabled=true',
        '',
    ])


_RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def _windows_value() -> str:
    return subprocess.list2cmdline(_command())


def is_enabled() -> bool:
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.QueryValueEx(key, NAME)
            return True
        except OSError:
            return False
    return (_launch_agent_file() if sys.platform == 'darwin' else _autostart_file()).exists()


def set_enabled(enabled: bool) -> None:
    """Turn starting at login on or off; raises AutostartError. Blocking (the portal may ask the user)."""
    try:
        if detect_channel() == Channel.FLATPAK:
            _request_background(enabled)
        elif os.name == 'nt':
            _set_run_key(enabled)
        elif sys.platform == 'darwin':
            _set_launch_agent(enabled)
        else:
            _set_desktop_file(enabled)
    except OSError as error:
        raise AutostartError(str(error)) from error


def _set_desktop_file(enabled: bool) -> None:
    path = _autostart_file()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry(_command()))
    else:
        path.unlink(missing_ok=True)


def _set_run_key(enabled: bool) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, _windows_value())
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass


def _set_launch_agent(enabled: bool) -> None:
    path = _launch_agent_file()
    domain = 'gui/{uid}'.format(uid=os.getuid())
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as f:
            plistlib.dump({'Label': _LAUNCH_AGENT, 'ProgramArguments': _command(), 'RunAtLoad': True,
                           'LimitLoadToSessionType': 'Aqua'}, f)
    else:
        subprocess.run(['launchctl', 'bootout', domain, str(path)], capture_output=True)  # best effort: not loaded
        path.unlink(missing_ok=True)


def _request_background(enabled: bool) -> None:
    """Ask the Background portal to (not) autostart this Flatpak, and wait for its answer."""
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    token = 'gru' + os.urandom(4).hex()
    sender = bus.get_unique_name().lstrip(':').replace('.', '_')
    result = {}
    loop = GLib.MainLoop()

    def on_response(_bus, _sender, _path, _iface, _signal, params):
        result['code'], result['results'] = params.unpack()
        loop.quit()

    subscription = bus.signal_subscribe(
        'org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request', 'Response',
        '/org/freedesktop/portal/desktop/request/{sender}/{token}'.format(sender=sender, token=token), None,
        Gio.DBusSignalFlags.NONE, on_response)
    try:
        options = {
            'handle_token': GLib.Variant('s', token),
            'reason': GLib.Variant('s', 'Show the number of add-on updates in the tray'),
            'autostart': GLib.Variant('b', enabled),
            'commandline': GLib.Variant('as', ['gru-app'] + ARGS),
            'dbus-activatable': GLib.Variant('b', False),
        }
        try:
            bus.call_sync('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
                          'org.freedesktop.portal.Background', 'RequestBackground',
                          GLib.Variant('(sa{sv})', ('', options)), None, Gio.DBusCallFlags.NONE, -1)
        except GLib.Error as error:
            raise AutostartError(error.message) from error
        GLib.timeout_add_seconds(120, loop.quit)  # the user may be asked to confirm
        loop.run()
    finally:
        bus.signal_unsubscribe(subscription)
    if result.get('code') != 0 or bool(result['results'].get('autostart')) != enabled:
        raise AutostartError('The desktop did not allow starting at login')
