# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Named GUI color themes, selected via the app.theme config value.

Every entry but `dark` is registered as a Quasar color, i.e. the CSS variable --q-<name> (underscores
become hyphens) plus the .text-<name> / .bg-<name> classes, and used by those names in props and CSS. """

THEMES = {
    'Midnight Gold': {
        'dark': True,
        'primary': '#FFC800',
        'secondary': '#2B2B52',
        'warning': '#FF9800',
        'link': '#FFC800',
        'title_bg': 'rgba(151,166,195,0.15)',
        'title_fg': 'inherit',
        'title_border': 'rgba(151,166,195,0.25)',
        'toggle_bg': '#3d3d58',
        'toggle_fg': '#e8e8e8',
        'header_toggle_bg': 'rgba(255,255,255,0.14)',
        'header_fg': '#ffffff',
        'button_fg': '#1a1a1a',
        'badge_bg': 'rgba(255,171,0,0.15)',
        'badge_border': 'rgba(255,171,0,0.4)',
    },
    'Daylight': {
        'dark': False,
        'primary': '#FFC800',
        'secondary': '#2B2B52',
        'warning': '#C77700',
        'link': '#8A5A00',
        'title_bg': '#2B2B52',
        'title_fg': '#e8e8e8',
        'title_border': 'rgba(255,255,255,0.12)',
        'toggle_bg': '#dfe2ec',
        'toggle_fg': '#1a1a1a',
        'header_toggle_bg': 'rgba(255,255,255,0.14)',
        'header_fg': '#ffffff',
        'button_fg': '#1a1a1a',
        'badge_bg': 'rgba(255,171,0,0.15)',
        'badge_border': 'rgba(255,171,0,0.4)',
    },
}

DEFAULT_THEME = 'Daylight'


def get_theme(name: str) -> dict:
    return THEMES.get(name, THEMES[DEFAULT_THEME])
