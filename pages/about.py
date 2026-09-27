# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""About page: what Gru is, straight from gru itself (same text the CLI's `gru about` shows)."""

from nicegui import ui

from gru.app import ABOUT
from gru_ui import shell


@ui.page('/about')
def about_page():
    shell.frame('/about')
    ui.markdown(ABOUT)
