"""Entry point: registers every page and starts the NiceGUI server."""

import importlib.resources

from nicegui import ui

import pages.about  # noqa: F401
import pages.settings  # noqa: F401
import pages.installed  # noqa: F401
import pages.search  # noqa: F401
import pages.patches  # noqa: F401
import pages.changes  # noqa: F401
from gru_ui.themes import THEMES, DEFAULT_THEME

_ICON = importlib.resources.files('gru_ui').joinpath('assets', 'icon.png')


def run():
    # Actual theme/dark-mode is applied per-page in shell.frame() from the app.theme config;
    # this is only the pre-hydration default for the very first paint.
    ui.run(title='Gru', favicon=str(_ICON), dark=THEMES[DEFAULT_THEME]['dark'], reload=False)


if __name__ in {'__main__', '__mp_main__'}:
    run()
