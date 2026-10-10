# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Reusable addon card component and the install/remove/update actions behind its buttons."""

import contextlib
import html
import pathlib
import warnings
import webbrowser

from nicegui import run, ui

from gru.addon import AddonBundle, InstalledAddon, AddonInfo

from .utils import open_folder, si_suffixed, eso_colored, strip_eso_colors, anchor_id, bold, code, \
    installed_item, updated_item
from .state import (opt_deps, rescan_async, flash_warning, flash_info, flash_summary, flash_warnings,
                    remove_vars_setting, patches_enabled, logged_changes, update_pending, update_moot, set_locked,
                    ambiguous_candidates, ranked_candidates, set_match, save_addon_patch, search_for,
                    dependency_search_term)


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
    with ui.context.client.content, \
            ui.card().classes('fixed bottom-4 right-4 z-[9999] w-96 shadow-lg gap-1') as card:
        label_el = ui.label(label)
        bar = ui.linear_progress(value=0, show_value=False)
        timer = ui.timer(0.15, lambda: tick())

    def tick():
        label_el.set_text('{message} {fraction:.0%}'.format(message=state.message, fraction=state.frac)
                          if state.frac is not None else state.message)
        bar.set_value(state.frac or 0)
        bar.props(f'indeterminate={"true" if state.frac is None else "false"}')

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


def _category_icon(api, category_id: int) -> str | None:
    """The category's remote icon URL, fetched by the browser."""
    try:
        return api.cat(category_id)['icon'] or None
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
        version_str = ('{version} 🔒 (latest: {latest})' if addon.can_update else '{version} 🔒') \
            .format(version=version, latest=upstream_version)
    elif upstream_version and addon.can_update and not update_moot(addon):
        version_str = version + ' → ' + _bold_diff_suffix(version, upstream_version)
    else:
        version_str = version

    if is_embedded:
        return [
            ('Author',    eso_colored(addon.author) if addon.author else '?', 2),
            ('Version',   version_str,                                         2),
            ('Directory', addon.folder,                                        4),
        ]

    rows = [
        ('Author',    eso_colored(addon.author) if addon.author else '?', 2),
        ('Version',   version_str,                                         1),
        ('Updated',   date.strftime('%x') if date else '?',               1),
        ('Category',  _category_label(api, category) if category else '?', 2),
        ('Downloads', '{total} ({monthly}/mo)'.format(total=si_suffixed(downloads), monthly=si_suffixed(monthly))
                      if downloads else '?', 1),
        ('Favorites', si_suffixed(favorites) if favorites else '?',        1),
    ]

    if is_installed:
        rows.append(('Directory', addon.folder, 4))

    return rows


def _render_meta_grid(addon, api, local):
    def value(val):
        if not isinstance(val, pathlib.Path):
            return f'<span>{val}</span>'
        path = html.escape(str(val), quote=True)
        return f'<span class="gru-meta-nowrap"><a data-path="{path}" style="cursor:pointer">{path}</a></span>'

    cells = ''.join(
        f'<div class="gru-meta-cell" style="grid-column:span {span}">'
        f'<span class="gru-meta-lbl">{lbl}</span>{value(val)}</div>'
        for lbl, val, span in _metadata_rows(addon, api, local)
    )
    ui.html(
        f'<div style="display:grid; grid-template-columns:repeat(4,1fr); width:100%;'
        f' gap:0.3rem 0.75rem; font-size:0.85em;">'
        f'{cells}</div>'
    ).classes('w-full').on(
        'click', lambda e: open_folder(e.args), js_handler='(e) => {'
        ' const a = e.target.closest("[data-path]"); if (a) emit(a.dataset.path); }')


def _dependency_link(dep, addon, local, optional: bool) -> None:
    """One dependency: linked to its card on Installed Add-Ons if installed, else to a search for it.
    The game ignores versions of optional dependencies, so any installed copy counts for those. """
    if optional:
        found = next((a for a in local.dir(dep.dir) if not isinstance(a, AddonBundle)), None)
    else:
        found = local.find_installed(dep)
    if found is None:
        ui.html(f'<a style="cursor:pointer">{"➕" if optional else "❌"} {dep.dir}</a>').on(
            'click', lambda: search_for(dependency_search_term(dep.dir))).tooltip(
                'Not installed, but optional: search ESOUI for it' if optional else
                'Missing, and needed: search ESOUI for it')
        return
    top, own_top = found, addon
    while top.parent is not None:
        top = top.parent
    while own_top.parent is not None:
        own_top = own_top.parent
    updatable = update_pending(found)
    mark = '🔄' if updatable else '✅'
    if top is own_top:
        ui.html(f'<span>{mark} {dep.dir}</span>').tooltip(
            'Bundled with this add-on, update available' if updatable else 'Bundled with this add-on')
    else:
        ui.html(f'<a href="#{anchor_id(top.dir)}">{mark} {dep.dir}</a>').tooltip(
            'Installed, update available: go to its card' if updatable else 'Installed: go to its card')


def _render_dependencies(addon, local, dimmed: bool) -> None:
    for label, deps, optional in (('Requires', addon.deps, False), ('Works with', addon.optdeps, True)):
        if not deps:
            continue
        with ui.row().classes('w-full items-baseline gap-x-2 gap-y-0' + (' opacity-50' if dimmed else '')) \
                .style('font-size:0.85em'):
            ui.html(f'<span class="gru-meta-lbl">{label}</span>').tooltip(
                'Needed by this add-on: it will not load if any of them is missing' if not optional else
                'Optional extras: this add-on uses them when installed, but works fine without them')
            for dep in deps:
                _dependency_link(dep, addon, local, optional)


def addon_card(addon, api, local, refresh, children: list | None = None, children_label: str | None = None,
               dimmed: bool = False, expanded: bool = False, on_lock_change=None):
    """Render a single addon as a card with action buttons. When filtering, `children` holds only the matching
    bundled addons with `children_label` as their dropdown text, `dimmed` greys out the card itself and `expanded`
    opens the dropdown. `on_lock_change` is called after locking or unlocking, which only refreshes this card."""
    @ui.refreshable
    def card():
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
            status = ('❓ Matches {count} ESOUI add-ons, 🔒 version locked' if is_locked else
                      '❓ Matches {count} ESOUI add-ons').format(count=len(candidates))
        elif is_installed and can_update and addon.parent is not None:
            status = '🔄 Update available as a standalone library'
        elif is_installed and can_update:
            status = '🔄 Update available'
        elif is_locked:
            status = ('🔒 Version locked, update available' if addon.can_update and not update_moot(addon) else
                      '🔒 Version locked')
        elif is_installed and unused:
            status = '⚠️ Unused library'
        elif ambiguous_copies:
            status = '❓ Possibly installed, 🔒 version locked' if locked_copy else '❓ Possibly installed'
        elif locked_copy:
            status = '✅ Installed, 🔒 version locked'
        elif already_installed:
            status = '✅ Installed'

        if is_installed and addon.infos is not None and len(addon.infos.folders) > 1 and addon.version_rank:
            rank = '🟢 active copy' if addon.version_rank == 'active' else '⚪ superseded copy'
            status = '{status}, {rank}'.format(status=status, rank=rank) if status else rank

        status_span = (
            f' <span style="display:inline-block; font-size:0.85em; font-weight:600; opacity:0.75">{status}</span>'
            if status else ''
        )
        anchor = f' id="{anchor_id(addon.dir)}"' if is_installed and addon.parent is None else ''
        title_html = (
            f'<div{anchor} class="gru-card-title">'
            f'  <span style="display:inline-block; font-size:1.25em; font-weight:600">{title}</span>'
            f'  {status_span}'
            f'</div>'
        )

        with ui.card().classes('w-full gap-2'):
            dim = ' opacity-50' if dimmed else ''
            ui.html(title_html).classes(dim)

            with ui.row().classes('w-full items-start no-wrap gap-4' + dim):
                if not is_embedded:
                    category = (addon.infos.metadata if is_installed and addon.infos else
                                addon.metadata if not is_installed else {}).get('category')
                    icon_url = _category_icon(api, category) if category else None
                    if icon_url:
                        ui.image(icon_url).classes('w-10 h-10 shrink-0')

                with ui.column().classes('flex-grow gap-1 min-w-0'):
                    _render_meta_grid(addon, api, local)

                if not is_embedded:
                    with ui.column().classes('items-end shrink-0'):
                        if link:
                            external_link('🔗 ESOUI page', link, style='font-size:0.85em')
                        elif candidates:
                            ui.html('<span style="font-size:0.85em">Could be any of:</span>')
                            for c in candidates:
                                external_link('🔗 {title}'.format(title=eso_colored(c.title)), c.metadata['link'])
                        else:
                            ui.html('<span class="gru-badge-warn" title="No ESOUI add-on uses this folder name, so it '
                                    'can\'t be updated.">⚠️ Not found on ESOUI</span>')

            if is_installed and local is not None:
                _render_dependencies(addon, local, dimmed)

            with ui.row().classes('w-full justify-end gap-1' + dim):
                if not is_installed and has_id:
                    install_help = ('Unlock the installed version first' if locked_copy else
                                    'Replaces the installed ' + ', '.join(
                                        str(a.folder.relative_to(local.root)) for a in ambiguous_copies)
                                    + ' folder and records it as this add-on' if ambiguous_copies else None)
                    btn = ui.button('⬇️ Install', on_click=lambda: _run_install(addon, api, local, refresh))
                    btn.set_enabled(not locked_copy)
                    btn.tooltip(install_help or 'Download this add-on from ESOUI into your add-ons folder')

                if is_installed:
                    ui.button('🗑️ Remove', on_click=lambda: _handle_remove(addon, local, refresh)) \
                      .tooltip("Delete this add-on's folder, including any add-ons bundled inside it")

                    if can_update:
                        label = '⬆️ Install standalone' if is_embedded else '⬆️ Update'
                        up_btn = ui.button(label, on_click=lambda: _run_update(addon, api, local, refresh))
                        up_btn.tooltip('Install the update as a standalone library add-on' if is_embedded else
                                       'Update to the latest ESOUI version')

                    # Only offered while unmatched: once set (by hand or by auto-resolve), a match is
                    # permanent -- remove the add-on and install the right one instead of changing it.
                    if not is_embedded and candidates:
                        ui.button('🔗 Match ESOUI listing', on_click=lambda: open_choose_match(addon, refresh)) \
                          .tooltip('Select which ESOUI add-on this folder is, which several share')

                    if not is_embedded:
                        lock_label = '🔓 Unlock version' if is_locked else '🔒 Lock version'
                        lock_btn = ui.button(
                            lock_label,
                            on_click=lambda: _handle_lock(addon, is_locked, card.refresh, on_lock_change))
                        lock_btn.tooltip('Allow updates for this add-on again' if is_locked else
                                         'Pin to the installed version: skip updates')

                    if not is_embedded and patches_enabled():
                        save_btn = ui.button('💾 Save changes', on_click=lambda: _handle_save(addon, api, local, card.refresh))
                        save_btn.set_enabled(addon.infos is not None)
                        save_btn.tooltip('Save local changes as a patch, to re-apply after updates'
                                         if addon.infos else "Add-on isn't matched online")

            if children:
                with ui.expansion(children_label or '{count} bundled addon(s)'.format(count=len(children)), icon='expand_more',
                                  value=expanded).classes('w-full'):
                    for child in sorted(children, key=lambda a: a.title.lower()):
                        addon_card(child, api, local, refresh, on_lock_change=on_lock_change)

    card()


async def _handle_lock(addon, is_locked: bool, refresh_card, on_change=None):
    await set_locked(addon, not is_locked)
    refresh_card()
    if on_change is not None:
        on_change()


async def _handle_save(addon, api, local, refresh):
    try:
        async with global_progress('Checking {title}...'.format(title=addon.title)):
            n, messages = await run.io_bound(save_addon_patch, addon, api, local)
    except Exception as exc:
        flash_warning('Failed to check {title}: {error}'.format(title=bold(addon.title), error=exc))
        return
    for message in messages:
        flash_warning(message)
    if n:
        flash_info('Saved patch for {title} ({count} modified file(s))'.format(title=bold(addon.title), count=n))
    elif n == 0:
        flash_info('No local changes to save for {title}.'.format(title=bold(addon.title)))
    refresh()


async def _handle_remove(addon: InstalledAddon, local, refresh):
    setting = remove_vars_setting()
    if setting == 'ask' and local.saved_variable_files(addon):
        _open_confirm_remove(addon, local, refresh)
    else:
        await _do_remove(addon, local, remove_vars=setting == 'yes')
        refresh()


async def _do_remove(addon: InstalledAddon, local, remove_vars: bool = False):
    title = addon.title or addon.dir

    def work():
        with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
            local.remove(addon, remove_vars=remove_vars)
        return caught

    async with global_progress('Removing {title}...'.format(title=title)):
        caught = await run.io_bound(work)
        await rescan_async()
    flash_warnings(caught)
    flash_info('Removed: {title}'.format(title=bold(title)))


def _open_confirm_remove(addon: InstalledAddon, local, refresh):
    files = local.saved_variable_files(addon)
    with ui.dialog() as dialog, ui.card():
        ui.html('{title} has saved variables:'.format(title=bold(addon.title)))
        ui.code('\n'.join(str(path) for path in files))
        ui.label("Deleting them discards this add-on's settings and data for all characters.").classes('text-caption')

        async def choose(delete: bool):
            dialog.close()
            await _do_remove(addon, local, remove_vars=delete)
            refresh()

        with ui.row().classes('w-full'):
            ui.button('🗑️ Delete them too', on_click=lambda: choose(True)).classes('flex-grow') \
              .tooltip('Remove the add-on and its saved variables')
            ui.button('💾 Keep them', on_click=lambda: choose(False)).classes('flex-grow') \
              .tooltip('Remove the add-on but keep its saved variables')
    dialog.open()


async def _run_install(addon: AddonInfo, api, local, refresh):
    before = {a.dir for a in local.installed}
    async with global_progress('Installing {title}...'.format(title=addon.title)) as state:
        progress = progress_factory(state)

        def work():
            with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                installed = list(local.unpack(addon, api, progress=progress))
                local.install_deps(installed, api, opt=opt_deps(), progress=progress)
            return caught

        caught = await run.io_bound(work)
    flash_warnings(caught)
    await rescan_async()
    flash_summary('Installed', [installed_item(a.title or a.dir, a.version)
                                for a in sorted(local.installed, key=lambda a: (a.title or a.dir).lower())
                                if a.dir not in before])
    refresh()


async def _run_update(addon: InstalledAddon, api, local, refresh):
    if addon.locked:
        flash_warning('{title} is version locked, not updating.'.format(title=bold(addon.title)))
        return
    if addon.infos is None:
        flash_warning('{title} is not matched to a single ESOUI add-on, not updating.'.format(title=bold(addon.title)))
        return
    if update_moot(addon):
        flash_warning('{title} is superseded by a newer copy, not updating.'.format(title=bold(addon.title)))
        return

    before = {a.folder: (a.title, a.version) for a in local.installed}
    async with global_progress('Updating {title}...'.format(title=addon.title)) as state:
        progress = progress_factory(state)
        path = addon.folder if addon.parent is None else None

        def work():
            with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                updated = list(local.unpack(addon.infos, api, path=path, progress=progress))
                local.install_deps(updated, api, opt=opt_deps(), progress=progress)
            return caught

        caught = await run.io_bound(work)
    flash_warnings(caught)
    await rescan_async()
    after = {a.folder: (a.title, a.version) for a in local.installed}
    installed, updated = [], []
    for folder, (title, v_after) in sorted(after.items(), key=lambda x: x[1][0].lower()):
        if folder not in before:
            installed.append(installed_item(title, v_after))
        elif before[folder][1] != v_after:
            updated.append(updated_item(title, before[folder][1], v_after))
    flash_summary('Installed', installed)
    flash_summary('Updated', updated)
    refresh()


def open_choose_match(addon: InstalledAddon, refresh, context: str | None = None):
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
        if context:
            ui.label(context).classes('text-caption')
        ui.html('Several ESOUI add-ons install a {folder} folder. Which one is {title} {version} by {author}?'
                .format(folder=code(addon.dir), title=bold(addon.title), version=addon.version,
                        author=eso_colored(addon.author or '?')))
        spinner = ui.spinner('dots', size='lg')
        content = ui.column().classes('w-full gap-2')
    dialog.open()

    async def load():
        ranked = await run.io_bound(ranked_candidates, addon)
        spinner.delete()

        def label(candidate):
            text = '{title} {version} by {author} ({downloads} downloads)'.format(
                title=strip_eso_colors(candidate.title), version=candidate.version,
                author=strip_eso_colors(candidate.author),
                downloads=si_suffixed(candidate.metadata.get('downloads') or 0))
            if candidate is ranked[0]:
                text = '{text} — best guess'.format(text=text)
            if candidate is addon.infos:
                text = '{text} — current match'.format(text=text)
            return text

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

            async def confirm():
                await set_match(addon, picked_box['value'])
                dialog.submit(True)
                refresh()

            confirm_btn = ui.button('✅ Confirm', on_click=confirm) \
                .tooltip('Use the selected ESOUI listing for this folder')
            confirm_btn.set_enabled(picked_box['value'] is not addon.infos)

    ui.timer(0.01, load, once=True)
    return dialog
