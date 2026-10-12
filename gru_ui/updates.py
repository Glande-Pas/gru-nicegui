# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Once-a-day check of the latest GitHub release for a newer Gru, published once the store build is certified."""

import json
import re
import time

import requests
from gru.channel import Channel, detect as detect_channel
from gru.config import user_cache

CHECK_EVERY = 24 * 3600  # seconds
_CACHE = 'gru-nicegui-release-v3.json'

_CHANNEL_URLS = {
    Channel.MSSTORE: 'https://apps.microsoft.com/detail/9P1251PBNJMM',
    Channel.PYPI: 'https://pypi.org/project/gru-nicegui/',
}
_RELEASES_URL = 'https://github.com/Glande-Pas/gru-nicegui/releases/latest'


def latest_release() -> tuple[str, str] | None:
    """(version, release page) of the newest published release, fetched at most once a day; None if unknown."""
    try:
        path = user_cache(_CACHE)
        try:
            cached = json.loads(path.read_text())
        except (OSError, ValueError):
            cached = {}
        if time.time() - cached.get('checked', 0) >= CHECK_EVERY:
            # /releases/latest redirects to the newest published release, ignoring bare tags
            response = requests.head(_RELEASES_URL, allow_redirects=False, timeout=10)
            link = response.headers.get('Location', '')
            if response.status_code // 100 != 3 or '/releases/tag/' not in link:
                return None
            cached = {'version': link.rsplit('/', 1)[-1].removeprefix('v'), 'link': link}
            path.write_text(json.dumps({**cached, 'checked': time.time()}))
        return (cached['version'], cached['link']) if cached.get('version') else None
    except Exception:
        return None


def is_newer(latest: str, current: str) -> bool:
    """Whether release `latest` is newer than `current`, a release or `git describe` string; False if unparsable."""
    def numbers(version):
        match = re.match(r'v?(\d+(?:\.\d+)*)', version)
        return tuple(int(n) for n in match.group(1).split('.')) if match else None
    new, old = numbers(latest), numbers(current)
    return new is not None and old is not None and new > old


def update_url(release_page: str) -> str:
    """Where to get the update for this install channel."""
    return _CHANNEL_URLS.get(detect_channel(), release_page)
