# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Once-a-day check of the GitHub releases feed for a newer Gru, which is published once the store build is certified."""

import json
import time
import xml.etree.ElementTree as ET

import requests
from gru.channel import Channel, detect as detect_channel
from gru.config import user_cache

FEED = 'https://github.com/Glande-Pas/gru-nicegui/releases.atom'
CHECK_EVERY = 24 * 3600  # seconds
_ATOM = '{http://www.w3.org/2005/Atom}'
_CACHE = 'gru-nicegui-release.json'

_CHANNEL_URLS = {
    Channel.MSSTORE: 'https://apps.microsoft.com/detail/9P1251PBNJMM',
    Channel.PYPI: 'https://pypi.org/project/gru-nicegui/',
}
_RELEASES_URL = 'https://github.com/Glande-Pas/gru-nicegui/releases/latest'


def _latest_from_feed(text: str) -> tuple[str, str] | None:
    entry = ET.fromstring(text).find(f'{_ATOM}entry')
    if entry is None:
        return None
    title = (entry.findtext(f'{_ATOM}title') or '').strip()
    link = entry.find(f'{_ATOM}link')
    return (title.removeprefix('v'), link.get('href', _RELEASES_URL)) if title and link is not None else None


def latest_release() -> tuple[str, str] | None:
    """(version, release page) of the newest release, fetched at most once a day; None if unknown."""
    try:
        path = user_cache(_CACHE)
        try:
            cached = json.loads(path.read_text())
        except (OSError, ValueError):
            cached = {}
        if time.time() - cached.get('checked', 0) >= CHECK_EVERY:
            headers = {'If-None-Match': cached['etag']} if cached.get('etag') and cached.get('version') else {}
            response = requests.get(FEED, headers=headers, timeout=10)
            if response.status_code == 200:
                if (latest := _latest_from_feed(response.text)) is not None:
                    cached = {'etag': response.headers.get('ETag'), 'version': latest[0], 'link': latest[1]}
            elif response.status_code != 304:
                return None
            path.write_text(json.dumps({**cached, 'checked': time.time()}))
        return (cached['version'], cached['link']) if cached.get('version') else None
    except Exception:
        return None


def update_url(release_page: str) -> str:
    """Where to get the update for this install channel."""
    return _CHANNEL_URLS.get(detect_channel(), release_page)
