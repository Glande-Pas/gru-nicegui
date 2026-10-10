# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Process-wide app state and shared business-logic helpers."""

import asyncio
import concurrent.futures
import contextlib
import functools
import io
import locale
import pathlib
import threading
import time
import warnings

from nicegui import run, ui

from gru import patch as gru_patch
from gru.app import log_changes, rank_candidates, find_ambiguous, resolve_exact_matches
from gru.config import root_key, load_config, save_config, user_config
from gru.api import API, AmbiguousDirectory
from gru.cache import prune_downloads
from gru.install import Folder

from .utils import strip_eso_colors


GAME = 'ESO'
API_MAX_AGE = 3600  # seconds, matches gru's HTTP cache lifetime

_RESOLVE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='gru-resolve')
_ambiguous_future = None


class AppState:
    def __init__(self):
        locale.setlocale(locale.LC_ALL, '')
        self.config = load_config()
        self.api = API.live(self.config)
        self.api_loaded = time.monotonic()
        self.pending_search = ''
        self.local = None
        self.local_loaded = False
        self.target = self.config.get('app', 'target', fallback='live')
        if not self.target_available(self.target):
            self.target = 'live'

    def target_available(self, target: str) -> bool:
        root = self.config.get(f'{GAME}.addons', root_key(target), fallback='')
        return bool(root) and pathlib.Path(root).exists()

    def load_local(self) -> None:
        """Scan the addons folder against ESOUI data: slow, call from a worker."""
        self.local = None
        try:
            if self.target_available(self.target):
                local = Folder(GAME, self.config, self.target)
                local.scan(self.api)
                self.local = local
                with contextlib.suppress(OSError):
                    prune_downloads(local.installed)
                self.api.prune_cache()
        finally:
            self.local_loaded = True


_state = None
_state_lock = threading.Lock()
_load_lock = asyncio.Lock()


def get_state() -> AppState:
    """The process-wide state. Cheap: the addons folder is scanned by ensure_loaded()."""
    global _state
    if _state is None:
        with _state_lock:
            if _state is None:
                _state = AppState()
    return _state


async def ensure_loaded() -> None:
    """Scan the addons folder once, off the event loop, before a page needs `state.local`."""
    state = get_state()
    if state.local_loaded:
        return
    async with _load_lock:
        if not state.local_loaded:
            await run.io_bound(state.load_local)
            spawn_ambiguous_resolution()


def flash_warning(message: str):
    ui.notify(f'⚠️ {message}', type='warning', html=True, multi_line=True, close_button=True)


def flash_info(message: str):
    ui.notify(f'ℹ️ {message}', type='info', html=True, multi_line=True, close_button=True)


def flash_summary(heading: str, items: list[str], flash=flash_info):
    """One notification for a whole batch, e.g. 'Updated (3):' followed by one line per item."""
    if len(items) == 1:
        flash('{heading}: {item}'.format(heading=heading, item=items[0]))
    elif items:
        flash('{heading} ({count}):'.format(heading=heading, count=len(items)) + '<br/>'
              + '<br/>'.join(f'• {item}' for item in items))


def flash_warnings(caught):
    """Merge the warnings recorded by warnings.catch_warnings() into a single notification."""
    flash_summary('Warnings', list(dict.fromkeys(str(w.message) for w in caught)), flash_warning)


def _invalidate_api():
    """Drop all cached ESOUI data (HTTP and in-memory) in place."""
    state = get_state()
    api = state.api
    api.session.cache.clear()
    api.zip_session.cache.clear()
    for name, attr in vars(type(api)).items():
        if isinstance(attr, functools.cached_property):
            api.__dict__.pop(name, None)
    state.api_loaded = time.monotonic()


def rescan():
    """Re-scan the addons directory, against fresh ESOUI data if the loaded data is over an hour old."""
    state = get_state()
    if time.monotonic() - state.api_loaded > API_MAX_AGE:
        _invalidate_api()
    if state.local is not None:
        state.local.scan(state.api)
        spawn_ambiguous_resolution()


def search_for(term: str):
    """Open the Search page with `term` already searched."""
    get_state().pending_search = term
    ui.navigate.to('/search')


def dependency_search_term(dir_name: str) -> str:
    """Search term finding the ESOUI add-on providing folder `dir_name`: its title if known, else the folder name."""
    try:
        return strip_eso_colors(get_state().api.dir(dir_name).title) or dir_name
    except (FileNotFoundError, AmbiguousDirectory):
        return dir_name


async def rescan_async():
    """rescan() off the event loop, as it may fetch fresh ESOUI data."""
    await run.io_bound(rescan)


def refresh_api():
    """Force-refresh the ESOUI data, then rescan against it."""
    _invalidate_api()
    rescan()


async def set_addons_root(path: pathlib.Path | None, target: str = 'live'):
    """Persist a new addons root for `target` (None clears it) and reinitialise the Folder if it's the active one."""
    state = get_state()
    state.config.set(f'{GAME}.addons', root_key(target), str(path.resolve()) if path else '')
    save_config(state.config)

    if target == state.target:
        if path is None:
            state.target = 'live'
            state.config.set('app', 'target', 'live')
            save_config(state.config)
        await run.io_bound(state.load_local)
        spawn_ambiguous_resolution()


async def set_target(target: str):
    """Switch the active game channel, persisting the choice."""
    state = get_state()
    if target == state.target or not state.target_available(target):
        return
    state.target = target
    state.config.set('app', 'target', target)
    save_config(state.config)
    await run.io_bound(state.load_local)
    spawn_ambiguous_resolution()


def spawn_ambiguous_resolution():
    """Auto-resolve ambiguous addon matches in the background via gru's CRC32 check."""
    global _ambiguous_future
    state = get_state()
    if state.local is None:
        return
    if _ambiguous_future is not None and not _ambiguous_future.done():
        return
    _ambiguous_future = _RESOLVE_EXECUTOR.submit(_resolve_ambiguous, state.local, state.api)


def _resolve_ambiguous(local, api) -> list | None:
    """Worker job: None when nothing was ambiguous, else the addons resolved."""
    if not find_ambiguous(local, api):
        return None
    return resolve_exact_matches(local, api)


def ambiguous_resolution_pending() -> bool:
    return _ambiguous_future is not None


async def poll_ambiguous_resolution() -> bool:
    """Call periodically; returns True once a pending background resolution has finished."""
    global _ambiguous_future
    if _ambiguous_future is None or not _ambiguous_future.done():
        return False

    future, _ambiguous_future = _ambiguous_future, None
    try:
        resolved = future.result()
    except Exception as exc:
        flash_warning('Auto-resolving ambiguous add-ons failed: {error}'.format(error=exc))
        return True

    if resolved is None:
        return False
    if resolved:
        await run.io_bound(get_state().local.export_state)
    return True


def opt_deps() -> bool:
    return get_state().config.getboolean(f'{GAME}.addons', 'optional')


def patches_enabled() -> bool:
    """Whether the advanced patches feature (Patches page, Save changes buttons) is shown."""
    return get_state().config.getboolean('app', 'patches', fallback=False)


def patch_updates() -> bool:
    """Whether a bulk update should re-apply each addon's saved patch afterwards."""
    return get_state().config.getboolean(f'{GAME}.addons', 'patch_updates')


def sortkey() -> str | None:
    key = get_state().config.get(f'{GAME}.addons', 'sortkey')
    return key if key in {'downloads', 'monthly', 'favorites'} else None


def update_moot(addon) -> bool:
    """Whether updating this addon is pointless: superseded by a newer copy elsewhere."""
    return addon.parent is not None and addon.is_superseded


def update_pending(addon) -> bool:
    """Whether an installed addon has an update that may be applied: outdated, not version-locked nor moot."""
    return addon.can_update and not addon.locked and not update_moot(addon)


def match_candidates(addon) -> list:
    """The online addons an installed folder could be, when several share its dir."""
    try:
        get_state().api.dir(addon.dir)
    except AmbiguousDirectory as err:
        return err.candidates
    except FileNotFoundError:
        pass
    return []


def ambiguous_candidates(addon) -> list:
    """match_candidates(), but only when the addon is still unmatched."""
    return [] if addon.infos is not None else match_candidates(addon)


def ranked_candidates(addon) -> list:
    """match_candidates(), best guess first -- the order `gru match` offers them in."""
    return rank_candidates(addon, match_candidates(addon), get_state().api, sortkey() or 'downloads')


async def set_match(addon, infos):
    """Record which online addon an installed folder is, as `gru match` does, persisted in addons.csv."""
    if addon.infos is not None:
        addon.infos.deregister(addon)
    addon.link(infos)
    await run.io_bound(get_state().local.export_state)


async def set_locked(addon, locked: bool):
    """Pin or unpin an installed addon to its current version, persisted in addons.csv as the CLI does."""
    addon.locked = locked
    await run.io_bound(get_state().local.export_state)


def diff_addon_patch(addon, api, local) -> tuple[int, str, list[str]]:
    """Diff `addon` against its unmodified ESOUI listing. Returns (modified-file count, diff text, warning messages).

    Does no UI work, so it is safe to run in a worker thread; raises on failure."""
    out = io.StringIO()
    with local.unmodified_addon(addon.infos, addon.dir, api) as ref_addon:
        with warnings.catch_warnings(record=True, category=UserWarning) as caught:
            n = gru_patch.addon_diff(addon, ref_addon, out)
    return n, out.getvalue(), [str(w.message) for w in caught]


def save_addon_patch(addon, api, local) -> tuple[int, list[str]]:
    """Diff `addon` against its unmodified ESOUI listing and save/update/remove its patch file.

    Returns (modified-file count, warning messages); raises on failure."""
    n, text, messages = diff_addon_patch(addon, api, local)

    patch_dir = user_config(*local.meta)
    patch_dir.mkdir(exist_ok=True)
    patch_path = patch_dir / f'{addon.dir}.patch'
    if n > 0:
        patch_path.write_text(text)
    elif patch_path.exists():
        patch_path.unlink()
    return n, messages


def remove_vars_setting() -> str:
    """Whether removing an addon also deletes its SavedVariables: 'yes', 'no' or 'ask'."""
    setting = get_state().config.get(f'{GAME}.addons', 'remove_saved_variables')
    return setting if setting in {'yes', 'no', 'ask'} else 'ask'


@contextlib.contextmanager
def logged_changes():
    """Persist changes made to addons within the block, as the CLI does."""
    state = get_state()
    before = state.local.snapshot()
    try:
        yield
    finally:
        state.local.export_state()
        log_changes(state.local, state.config, before)
