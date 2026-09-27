# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Reusable addon card component and the install/remove/update actions behind its buttons."""

import contextlib
import functools
import warnings
import webbrowser

from nicegui import run, ui

from gru.addon import InstalledAddon, AddonInfo

from .utils import si_suffixed, load_icon, eso_colored, strip_eso_colors, anchor_id
from .state import (get_state, opt_deps, rescan, flash_warning, flash_info, remove_vars_setting,
                    logged_changes, update_pending, update_moot, set_locked, ambiguous_candidates,
                    ranked_candidates, set_match, save_addon_patch)
from .themes import get_theme, DEFAULT_THEME


def external_link(inner_html: str, url: str, style: str = '') -> None:
    """A link that opens in the system browser, not the native app window (no back/close there)."""
    ui.html(f'<a style="cursor:pointer;{style}">{inner_html}</a>').on('click', lambda: webbrowser.open(url))


class _ProgressState:
    def __init__(self, message: str):
        self.message = message
        self.size = 0
        self.done = 0
        self.frac: float | None = None


@contextlib.asynccontextmanager
async def global_progress(label: str):
    """A floating progress card pinned to a corner of the page."""
    state = _ProgressState(label)
    with ui.card().classes('fixed bottom-4 right-4 z-[9999] w-96 shadow-lg gap-1') as card:
        label_el = ui.label(label)
        bar = ui.linear_progress(value=0, show_value=False)

    def tick():
        label_el.set_text(f'{state.message} {state.frac:.0%}' if state.frac is not None else state.message)
        bar.set_value(state.frac or 0)
        bar.props(f'indeterminate={"true" if state.frac is None else "false"}')

    timer = ui.timer(0.15, tick)
    try:
        yield state
    finally:
        timer.deactivate()
        card.delete()


def progress_factory(state: _ProgressState):
    """A gru ProgressFactory (size, message) -> ProgressProtocol that updates `state`."""
    def factory(size, message):
        return _StepProgress(state, size, message)
    return factory


class _StepProgress:
    def __init__(self, state: _ProgressState, size: int, message: str):
        self.state = state
        state.message = message
        state.size = size
        state.done = 0
        state.frac = 0.0 if size else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, size: int):
        self.state.done += size
        self.state.frac = min(self.state.done / self.state.size, 1.0) if self.state.size else None


def _category_label(api, category_id: int) -> str:
    try:
        return ' > '.join(api.cat_name_hierarchy(category_id))
    except Exception:
        return str(category_id)


@functools.lru_cache(maxsize=256)
def _cached_icon(icon_url: str):
    return load_icon(icon_url)


def _category_icon(api, category_id: int):
    try:
        url = api.cat(category_id)['icon']
        return _cached_icon(url)
    except Exception:
        return None


def _bold_diff_suffix(current: str, upstream: str) -> str:
    """Return upstream with the first character that differs from current bolded to end."""
    for i, (a, b) in enumerate(zip(current, upstream)):
        if a != b:
            return upstream[:i] + f'<b>{upstream[i:]}</b>'
    common = min(len(current), len(upstream))
    return upstream[:common] + f'<b>{upstream[common:]}</b>'


def _metadata_rows(addon, api, local) -> list[tuple]:
    """Return (label, value, span) triples for display."""
    is_installed = isinstance(addon, InstalledAddon)
    is_embedded = is_installed and local is not None and addon.folder.parent != local.root

    if is_installed:
        infos = addon.infos
        meta = infos.metadata if infos else {}
        version = addon.version
        upstream_version = infos.version if infos else None
    else:
        meta = addon.metadata
        version = addon.version
        upstream_version = None

    date = meta.get('date')
    category = meta.get('category')
    downloads = meta.get('downloads')
    monthly = meta.get('monthly')
    favorites = meta.get('favorites')

    if is_installed and addon.locked:
        version_str = f'{version} 🔒' + (f' (latest: {upstream_version})' if addon.can_update else '')
    elif upstream_version and addon.can_update and not update_moot(addon):
        version_str = version + ' → ' + _bold_diff_suffix(version, upstream_version)
    else:
        version_str = version

    if is_embedded:
        return [
            ('Author',    eso_colored(addon.author) if addon.author else '?', 2),
            ('Version',   version_str,                                         2),
            ('Directory', str(addon.folder),                                   4),
        ]

    rows = [
        ('Author',    eso_colored(addon.author) if addon.author else '?', 2),
        ('Version',   version_str,                                         1),
        ('Updated',   date.strftime('%x') if date else '?',               1),
        ('Category',  _category_label(api, category) if category else '?', 2),
        ('Downloads', f'{si_suffixed(downloads)} ({si_suffixed(monthly)}/mo)' if downloads else '?', 1),
        ('Favorites', si_suffixed(favorites) if favorites else '?',        1),
    ]

    if is_installed:
        rows.append(('Directory', str(addon.folder), 4))

    return rows


def _render_meta_grid(addon, api, local):
    cells = ''.join(
        f'<div class="gru-meta-cell" style="grid-column:span {span}">'
        f'<span class="gru-meta-lbl">{lbl}</span>'
        f'<span class="{"gru-meta-nowrap" if lbl == "Directory" else ""}">{val}</span></div>'
        for lbl, val, span in _metadata_rows(addon, api, local)
    )
    ui.html(
        f'<div style="display:grid; grid-template-columns:repeat(4,1fr); width:100%;'
        f' gap:0.3rem 0.75rem; font-size:0.85em;">'
        f'{cells}</div>'
    ).classes('w-full')


def addon_card(addon, api, local, refresh, children: list | None = None):
    """Render a single addon as a card with action buttons."""
    is_installed = isinstance(addon, InstalledAddon)
    has_id = getattr(addon, 'id', None) is not None
    can_update = update_pending(addon) if has_id and is_installed else False
    is_locked = is_installed and addon.locked
    is_lib = getattr(addon, 'is_lib', False) is True
    unused = is_lib and is_installed and local is not None and local.depcount(addon) == 0
    is_embedded = is_installed and local is not None and addon.folder.parent != local.root

    title = eso_colored(addon.title) if addon.title else ''
    link = (addon.infos.metadata.get('link') if is_installed and addon.infos else None) or \
           (addon.metadata.get('link') if not is_installed else None)

    candidates = ambiguous_candidates(addon) if is_installed else []

    installed_copies = ([a for a in local.installed if getattr(a, 'id', None) == addon.id]
                        if not is_installed and has_id and local is not None else [])
    ambiguous_copies = ([a for a in local.installed if a.infos is None and
                         any(c.id == addon.id for c in ambiguous_candidates(a))]
                        if not is_installed and has_id and local is not None else [])
    already_installed = bool(installed_copies)
    locked_copy = any(a.locked for a in installed_copies + ambiguous_copies)

    has_missing = (is_installed and not is_embedded and local is not None and
                   bool(local.missing_deps([addon])))

    status = ''
    if is_installed and has_missing:
        status = '❌ Missing dependencies'
    elif candidates:
        status = f'❓ Matches {len(candidates)} ESOUI add-ons' + (', 🔒 version locked' if is_locked else '')
    elif is_installed and can_update and addon.parent is not None:
        status = '🔄 Update available as a standalone library'
    elif is_installed and can_update:
        status = '🔄 Update available'
    elif is_locked:
        status = '🔒 Version locked' + (', update available' if addon.can_update and not update_moot(addon) else '')
    elif is_installed and unused:
        status = '⚠️ Unused library'
    elif ambiguous_copies:
        status = '❓ Possibly installed' + (', 🔒 version locked' if locked_copy else '')
    elif locked_copy:
        status = '✅ Installed, 🔒 version locked'
    elif already_installed:
        status = '✅ Installed'

    if is_installed and addon.infos is not None and len(addon.infos.folders) > 1 and addon.version_rank:
        rank = '🟢 active copy' if addon.version_rank == 'active' else '⚪ superseded copy'
        status = f'{status}, {rank}' if status else rank

    status_span = (
        f' <span style="display:inline-block; font-size:0.85em; font-weight:600; opacity:0.75">{status}</span>'
        if status else ''
    )
    anchor = f' id="{anchor_id(addon.dir)}"' if is_installed and addon.parent is None else ''
    theme = get_theme(get_state().config.get('app', 'theme', fallback=DEFAULT_THEME))
    title_bg, title_fg, title_border = (
        ('rgba(151,166,195,0.15)', 'inherit', 'rgba(151,166,195,0.25)') if theme['dark']
        else (theme['secondary'], '#e8e8e8', 'rgba(255,255,255,0.12)')
    )
    title_html = (
        f'<div{anchor} style="background:{title_bg}; color:{title_fg};'
        f'             padding:0.35rem 0.6rem; margin:-1rem -1rem 0.75rem;'
        f'             border-radius:6px 6px 0 0;'
        f'             border-bottom:1px solid {title_border};">'
        f'  <span style="display:inline-block; font-size:1.25em; font-weight:600">{title}</span>'
        f'  {status_span}'
        f'</div>'
    )

    with ui.card().classes('w-full gap-2'):
        ui.html(title_html)

        with ui.row().classes('w-full items-start no-wrap gap-4'):
            if not is_embedded:
                category = (addon.infos.metadata if is_installed and addon.infos else
                            addon.metadata if not is_installed else {}).get('category')
                icon_path = _category_icon(api, category) if category else None
                if icon_path:
                    ui.image(str(icon_path)).classes('w-10 h-10 shrink-0')

            with ui.column().classes('flex-grow gap-1 min-w-0'):
                _render_meta_grid(addon, api, local)

            if not is_embedded:
                with ui.column().classes('items-end shrink-0'):
                    if link:
                        external_link('🔗 ESOUI page', link, style='font-size:0.85em')
                    elif candidates:
                        ui.html('<span style="font-size:0.85em">Could be any of:</span>')
                        for c in candidates:
                            external_link(f'🔗 {eso_colored(c.title)}', c.metadata['link'])
                    else:
                        ui.html('<span style="display:inline-block;font-size:0.85em;padding:0.1rem 0.45rem;'
                                'background:rgba(255,171,0,0.15);border:1px solid rgba(255,171,0,0.4);'
                                'border-radius:0.4rem" title="No ESOUI add-on uses this folder name, so it '
                                'can\'t be updated.">⚠️ Not found on ESOUI</span>')

        with ui.row().classes('w-full justify-end gap-1'):
            if not is_installed and has_id:
                install_help = ('Unlock the installed version first' if locked_copy else
                                'Replaces the installed ' + ', '.join(
                                    str(a.folder.relative_to(local.root)) for a in ambiguous_copies)
                                + ' folder and records it as this add-on' if ambiguous_copies else None)
                btn = ui.button('⬇️ Install', on_click=lambda: _run_install(addon, api, local, refresh))
                btn.set_enabled(not locked_copy)
                if install_help:
                    btn.tooltip(install_help)

            if is_installed:
                ui.button('🗑️ Remove', on_click=lambda: _handle_remove(addon, local, refresh))

                if can_update:
                    label = '⬆️ Install standalone' if is_embedded else '⬆️ Update'
                    up_btn = ui.button(label, on_click=lambda: _run_update(addon, api, local, refresh))
                    if is_embedded:
                        up_btn.tooltip('Install the update as a top-level library, which ESO loads '
                                       'instead of this bundled copy')

                # Only offered while unmatched: once set (by hand or by auto-resolve), a match is
                # permanent -- remove the add-on and install the right one instead of changing it.
                if not is_embedded and candidates:
                    ui.button('🔗 Match ESOUI listing', on_click=lambda: _open_choose_match(addon, refresh)) \
                      .tooltip('Select which ESOUI add-on this folder is, which several share')

                if not is_embedded:
                    lock_label = '🔓 Unlock version' if is_locked else '🔒 Lock version'
                    lock_btn = ui.button(lock_label, on_click=lambda: _handle_lock(addon, is_locked, refresh))
                    if not is_locked:
                        lock_btn.tooltip('Pin to the installed version: skip it on updates')

                if not is_embedded:
                    save_btn = ui.button('💾 Save changes', on_click=lambda: _handle_save(addon, api, local, refresh))
                    save_btn.set_enabled(addon.infos is not None)
                    save_btn.tooltip('Save local changes as a patch, to re-apply after updates'
                                     if addon.infos else "Add-on isn't matched online")

        if children:
            for child in sorted(children, key=lambda a: a.title.lower()):
                addon_card(child, api, local, refresh)


def _handle_lock(addon, is_locked: bool, refresh):
    set_locked(addon, not is_locked)
    refresh()


def _handle_save(addon, api, local, refresh):
    n = save_addon_patch(addon, api, local)
    if n:
        flash_info(f'Saved patch for <b>{eso_colored(addon.title)}</b> ({n} modified file(s))')
    elif n == 0:
        flash_info(f'No local changes to save for <b>{eso_colored(addon.title)}</b>.')
    refresh()


def _handle_remove(addon: InstalledAddon, local, refresh):
    setting = remove_vars_setting()
    if setting == 'ask' and local.saved_variable_files(addon):
        _open_confirm_remove(addon, local, refresh)
    else:
        _do_remove(addon, local, remove_vars=setting == 'yes')
        refresh()


def _do_remove(addon: InstalledAddon, local, remove_vars: bool = False):
    title = addon.title or addon.dir
    with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
        local.remove(addon, remove_vars=remove_vars)
    for w in caught:
        flash_warning(str(w.message))
    rescan()
    flash_info(f'Removed: <b>{eso_colored(title)}</b>')


def _open_confirm_remove(addon: InstalledAddon, local, refresh):
    files = local.saved_variable_files(addon)
    with ui.dialog() as dialog, ui.card():
        ui.html(f'<b>{eso_colored(addon.title)}</b> has saved variables:')
        ui.code('\n'.join(str(path) for path in files))
        ui.label("Deleting them discards this add-on's settings and data for all characters.").classes('text-caption')

        def choose(delete: bool):
            dialog.close()
            _do_remove(addon, local, remove_vars=delete)
            refresh()

        with ui.row().classes('w-full'):
            ui.button('🗑️ Delete them too', on_click=lambda: choose(True)).classes('flex-grow')
            ui.button('💾 Keep them', on_click=lambda: choose(False)).classes('flex-grow')
    dialog.open()


async def _run_install(addon: AddonInfo, api, local, refresh):
    before = {a.dir for a in local.installed}
    async with global_progress(f'Installing {addon.title}...') as state:
        progress = progress_factory(state)

        def work():
            with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                installed = list(local.unpack(addon, api, progress=progress))
                local.install_deps(installed, api, opt=opt_deps(), progress=progress)
            return caught

        caught = await run.io_bound(work)
    for w in caught:
        flash_warning(str(w.message))
    rescan()
    for a in sorted(local.installed, key=lambda a: (a.title or a.dir).lower()):
        if a.dir not in before:
            flash_info(f'Installed: <b>{eso_colored(a.title or a.dir)}</b> {a.version}')
    refresh()


async def _run_update(addon: InstalledAddon, api, local, refresh):
    if addon.locked:
        flash_warning(f'<b>{eso_colored(addon.title)}</b> is version locked, not updating.')
        return
    if addon.infos is None:
        flash_warning(f'<b>{eso_colored(addon.title)}</b> is not matched to a single ESOUI add-on, not updating.')
        return
    if update_moot(addon):
        flash_warning(f'<b>{eso_colored(addon.title)}</b> is superseded by a newer copy, not updating.')
        return

    before = {a.folder: (a.title, a.version) for a in local.installed}
    async with global_progress(f'Updating {addon.title}...') as state:
        progress = progress_factory(state)
        path = addon.folder if addon.parent is None else None

        def work():
            with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                updated = list(local.unpack(addon.infos, api, path=path, progress=progress))
                local.install_deps(updated, api, opt=opt_deps(), progress=progress)
            return caught

        caught = await run.io_bound(work)
    for w in caught:
        flash_warning(str(w.message))
    rescan()
    after = {a.folder: (a.title, a.version) for a in local.installed}
    for folder, (title, v_after) in sorted(after.items(), key=lambda x: x[1][0].lower()):
        if folder not in before:
            flash_info(f'Installed: <b>{eso_colored(title)}</b> {v_after}')
        elif before[folder][1] != v_after:
            flash_info(f'Updated: <b>{eso_colored(title)}</b> {before[folder][1]} → {v_after}')
    refresh()


def _open_choose_match(addon: InstalledAddon, refresh):
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
        ui.html(f'Several ESOUI add-ons install a <code>{addon.dir}</code> folder. Which one is '
                f'<b>{eso_colored(addon.title)}</b> {addon.version} by {eso_colored(addon.author or "?")}?')
        spinner = ui.spinner('dots', size='lg')
        content = ui.column().classes('w-full gap-2')
    dialog.open()

    async def load():
        ranked = await run.io_bound(ranked_candidates, addon)
        spinner.delete()

        def label(candidate):
            guess = ' — best guess' if candidate is ranked[0] else ''
            current = ' — current match' if candidate is addon.infos else ''
            return (f'{strip_eso_colors(candidate.title)} {candidate.version} by '
                    f'{strip_eso_colors(candidate.author)} '
                    f'({si_suffixed(candidate.metadata.get("downloads") or 0)} downloads){guess}{current}')

        with content:
            current_index = next((i for i, c in enumerate(ranked) if c is addon.infos), 0)
            picked_box = {'value': ranked[current_index]}
            link_html = ui.html('')
            link_html.on('click', lambda: webbrowser.open(picked_box['value'].metadata['link']))

            def show_link():
                link_html.set_content('<a style="cursor:pointer">🔗 View it on ESOUI</a>')

            def on_pick(e):
                picked_box['value'] = ranked[e.value] if isinstance(e.value, int) else e.value
                show_link()
                confirm_btn.set_enabled(picked_box['value'] is not addon.infos)

            radio_options = {i: label(c) for i, c in enumerate(ranked)}
            ui.radio(radio_options, value=current_index, on_change=on_pick)
            show_link()

            def confirm():
                set_match(addon, picked_box['value'])
                dialog.close()
                refresh()

            confirm_btn = ui.button('✅ Confirm', on_click=confirm)
            confirm_btn.set_enabled(picked_box['value'] is not addon.infos)

    ui.timer(0.01, load, once=True)
