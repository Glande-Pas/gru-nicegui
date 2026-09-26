#!/usr/bin/env python3
"""Entry point: registers every page and starts the NiceGUI server."""

import importlib.resources

from nicegui import app, ui

import pages.about  # noqa: F401
import pages.settings  # noqa: F401
import pages.installed  # noqa: F401
import pages.search  # noqa: F401
import pages.patches  # noqa: F401
import pages.changes  # noqa: F401
from gru_ui.themes import THEMES, DEFAULT_THEME

_ICON = importlib.resources.files('gru_ui').joinpath('assets', 'icon.png')


def run():
    app.native.start_args['icon'] = str(_ICON)
    ui.run(title='Gru', favicon=str(_ICON), dark=THEMES[DEFAULT_THEME]['dark'], reload=False,
           native=True, window_size=(1400, 900))


if __name__ in {'__main__', '__mp_main__'}:
    run()
