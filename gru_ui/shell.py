"""Shared page chrome: header with logo, and the left nav drawer."""

import importlib.resources

from nicegui import ui

_PAGES = [
    ('/', '📦', 'Installed Add-Ons'),
    ('/search', '🔍', 'Search'),
    ('/patches', '📝', 'Patches'),
    ('/settings', '⚙️', 'Settings'),
    ('/changes', '🕓', 'Recent Changes'),
    ('/about', 'ℹ️', 'About'),
]

_LOGO = importlib.resources.files('gru_ui').joinpath('assets', 'gru.png')


_META_CSS = '''
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
'''


def frame(active: str):
    """Add the header + left nav drawer to the current page. Call first, then add page content."""
    ui.add_head_html(f'<style>{_META_CSS}</style>')

    with ui.header().classes('items-center justify-between'):
        ui.label('Gru').classes('text-h5')

    with ui.left_drawer().classes('items-stretch'):
        ui.image(str(_LOGO)).classes('w-full')
        for path, icon, title in _PAGES:
            with ui.link(target=path).classes('no-underline text-black dark:text-white'):
                with ui.row().classes(
                        'items-center gap-2 w-full p-2 rounded ' +
                        ('bg-primary text-white' if path == active else 'hover:bg-gray-500/20')):
                    ui.label(icon)
                    ui.label(title)

    ui.page_title(f'Gru — {dict((p, t) for p, _, t in _PAGES).get(active, "")}')
