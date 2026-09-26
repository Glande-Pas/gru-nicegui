"""Named GUI color themes, selected via the app.theme config value."""

THEMES = {
    'Midnight Gold': {
        'dark': True,
        'primary': '#FFC800',
        'secondary': '#2B2B52',
        'warning': '#FF9800',
        'link': '#FFC800',
    },
    'Daylight': {
        'dark': False,
        'primary': '#FFC800',
        'secondary': '#2B2B52',
        'warning': '#C77700',
        'link': '#8A5A00',
    },
}

DEFAULT_THEME = 'Daylight'


def get_theme(name: str) -> dict:
    return THEMES.get(name, THEMES[DEFAULT_THEME])
