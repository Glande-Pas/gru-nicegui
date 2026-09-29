# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""About page: what Gru is, straight from gru itself (same text the CLI's `gru about` shows)."""

import importlib.metadata

from nicegui import ui

from gru.app import ABOUT
from gru_ui import shell
from gru_ui.components import external_link


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return 'unknown'


@shell.page('/about')
def about_page():
    ui.markdown(ABOUT)
    ui.separator()
    ui.label(f'gru-nicegui {_version("gru-nicegui")}  ·  gru {_version("gru")}').classes('text-caption')
    with ui.row().classes('items-center gap-1'):
        ui.label('Licensed under the').classes('text-caption')
        external_link('EUPL-1.2', 'https://joinup.ec.europa.eu/software/page/eupl', style='font-size:0.85em')
        ui.label('— see LICENSE.md for the full text.').classes('text-caption')
