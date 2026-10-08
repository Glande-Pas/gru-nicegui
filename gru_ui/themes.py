# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Named GUI color themes, selected via the app.theme config value."""

THEMES = {
    'Midnight Gold': {
        'dark': True,
        'primary': '#FFC800',
        'secondary': '#2B2B52',
        'warning': '#FF9800',
        'link': '#FFC800',
        'toggle_bg': '#3d3d58',
        'toggle_fg': '#e8e8e8',
    },
    'Daylight': {
        'dark': False,
        'primary': '#FFC800',
        'secondary': '#2B2B52',
        'warning': '#C77700',
        'link': '#8A5A00',
        'toggle_bg': '#dfe2ec',
        'toggle_fg': '#1a1a1a',
    },
}

DEFAULT_THEME = 'Daylight'


def get_theme(name: str) -> dict:
    return THEMES.get(name, THEMES[DEFAULT_THEME])
