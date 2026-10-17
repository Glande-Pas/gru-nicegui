# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""System tray icon showing the number of pending updates.

It runs as its own process (`gru-app --tray`): the app's window process owns the GUI main loop and quits with the
window, whereas pystray needs the main thread of a process of its own. The app and the tray helper communicate through
files in the user cache dir: a lock for a single helper, and the update count the app publishes after each scan.
"""

import importlib.resources
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

from gru.config import load_config, user_cache

CHECK_EVERY = 3600  # seconds between scans
POLL_EVERY = 30  # seconds between looking at the config and the count published by the app
_LOCK = 'tray.lock'
_COUNT = 'tray-updates.json'


def available() -> bool:
    """Whether the optional tray dependencies are installed (not whether the desktop will show the icon)."""
    return all(importlib.util.find_spec(name) is not None for name in ('pystray', 'PIL'))


def enabled(config=None) -> bool:
    return (config or load_config()).getboolean('app', 'tray', fallback=False)


def _acquire_lock():
    """An open, locked file while this is the only tray helper; None if another one holds the lock."""
    path = user_cache(_LOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, 'a+')
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def is_running() -> bool:
    handle = _acquire_lock()
    if handle is None:
        return True
    handle.close()
    return False


def launch_command() -> list[str]:
    """The command line starting this app."""
    return [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'main']


def start_detached(args: list[str]) -> None:
    """Start the app with `args`, outliving this process."""
    env = dict(os.environ)
    if getattr(sys, 'frozen', False):
        env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'  # unpack afresh rather than reuse this process's bundle
    command = launch_command() + args
    quiet = {'env': env, 'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if os.name == 'nt':
        subprocess.Popen(command, creationflags=0x08000000 | 0x00000008, **quiet)  # CREATE_NO_WINDOW | DETACHED_PROCESS
    else:
        subprocess.Popen(command, start_new_session=True, **quiet)


def ensure_running() -> None:
    """Start the tray helper unless one is already running."""
    if available() and not is_running():
        start_detached(['--tray'])


def publish_count(count: int) -> None:
    """Tell the tray helper the number of updates the app found, so it needn't rescan."""
    try:
        path = user_cache(_COUNT)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'count': count, 'time': time.time()}))
    except OSError:
        pass


def read_count(after: float) -> int | None:
    """The count published by the app since time `after`, if any."""
    try:
        data = json.loads(user_cache(_COUNT).read_text())
        return int(data['count']) if float(data['time']) > after else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def badge_icon(count: int):
    """The app icon with `count` in a red disc in the corner; the bare icon for 0."""
    from PIL import Image, ImageDraw, ImageFont
    size = 64
    with importlib.resources.files('gru_ui').joinpath('assets', 'icon.png').open('rb') as f:
        image = Image.open(f).convert('RGBA').resize((size, size), Image.LANCZOS)
    if count <= 0:
        return image
    text = str(count) if count < 100 else '99+'
    diameter = 40 if len(text) < 3 else 46
    draw = ImageDraw.Draw(image)
    box = (size - diameter, size - diameter, size - 1, size - 1)
    draw.ellipse(box, fill='#e53935', outline='white', width=2)
    try:
        font = ImageFont.load_default(size=26 if len(text) < 3 else 20)
    except TypeError:  # Pillow < 10.1: fixed-size font
        font = ImageFont.load_default()
    draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text, fill='white', font=font, anchor='mm')
    return image


def run() -> None:
    """Show the tray icon until Quit (blocking). Quietly does nothing if one is already shown or can't be."""
    lock = _acquire_lock()
    if lock is None:
        return
    try:
        import pystray
    except Exception:  # no usable backend on this desktop
        return
    Tray(pystray).run()


class Tray:
    def __init__(self, pystray):
        self.count = 0
        self.checked = 0.0  # monotonic time of the last scan
        self.seen = 0.0  # time of the last count taken from the app
        self.wake = threading.Event()
        self.stopping = False
        self.icon = pystray.Icon(
            'gru', badge_icon(0), 'Gru',
            pystray.Menu(
                pystray.MenuItem('Open Gru', self.open, default=True),
                pystray.MenuItem(lambda item: 'Updates available: {count}'.format(count=self.count), None,
                                 enabled=False),
                pystray.MenuItem('Check for updates now', lambda: self.wake.set()),
                pystray.MenuItem('Quit', self.quit),
            ))

    def run(self) -> None:
        self.icon.run(self.loop)

    def loop(self, icon) -> None:
        icon.visible = True
        forced = False
        while not self.stopping:
            if not enabled():
                break
            published = read_count(self.seen)
            if published is not None:
                self.seen = time.time()
                self.apply(published)
            if forced or time.monotonic() - self.checked >= CHECK_EVERY:
                self.check()
            forced = self.wake.wait(POLL_EVERY)
            self.wake.clear()
        icon.stop()

    def check(self) -> None:
        from .state import get_state, rescan, update_count
        state = get_state()
        try:
            if state.local is None:
                state.load_local()
            else:
                rescan(readonly=True)
            self.apply(update_count(state.local) if state.local is not None else 0)
        except Exception:
            pass  # offline or mid-write: try again at the next check
        self.checked = time.monotonic()

    def apply(self, count: int) -> None:
        increased = count > self.count
        self.count = count
        self.icon.icon = badge_icon(count)
        self.icon.title = 'Gru: updates available: {count}'.format(count=count) if count else 'Gru'
        self.icon.update_menu()
        if increased and self.icon.HAS_NOTIFICATION:
            try:
                self.icon.notify('Updates available: {count}'.format(count=count), 'Gru')
            except Exception:
                pass

    def open(self) -> None:
        from . import single_instance
        if not single_instance.forward(''):
            start_detached([])

    def quit(self) -> None:
        self.stopping = True
        self.wake.set()
