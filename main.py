"""Entry point: registers every page and starts the NiceGUI server."""

import importlib.resources

from nicegui import ui

import pages.about  # noqa: F401
import pages.settings  # noqa: F401
import pages.installed  # noqa: F401
import pages.search  # noqa: F401

_ICON = importlib.resources.files('gru_ui').joinpath('assets', 'icon.png')


def run():
    ui.run(title='Gru', favicon=str(_ICON), dark=True, reload=False)


if __name__ in {'__main__', '__mp_main__'}:
    run()
