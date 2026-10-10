#!/usr/bin/env python3
# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Entry point: registers every page and starts the NiceGUI server."""

import importlib.resources

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

_ICON = importlib.resources.files('gru_ui').joinpath('assets', 'icon.png')
_ICON_ICO = importlib.resources.files('gru_ui').joinpath('assets', 'icon.ico')


def initial_theme() -> dict:
    """The configured theme, so the first paint matches before the page applies it."""
    return get_theme(load_config().get('app', 'theme', fallback=DEFAULT_THEME))


def run():
    # Read by Windows WinForms backend, and throws if it isn't a real .ico
    app.native.start_args['icon'] = str(_ICON_ICO)
    app.native.settings['ALLOW_DOWNLOADS'] = True
    theme = initial_theme()
    # Window background shown until the page loads
    app.native.window_args['background_color'] = theme['page_bg']
    ui.run(shell.root, title='Gru', favicon=str(_ICON_ICO), dark=theme['dark'], reload=False,
           native=True, window_size=(1400, 900), reconnect_timeout=10)


if __name__ in {'__main__', '__mp_main__'}:
    run()
