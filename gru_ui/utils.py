# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Formatting helpers, ported from gru-toga."""

import importlib.metadata
import locale
import math
import os
import re
import subprocess
import sys


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
    """Convert ESO color codes (|cRRGGBB...|r) to HTML <span> elements."""
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


def fuzzy_score(query: str, text: str) -> tuple[int, int, int] | None:
    """How well `query` matches `text`, lower is better, or None if it doesn't match at all. """
    text = text.lower()
    search_pos = 0
    gaps = []
    for ch in query.lower():
        ch_pos = text.find(ch, search_pos)
        if ch_pos == -1:
            return None
        if ch_pos != search_pos:
            gaps.append(ch_pos - search_pos)
        search_pos = ch_pos + 1
    # penalize for: nb of separate match words, distance in between matches, nb letters un-matched
    return len(gaps), sum(gaps), len(query) - len(text)


def anchor_id(dir_name: str) -> str:
    """A stable, link-safe HTML id for a top-level installed addon's card."""
    return 'addon-' + re.sub(r'[^\w-]', '_', dir_name)


def open_folder(path) -> None:
    """Open a folder in the OS file explorer."""
    if sys.platform == 'win32':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])


try:
    # Written by gru.spec: a frozen build has no package metadata to read
    from gru_ui._build_version import VERSIONS
except ImportError:
    VERSIONS = {}


def package_version(package: str) -> str:
    if package in VERSIONS:
        return VERSIONS[package]
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return 'unknown'


def bold(text: str) -> str:
    """`text` (with ESO color codes) as bold HTML, for use as a placeholder value in a message."""
    return f'<b>{eso_colored(text)}</b>'


def code(text: str) -> str:
    """`text` as monospace HTML, for use as a placeholder value in a message."""
    return f'<code>{text}</code>'


def installed_item(title: str, version: str) -> str:
    return '{title} {version}'.format(title=bold(title), version=version)


def updated_item(title: str, before: str, after: str) -> str:
    return '{title} {before} → {after}'.format(title=bold(title), before=before, after=after)
