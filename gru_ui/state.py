"""Process-wide app state and shared business-logic helpers.

Unlike the Streamlit port this replaces, NiceGUI event handlers run in place (no rerun-from-top),
so there is no need to queue flash messages across reruns -- flash_info/flash_warning just fire an
ui.notify() immediately. State is a single process-wide singleton rather than per-session, matching
how this app is actually launched: one local desktop user, one addons directory.
"""

import concurrent.futures
import contextlib
import io
import locale
import pathlib
import warnings

from nicegui import ui

from gru import patch as gru_patch
from gru.app import log_changes, rank_candidates, find_ambiguous, resolve_exact_matches
from gru.config import load_config, save_config, user_config
from gru.api import API, AmbiguousDirectory
from gru.install import Folder

from .utils import eso_colored

GAME = 'ESO'

_RESOLVE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='gru-resolve')
_ambiguous_future = None


class AppState:
    def __init__(self):
        locale.setlocale(locale.LC_ALL, '')
        self.config = load_config()
        self.api = API.live(self.config)
        self.local = None
        root = self.config.get(f'{GAME}.addons', 'root')
        if root and pathlib.Path(root).exists():
            self.local = Folder(GAME, self.config)
            self.local.scan(self.api)


_state = None


def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
        spawn_ambiguous_resolution()
    return _state


def flash_warning(message: str):
    ui.notify(f'⚠️ {message}', type='warning', html=True, multi_line=True, close_button=True)


def flash_info(message: str):
    ui.notify(f'ℹ️ {message}', type='info', html=True, multi_line=True, close_button=True)


def rescan():
    """Re-scan the addons directory."""
    state = get_state()
    if state.local is not None:
        state.local.scan(state.api)
        spawn_ambiguous_resolution()


def set_addons_root(path: pathlib.Path):
    """Persist a new addons root and reinitialise the Folder."""
    state = get_state()
    state.config.set(f'{GAME}.addons', 'root', str(path.resolve()))
    save_config(state.config)

    state.local = Folder(GAME, state.config)
    state.local.scan(state.api)
    spawn_ambiguous_resolution()


def spawn_ambiguous_resolution():
    """After a scan, if any addon's directory is ambiguous online, try to auto-resolve it in the
    background via gru's CRC32 file-content check -- real network round trips per candidate, so
    this never blocks the caller. Skips spawning while a previous attempt is still running;
    poll_ambiguous_resolution() picks up the result."""
    global _ambiguous_future
    state = get_state()
    if state.local is None:
        return
    if _ambiguous_future is not None and not _ambiguous_future.done():
        return
    if not find_ambiguous(state.local, state.api):
        return
    _ambiguous_future = _RESOLVE_EXECUTOR.submit(resolve_exact_matches, state.local, state.api)


def ambiguous_resolution_pending() -> bool:
    return _ambiguous_future is not None


def poll_ambiguous_resolution() -> bool:
    """Call periodically (e.g. from a ui.timer) while a background resolution may be pending.
    Returns True once a resolution has just finished, meaning the caller should refresh its view."""
    global _ambiguous_future
    if _ambiguous_future is None or not _ambiguous_future.done():
        return False

    future, _ambiguous_future = _ambiguous_future, None
    try:
        resolved = future.result()
    except Exception as exc:
        flash_warning(f'Auto-resolving ambiguous add-ons failed: {exc}')
        return True

    if resolved:
        get_state().local.export_state()
        for addon in resolved:
            flash_info(f'Resolved: <b>{eso_colored(addon.title)}</b> — exact file content match')
    return True


def opt_deps() -> bool:
    return get_state().config.getboolean(f'{GAME}.addons', 'optional')


def patch_updates() -> bool:
    """Whether a bulk update should re-apply each addon's saved patch afterwards, as `gru update` does.
    Only a full "Update all" reapplies patches this way -- a single-addon update always installs the
    clean upstream version instead, as gru's own `get` command does."""
    return get_state().config.getboolean(f'{GAME}.addons', 'patch_updates')


def sortkey() -> str | None:
    key = get_state().config.get(f'{GAME}.addons', 'sortkey')
    return key if key in {'downloads', 'monthly', 'favorites'} else None


def update_moot(addon) -> bool:
    """Whether updating this addon is pointless: a bundled copy outranked by a newer copy elsewhere, which ESO
    loads instead of it. gru skips those, as updating them would install a standalone copy that already exists."""
    return addon.parent is not None and addon.is_superseded


def update_pending(addon) -> bool:
    """Whether an installed addon has an update that may be applied: outdated, not version-locked nor moot."""
    return addon.can_update and not addon.locked and not update_moot(addon)


def match_candidates(addon) -> list:
    """The online addons an installed folder could be, when several of them share its dir -- whether or not
    addons.csv already records which one it is."""
    try:
        get_state().api.dir(addon.dir)
    except AmbiguousDirectory as err:
        return err.candidates
    except FileNotFoundError:
        pass
    return []


def ambiguous_candidates(addon) -> list:
    """The online addons an installed folder could be, when its dir matches several of them and nothing recorded
    in addons.csv says which. gru leaves such folders unmatched: never updated, and saved with no link."""
    return [] if addon.infos is not None else match_candidates(addon)


def ranked_candidates(addon) -> list:
    """match_candidates(), best guess first -- the order `gru match` offers them in."""
    return rank_candidates(addon, match_candidates(addon), get_state().api, sortkey() or 'downloads')


def set_match(addon, infos):
    """Record which online addon an installed folder is, as `gru match` does, persisted in addons.csv."""
    if addon.infos is not None:
        addon.infos.deregister(addon)
    addon.link(infos)
    get_state().local.export_state()


def set_locked(addon, locked: bool):
    """Pin or unpin an installed addon to its current version, persisted in addons.csv as the CLI does."""
    addon.locked = locked
    get_state().local.export_state()


def save_addon_patch(addon, api, local) -> int | None:
    """Diff `addon` against its unmodified ESOUI listing and save/update/remove its patch file to
    match. Returns the modified-file count (0 removes a stale patch), or None on failure (flashed)."""
    patch_dir = user_config(local.game)
    patch_dir.mkdir(exist_ok=True)
    try:
        out = io.StringIO()
        with local.unmodified_addon(addon.infos, api) as ref_addon:
            with warnings.catch_warnings(record=True, category=UserWarning) as caught:
                n = gru_patch.addon_diff(addon, ref_addon, out)
        for w in caught:
            flash_warning(str(w.message))
    except Exception as exc:
        flash_warning(f'Failed to check <b>{eso_colored(addon.title)}</b>: {exc}')
        return None

    patch_path = patch_dir / f'{addon.dir}.patch'
    if n > 0:
        patch_path.write_text(out.getvalue())
    elif patch_path.exists():
        patch_path.unlink()
    return n


def remove_vars_setting() -> str:
    """Whether removing an addon also deletes its SavedVariables: 'yes', 'no' or 'ask'."""
    setting = get_state().config.get(f'{GAME}.addons', 'remove_saved_variables')
    return setting if setting in {'yes', 'no', 'ask'} else 'ask'


@contextlib.contextmanager
def logged_changes():
    """Persist changes made to addons within the block, as the CLI does: save addons.csv, so the next
    scan keeps the link/lock of each install, and append a changes.csv row per changed version."""
    state = get_state()
    before = state.local.snapshot()
    try:
        yield
    finally:
        state.local.export_state()
        log_changes(state.local, state.config, before)
