# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Installed add-ons page."""

import warnings
from collections import defaultdict

from nicegui import run, ui

from gru_ui import shell
from gru_ui.state import (get_state, rescan, opt_deps, patch_updates, flash_summary, flash_warnings,
                          remove_vars_setting, logged_changes, update_pending, ambiguous_candidates,
                          poll_ambiguous_resolution)
from gru_ui.components import addon_card, progress_factory, global_progress
from gru_ui.utils import eso_colored, strip_eso_colors, anchor_id, fuzzy_match


def _do_remove_unused(local, remove_vars):
    before = {a.dir: a.title for a in local.installed}
    with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
        local.remove_unused_deps(opt=opt_deps(), remove_vars=remove_vars)
    flash_warnings(caught)
    rescan()
    after = {a.dir for a in local.installed}
    flash_summary('Removed', [f'<b>{eso_colored(before[dir_] or dir_)}</b>'
                              for dir_ in sorted(before.keys() - after, key=lambda d: (before[d] or d).lower())])


def _open_confirm_remove_unused(local, with_vars, refresh):
    with ui.dialog() as dialog, ui.card():
        ui.label('Also delete the saved variables of:')
        checks = {addon.folder: ui.checkbox(addon.title or addon.dir) for addon in with_vars}
        ui.label('Libraries that become unused as a result of this removal keep their saved variables.') \
          .classes('text-caption')

        def confirm():
            chosen = {folder for folder, box in checks.items() if box.value}
            dialog.close()
            _do_remove_unused(local, lambda addon: addon.folder in chosen)
            refresh()

        ui.button('🧹 Remove unused', on_click=confirm)
    dialog.open()


def _warning_banner(addons, heading: str):
    """A dismissable warning box listing `addons`, linking to their cards."""
    if not addons:
        return
    lines = [f'- [{strip_eso_colors(a.title) or a.dir}](#{anchor_id(a.dir)})'
             for a in sorted(addons, key=lambda a: (a.title or a.dir).lower())]
    with ui.element('div').classes('relative w-full bg-warning/20 border border-warning rounded p-2') as banner:
        ui.markdown(f'**{len(addons)} {heading}**\n' + '\n'.join(lines)).classes('pr-6')
        ui.icon('close').classes('cursor-pointer absolute top-2 right-2').on('click', banner.delete)


@ui.page('/')
def installed_page():
    shell.frame('/')
    state = get_state()
    api = state.api
    local = state.local

    ui.label('Installed Add-Ons').classes('text-h4')

    if local is None:
        ui.label('No addons directory configured. Go to Settings to set it up.').classes('text-warning')
        return

    filter_state = {'term': ''}

    @ui.refreshable
    def body():
        installed = list(local.installed)

        if not installed:
            ui.label('No addons found in the configured directory.')
            return

        can_update = [a for a in installed if update_pending(a)]
        locked = [a for a in installed if a.locked and a.parent is None]
        ambiguous = [a for a in installed if a.parent is None and ambiguous_candidates(a)]
        unmatched = [a for a in installed if a.parent is None and a.infos is None]
        libs = [a for a in installed if getattr(a, 'is_lib', False) is True]
        unused = [a for a in libs if local.depcount(a) == 0]
        missing = local.missing_deps(installed, opt=opt_deps())

        async def update_all():
            before = {a.folder: (a.title, a.version) for a in local.installed}
            async with global_progress('Updating add-ons...') as pstate:
                progress = progress_factory(pstate)

                def work():
                    with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                        local.update(api, opt=opt_deps(), deps=True, patch=patch_updates(), progress=progress)
                    return caught

                caught = await run.io_bound(work)
            flash_warnings(caught)
            rescan()
            after = {a.folder: (a.title, a.version) for a in local.installed}
            installed_now, updated = [], []
            for folder, (title, v_after) in sorted(after.items(), key=lambda x: x[1][0].lower()):
                if folder not in before:
                    installed_now.append(f'<b>{eso_colored(title)}</b> {v_after}')
                elif before[folder][1] != v_after:
                    updated.append(f'<b>{eso_colored(title)}</b> {before[folder][1]} → {v_after}')
            flash_summary('Installed', installed_now)
            flash_summary('Updated', updated)
            body.refresh()

        async def install_missing():
            before = {a.dir for a in local.installed}
            async with global_progress('Installing missing dependencies...') as pstate:
                progress = progress_factory(pstate)

                def work():
                    with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                        local.install_deps(installed, api, opt=opt_deps(), progress=progress)
                    return caught

                caught = await run.io_bound(work)
            flash_warnings(caught)
            rescan()
            flash_summary('Installed', [f'<b>{eso_colored(a.title or a.dir)}</b> {a.version}'
                                        for a in sorted(local.installed, key=lambda a: (a.title or a.dir).lower())
                                        if a.dir not in before])
            body.refresh()

        def remove_unused():
            setting = remove_vars_setting()
            with_vars = [a for a in local.unused_deps(installed, opt=opt_deps()) if local.saved_variable_files(a)]
            if setting == 'ask' and with_vars:
                _open_confirm_remove_unused(local, with_vars, body.refresh)
            else:
                _do_remove_unused(local, lambda addon: setting == 'yes')
                body.refresh()

        def refresh_all():
            rescan()
            body.refresh()

        with ui.row().classes('w-full items-center gap-2'):
            locked_note = f' {len(locked)} version locked.' if locked else ''
            locked_note += f' {len(ambiguous)} matching several ESOUI add-ons.' if ambiguous else ''
            ui.label(f'{len(installed)} addon(s) installed, {len(can_update)} update(s) available.{locked_note}') \
              .classes('text-caption flex-grow min-w-0')
            with ui.row().classes('gap-2 shrink-0 no-wrap'):
                ui.button('⬆️ Update all', on_click=update_all).set_enabled(bool(can_update))
                ui.button('⬇️ Install missing', on_click=install_missing).set_enabled(bool(missing))
                ui.button('🧹 Remove unused', on_click=remove_unused).set_enabled(bool(unused))
                ui.button('🔄 Refresh', on_click=refresh_all)

        not_found = [a for a in unmatched if a not in ambiguous]
        _warning_banner(ambiguous, "add-on(s) match several ESOUI add-ons — pick the right one on each card:")
        _warning_banner(not_found, "add-on(s) weren't found on ESOUI and can't be updated:")

        def on_filter(e):
            filter_state['term'] = e.value or ''
            addon_list.refresh(filter_state['term'])

        ui.input('Filter', placeholder='Filter installed add-ons…', value=filter_state['term'],
                 on_change=on_filter).classes('w-full')
        ui.separator()

        @ui.refreshable
        def addon_list(term: str):
            children_map = defaultdict(list)
            for a in installed:
                if a.parent is not None:
                    children_map[a.parent].append(a)

            standalone = [a for a in installed if a.parent is None]
            if term:
                standalone = [a for a in standalone if fuzzy_match(term, a.title or '')]

            def _sort_key(a):
                is_lib = getattr(a, 'is_lib', False) is True
                if local.missing_deps([a]):
                    prio = 0
                elif update_pending(a) or a in ambiguous:
                    prio = 1
                elif not is_lib:
                    prio = 2
                elif local.depcount(a) > 0:
                    prio = 3
                else:
                    prio = 4
                return (prio, (a.title or a.dir).lower())

            for addon in sorted(standalone, key=_sort_key):
                children = children_map.get(addon)
                addon_card(addon, api, local, body.refresh, children=children or None)

        addon_list(filter_state['term'])

    body()
    ui.timer(2.0, lambda: body.refresh() if poll_ambiguous_resolution() else None)
