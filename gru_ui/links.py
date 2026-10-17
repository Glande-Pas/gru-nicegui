# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""gru:// links: an ESOUI.com add-on page link with `gru` as its scheme, opened in the running app.

    gru://www.esoui.com/downloads/info7-LibAddonMenu.html

The add-on's card on the Installed page if it is installed, else the Search page showing it.
"""

import hmac

from fastapi import HTTPException, Request
from nicegui import Client, app, run

from .importing import esoui_addon_id
from .state import ensure_loaded, flash_warning, get_state, search_for, show_installed_card
from .utils import anchor_id

SCHEME = 'gru'
MAX_LENGTH = 512
TOKEN_HEADER = 'X-Gru-Token'

pending: list[str] = []  # links received before any window was connected


def find_url(args: list[str]) -> str | None:
    """The first gru:// link among command line `args`."""
    return next((a for a in args if a.lower().startswith(SCHEME + '://')), None)


def parse(url: str) -> int | None:
    """The ESOUI.com add-on id `url` points to, or None if it isn't a gru:// add-on page link."""
    prefix = SCHEME + '://'
    if not isinstance(url, str) or len(url) > MAX_LENGTH or not url.strip().lower().startswith(prefix):
        return None
    return esoui_addon_id('https://' + url.strip()[len(prefix):])


async def open_link(url: str) -> None:
    """Act on `url` in the current client's context."""
    addon_id = parse(url)
    if addon_id is None:
        flash_warning('Ignored an unsupported link.')
        return
    await ensure_loaded()
    state = get_state()
    top = next((a for a in state.local.installed if getattr(a, 'id', None) == addon_id), None) \
        if state.local is not None else None
    if top is not None:
        while top.parent is not None:
            top = top.parent
        show_installed_card(anchor_id(top.dir))
        return
    info = await run.io_bound(lambda: state.api.addons.get(addon_id))
    if info is None:
        flash_warning('Add-on {id} not found on ESOUI.com.'.format(id=addon_id))
    else:
        search_for(info.title)


async def open_pending() -> None:
    """Open the links that arrived before the window did."""
    while pending:
        await open_link(pending.pop(0))


def raise_window() -> None:
    """Bring the app window to the front: a forwarded link comes from another app, so it is likely behind it."""
    window = app.native.main_window
    if window is None:
        return
    window.restore()
    window.show()
    window.set_always_on_top(True)  # toggling is the portable way to raise it
    window.set_always_on_top(False)


def register_routes(token: str) -> None:
    """Accept links forwarded by later launches of the app, authenticated by `token`."""
    @app.post('/_open')
    async def _open(request: Request):
        if not hmac.compare_digest(request.headers.get(TOKEN_HEADER, ''), token):
            raise HTTPException(status_code=403)
        url = (await request.json()).get('url')
        if url != '' and parse(url) is None:  # '' only asks to raise the window
            raise HTTPException(status_code=400)
        raise_window()
        if url == '':
            return {'ok': True}
        client = next((c for c in list(Client.instances.values()) if c.has_socket_connection), None)
        if client is None:
            pending.append(url)
        else:
            with client:
                await open_link(url)
        return {'ok': True}
