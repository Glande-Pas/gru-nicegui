#!/usr/bin/env python3
# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Entry point: registers every page and starts the NiceGUI server."""

import importlib.resources
import signal
import sys

from nicegui import app, ui

from gru.config import load_config

import pages.about  # noqa: F401
import pages.settings  # noqa: F401
import pages.installed  # noqa: F401
import pages.search  # noqa: F401
import pages.patches  # noqa: F401
import pages.changes  # noqa: F401
from gru_ui import shell
from gru_ui.themes import get_theme, DEFAULT_THEME

APP_ID = 'io.github.Glande_Pas.Gru'

if sys.platform.startswith('linux'):
    # GTK derives the window's app id from the program name; matching the .desktop id gives the window its icon
    try:
        from gi.repository import GLib
        GLib.set_prgname(APP_ID)
    except ImportError:
        pass  # no PyGObject: another pywebview backend

_ICON = importlib.resources.files('gru_ui').joinpath('assets', 'icon.png')
_ICON_ICO = importlib.resources.files('gru_ui').joinpath('assets', 'icon.ico')


def initial_theme() -> dict:
    """The configured theme, so the first paint matches before the page applies it."""
    return get_theme(load_config().get('app', 'theme', fallback=DEFAULT_THEME))


def window_size(width: int = 1400, height: int = 900) -> tuple[int, int]:
    """The preferred size, shrunk to fit the primary screen."""
    if sys.platform == 'darwin':  # AppKit clamps windows itself, and querying screens would load it in this process
        return width, height
    try:
        import webview
        screen = webview.screens[0]
    except Exception:  # no display/backend available: keep the preferred size
        return width, height
    return min(width, int(screen.width * 0.9)), min(height, int(screen.height * 0.9))


def run():
    # Read by Windows WinForms backend, and throws if it isn't a real .ico
    app.native.start_args['icon'] = str(_ICON_ICO)
    app.native.settings['ALLOW_DOWNLOADS'] = True
    theme = initial_theme()
    # Window background shown until the page loads
    app.native.window_args['background_color'] = theme['page_bg']
    # Ignored here, the window process inherits it: Ctrl+C is handled by the server in this process only
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        ui.run(shell.root, title='Gru', favicon=str(_ICON_ICO), dark=theme['dark'], reload=False,
               native=True, window_size=window_size(), reconnect_timeout=10)
    except KeyboardInterrupt:
        pass  # Ctrl+C in the terminal: exit quietly


if __name__ in {'__main__', '__mp_main__'}:
    run()
