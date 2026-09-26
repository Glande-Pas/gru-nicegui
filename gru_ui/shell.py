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
_ICON = importlib.resources.files('gru_ui').joinpath('assets', 'icon.png')

# "Gold": yellow primary (buttons, active nav, links) on charcoal, with a denim-blue header --
# keeps the header from turning into a solid yellow bar while tying the palette to Gru's own mascot.
PRIMARY = '#FFC800'
SECONDARY = '#2B2B52'
WARNING = '#FF9800'

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
a {
    color: %(primary)s;
}
""" % {'primary': PRIMARY}

# Quasar's QBtn defaults to white text on any filled color, and dark mode has its own !important
# overrides for it -- an !important inline style is the only thing that reliably beats both.
ui.button.default_props('text-color=#1a1a1a')
ui.button.default_style('color: #1a1a1a !important')


def frame(active: str):
    """Add the header + left nav drawer to the current page. Call first, then add page content."""
    ui.add_head_html(f'<style>{_META_CSS}</style>')
    ui.colors(primary=PRIMARY, secondary=SECONDARY, warning=WARNING)

    with ui.header().classes('items-center justify-between bg-secondary'):
        with ui.row().classes('items-center gap-2'):
            ui.image(str(_ICON)).classes('w-8 h-8')
            ui.label('Gru').classes('text-h5')

    with ui.left_drawer().classes('items-stretch'):
        for path, icon, title in _PAGES:
            with ui.link(target=path).classes('no-underline'):
                with ui.row().classes(
                        'items-center gap-2 w-full p-2 rounded ' +
                        ('bg-primary text-black font-medium' if path == active
                         else 'text-primary hover:bg-gray-500/20')):
                    ui.label(icon)
                    ui.label(title)
        ui.image(str(_LOGO)).classes('w-full')

    ui.page_title(f'Gru — {dict((p, t) for p, _, t in _PAGES).get(active, "")}')
