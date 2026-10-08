# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Shared page chrome: header with logo and the left nav drawer, built once around the app's pages."""

import importlib.resources
from collections.abc import Callable

from nicegui import ui

from .state import get_state, set_target
from .themes import get_theme, DEFAULT_THEME

BUILTIN_COLORS = {'primary', 'secondary', 'warning'}  # Quasar already has classes for these

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
    color: var(--q-link);
}
.gru-card-title {
    background: var(--q-title-bg);
    color: var(--q-title-fg);
    padding: 0.35rem 0.6rem;
    margin: -1rem -1rem 0.75rem;
    border-radius: 6px 6px 0 0;
    border-bottom: 1px solid var(--q-title-border);
}
.gru-badge-warn {
    display: inline-block;
    font-size: 0.85em;
    padding: 0.1rem 0.45rem;
    background: var(--q-badge-bg);
    border: 1px solid var(--q-badge-border);
    border-radius: 0.4rem;
}
/* QUploader hardcodes white header text in its own stylesheet -- no prop reaches it. */
.q-uploader__header {
    color: var(--q-button-fg) !important;
}
"""

# `dense` keeps the many-button addon-card toolbars compact; button text color is the theme's custom
# `button-fg` color, registered in root() along with the rest of the theme.
ui.button.default_props('dense text-color=button-fg')


_ROUTES: dict[str, Callable[[], None]] = {}


def page(path: str):
    """Register a page's content builder. Pages are shown inside the shared frame built once by root()."""
    def decorator(builder: Callable[[], None]) -> Callable[[], None]:
        _ROUTES[path] = builder
        return builder
    return decorator


def root():
    """The app's single real page: header and left nav drawer, with the registered pages below them."""
    theme_name = get_state().config.get('app', 'theme', fallback=DEFAULT_THEME)
    theme = get_theme(theme_name)

    ui.add_head_html(f'<style>{_META_CSS}</style>')
    colors = {key: value for key, value in theme.items() if key != 'dark'}
    ui.colors(**colors)
    # ui.colors only applies once the page mounts: emit the same variables and classes in the initial HTML
    # so the first paint is already themed
    names = {key: key.replace('_', '-') for key in colors}
    ui.add_head_html('<style>body {' + ''.join(f'--q-{names[key]}: {value};' for key, value in colors.items()) + '}'
                     + ''.join(f'.text-{name} {{ color: var(--q-{name}) !important; }}'
                               f'.bg-{name} {{ background-color: var(--q-{name}) !important; }}'
                               for name in names.values() if name not in BUILTIN_COLORS) + '</style>')
    ui.dark_mode(theme['dark'])

    # The header stays denim regardless of theme, so its text must stay light regardless too.
    with ui.header().classes('items-center justify-between bg-secondary text-header-fg'):
        with ui.row().classes('items-center gap-2'):
            drawer_toggle = ui.button(icon='menu', on_click=lambda: drawer.toggle()) \
                .props('flat round text-color=header-fg')
            ui.image(str(_ICON)).classes('w-8 h-8')
            ui.label('Gru').classes('text-h5')
        state = get_state()

        def on_target_change(e):
            set_target(e.value)
            ui.navigate.reload()

        if state.target_available('pts'):
            with ui.row().classes('items-center gap-2'):
                if state.target != 'live':
                    ui.badge('PTS', color='warning').props('text-color=button-fg')
                ui.toggle({'live': 'Live', 'pts': 'PTS'}, value=state.target, on_change=on_target_change) \
                    .props('dense no-caps color=header-toggle-bg text-color=header-fg '
                           'toggle-color=primary toggle-text-color=button-fg')

    nav_rows = {}
    with ui.left_drawer().classes('items-stretch') as drawer:
        for path, icon, title in _PAGES:
            with ui.link(target=path).classes('no-underline'):
                with ui.row().classes('items-center gap-2 w-full p-2 rounded') as nav_rows[path]:
                    ui.label(icon)
                    ui.label(title)
        with ui.column().classes('w-full flex-grow min-h-0 overflow-hidden'):
            ui.image(str(_LOGO)).classes('w-full').props('fit=cover position=top')

    def show_active(path: str):
        active = path.split('?', 1)[0].split('#', 1)[0] or '/'
        for page_path, row in nav_rows.items():
            if page_path == active:
                row.classes(add='bg-primary text-button-fg font-medium', remove='hover:bg-gray-500/20 text-link')
            else:
                row.classes(add='hover:bg-gray-500/20 text-link', remove='bg-primary text-button-fg font-medium')
        ui.page_title(f'Gru — {dict((p, t) for p, _, t in _PAGES).get(active, "")}')

    router = ui.context.client.sub_pages_router
    router.on_path_changed(show_active)
    show_active(router.current_path)

    ui.sub_pages(_ROUTES).classes('w-full')
