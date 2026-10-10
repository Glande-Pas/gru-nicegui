# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""About page."""

from nicegui import ui

from gru.channel import detect as detect_channel
from gru_ui import shell
from gru_ui.components import external_link
from gru_ui.utils import package_version

ABOUT = """\
Gru gets, removes, and updates Elder Scrolls Online (ESO) add-ons from ESOUI.com.

Gru is an independent, unofficial tool. It is not affiliated with, endorsed by, or sponsored by \
ZeniMax Online Studios, Bethesda Softworks, ESOUI, Minion, or the Desplicable Me franchise. \
The Elder Scrolls Online and ESOUI are trademarks of their respective owners.

Add-on hosting, organization, and moderation are handled entirely by ESOUI.com.
"""


@shell.page('/about')
def about_page():
    ui.markdown(ABOUT)
    ui.separator()
    ui.label('gru-nicegui {ui_version}  ·  gru {gru_version}  ·  installed via {channel}'.format(
        ui_version=package_version('gru-nicegui'), gru_version=package_version('gru-eso'),
        channel=detect_channel())).classes('text-caption')
    with ui.row().classes('items-center gap-1'):
        ui.label('Licensed under the').classes('text-caption')
        external_link('EUPL-1.2', 'https://joinup.ec.europa.eu/software/page/eupl', style='font-size:0.85em')
