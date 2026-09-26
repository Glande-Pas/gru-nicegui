"""Formatting helpers, ported from gru-toga."""

import locale
import math
import pathlib
import re
import warnings
from urllib.parse import urlparse

import requests
from gru.config import user_cache


def si_suffixed(num: int) -> str:
    """Human-readable number: 1234567 -> '1.2M'"""
    try:
        scale = int(math.log(num, 10) // 3)
    except ValueError:
        scale = 0
    scaled = num / 10 ** (3 * scale)
    suffixes = ['', 'k', 'M', 'G']
    return locale.format_string(f'%.{1 if scaled < 10 else 0}f{suffixes[scale]}', scaled)


def eso_colored(text: str) -> str:
    """Convert ESO color codes (|cRRGGBB...|r) to HTML <span> elements.

    Handles nested and sequential color codes; |r closes the innermost open span.
    Unclosed spans at end-of-string are closed automatically.
    """
    parts = re.split(r'(\|c[0-9A-Fa-f]{6}|\|r)', text)
    result = []
    open_spans = 0
    for part in parts:
        if re.match(r'\|c[0-9A-Fa-f]{6}$', part):
            result.append(f'<span style="color: #{part[2:]}">')
            open_spans += 1
        elif part == '|r':
            if open_spans > 0:
                result.append('</span>')
                open_spans -= 1
        else:
            result.append(part)
    result.extend(['</span>'] * open_spans)
    return ''.join(result)


def strip_eso_colors(text: str) -> str:
    """Remove ESO color codes (|cRRGGBB...|r), for plain-text contexts such as widget labels."""
    return re.sub(r'\|c[0-9A-Fa-f]{6}|\|r', '', text or '')


def anchor_id(dir_name: str) -> str:
    """A stable, link-safe HTML id for a top-level installed addon's card, so a `#`-link can
    scroll straight to it (e.g. from a warning banner listing unmatched addons)."""
    return 'addon-' + re.sub(r'[^\w-]', '_', dir_name)


def load_icon(icon_url: str) -> pathlib.Path | None:
    """Download icon to cache and return local path, or None on failure."""
    try:
        fname = pathlib.Path(urlparse(icon_url).path).name
        dest = user_cache() / fname
        if dest.exists():
            return dest

        with requests.get(icon_url, stream=True, allow_redirects=True, timeout=5) as dl:
            dl.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in dl.iter_content(1024):
                    f.write(chunk)
        return dest

    except Exception as err:
        warnings.warn(f'Error loading icon {icon_url!r}: {err}')
        return None
