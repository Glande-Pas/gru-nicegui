# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Shared page chrome: header with logo, and the left nav drawer."""

import importlib.resources

from nicegui import ui

from .state import get_state
from .themes import get_theme, DEFAULT_THEME

_PAGES = [
    ('/', '📦', 'Installed Add-Ons'),
    ('/search', '🔍', 'Search'),
    ('/patches', '📝', 'Patches'),
    ('/settings', '⚙️', 'Settings'),
    ('/changes', '🕓', 'Recent Changes'),
    ('/about', 'ℹ️', 'About'),
]

_LOGO = importlib.resources.files('gru_ui').joinpath('assets', 'gru.png')
_ICON = importlib.resources.files('gru_ui').joinpath('assets', 'icon.png')

_META_CSS = """
.gru-meta-cell {
    display: grid;
    grid-template-columns: auto 1fr;
    column-gap: 0.4em;
    align-items: baseline;
    min-width: 0;
}
.gru-meta-lbl {
    opacity: 0.6;
    white-space: nowrap;
}
.gru-meta-nowrap {
    display: block;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
a {
    color: %(link)s;
}
/* QUploader hardcodes white header text in its own stylesheet -- no prop reaches it. */
.q-uploader__header {
    color: #1a1a1a !important;
}
"""

# Quasar's QBtn defaults to white text on any filled color, and dark mode has its own !important
# overrides for it -- an !important inline style is the only thing that reliably beats both.
# `dense` keeps the many-button addon-card toolbars compact.
ui.button.default_props('text-color=#1a1a1a dense')
ui.button.default_style('color: #1a1a1a !important')


def frame(active: str):
    """Add the header + left nav drawer to the current page. Call first, then add page content."""
    theme_name = get_state().config.get('app', 'theme', fallback=DEFAULT_THEME)
    theme = get_theme(theme_name)

    ui.add_head_html(f'<style>{_META_CSS % {"link": theme["link"]}}</style>')
    ui.colors(primary=theme['primary'], secondary=theme['secondary'], warning=theme['warning'])
    ui.dark_mode(theme['dark'])

    # The header stays denim regardless of theme, so its text must stay light regardless too.
    with ui.header().classes('items-center justify-between bg-secondary text-white'):
        with ui.row().classes('items-center gap-2'):
            drawer_toggle = ui.button(icon='menu', on_click=lambda: drawer.toggle()).props('flat round')
            ui.image(str(_ICON)).classes('w-8 h-8')
            ui.label('Gru').classes('text-h5')
    drawer_toggle.style('color: white !important')

    with ui.left_drawer().classes('items-stretch') as drawer:
        for path, icon, title in _PAGES:
            with ui.link(target=path).classes('no-underline'):
                row = ui.row().classes('items-center gap-2 w-full p-2 rounded ' +
                                       ('bg-primary text-black font-medium' if path == active
                                        else 'hover:bg-gray-500/20'))
                if path != active:
                    row.style(f'color: {theme["link"]}')
                with row:
                    ui.label(icon)
                    ui.label(title)
        with ui.column().classes('w-full flex-grow min-h-0 overflow-hidden'):
            ui.image(str(_LOGO)).classes('w-full').props('fit=cover position=top')

    ui.page_title(f'Gru — {dict((p, t) for p, _, t in _PAGES).get(active, "")}')
