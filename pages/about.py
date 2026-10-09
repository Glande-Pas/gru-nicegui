# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""About page: what Gru is, straight from gru itself (same text the CLI's `gru about` shows)."""

from nicegui import ui

from gru.app import ABOUT
from gru.channel import detect as detect_channel
from gru_ui import shell
from gru_ui.components import external_link
from gru_ui.utils import package_version


@shell.page('/about')
def about_page():
    ui.markdown(ABOUT)
    ui.separator()
    ui.label(f'gru-nicegui {package_version("gru-nicegui")}  ·  gru {package_version("gru-eso")}  ·  '
             f'installed via {detect_channel()}').classes('text-caption')
    with ui.row().classes('items-center gap-1'):
        ui.label('Licensed under the').classes('text-caption')
        external_link('EUPL-1.2', 'https://joinup.ec.europa.eu/software/page/eupl', style='font-size:0.85em')
