# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Installed add-ons page."""

import io
import warnings
from collections import defaultdict

from nicegui import run, ui

from gru_ui import shell
from gru_ui.state import (get_state, rescan_async, refresh_api, opt_deps, patch_updates, flash_summary,
                          flash_warnings, remove_vars_setting, logged_changes, update_pending, ambiguous_candidates,
                          poll_ambiguous_resolution)
from gru_ui.components import addon_card, progress_factory, global_progress, open_choose_match
from gru_ui.utils import bold, strip_eso_colors, anchor_id, fuzzy_score, installed_item, updated_item


async def _do_remove_unused(local, remove_vars):
    before = {a.dir: a.title for a in local.installed}

    def work():
        with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
            local.remove_unused_deps(opt=opt_deps(), remove_vars=remove_vars)
        return caught

    async with global_progress('Removing unused add-ons...'):
        caught = await run.io_bound(work)
        await rescan_async()
    flash_warnings(caught)
    after = {a.dir for a in local.installed}
    flash_summary('Removed', [bold(before[dir_] or dir_)
                              for dir_ in sorted(before.keys() - after, key=lambda d: (before[d] or d).lower())])


def _open_confirm_remove_unused(local, with_vars, refresh):
    with ui.dialog() as dialog, ui.card():
        ui.label('Also delete the saved variables of:')
        checks = {addon.folder: ui.checkbox(addon.title or addon.dir) for addon in with_vars}
        ui.label('Libraries that become unused as a result of this removal keep their saved variables.') \
          .classes('text-caption')

        async def confirm():
            chosen = {folder for folder, box in checks.items() if box.value}
            dialog.close()
            await _do_remove_unused(local, lambda addon: addon.folder in chosen)
            refresh()

        ui.button('🧹 Remove unused', on_click=confirm).tooltip('Remove the unused libraries')
    dialog.open()


def _warning_banner(addons, heading: str):
    """A dismissable warning box listing `addons`, linking to their cards. `heading` takes a {count}."""
    if not addons:
        return
    lines = [f'- [{strip_eso_colors(a.title) or a.dir}](#{anchor_id(a.dir)})'
             for a in sorted(addons, key=lambda a: (a.title or a.dir).lower())]
    with ui.element('div').classes('relative w-full bg-warning/20 border border-warning rounded p-2') as banner:
        ui.markdown('**{heading}**\n'.format(heading=heading.format(count=len(addons))) + '\n'.join(lines)).classes('pr-6')
        ui.icon('close').classes('cursor-pointer absolute top-2 right-2').on('click', banner.delete)


@shell.page('/')
def installed_page():
    state = get_state()
    api = state.api
    local = state.local

    ui.label('Installed Add-Ons').classes('text-h4')

    if local is None:
        ui.label('No addons directory configured. Go to Settings to set it up.').classes('text-warning')
        return

    filter_state = {'term': '', 'kind': 'all', 'libs': 'all'}

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
        unused = local.unused_deps(installed, opt=opt_deps())
        missing = local.missing_deps(installed, opt=opt_deps())

        async def offer_matching():
            for i, addon in enumerate(ambiguous, 1):
                if addon.infos is None:
                    context = ("Update all: add-on {index}/{total} can't be updated until matched. "
                               'Close this dialog to skip it.').format(index=i, total=len(ambiguous))
                    await open_choose_match(addon, lambda: None, context)

        async def update_all():
            if ambiguous:
                await offer_matching()
            before = {a.folder: (a.title, a.version) for a in local.installed}
            async with global_progress('Updating add-ons...') as pstate:
                progress = progress_factory(pstate)

                def work():
                    with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                        local.update(api, opt=opt_deps(), deps=True, patch=patch_updates(), progress=progress)
                    return caught

                caught = await run.io_bound(work)
            flash_warnings(caught)
            await rescan_async()
            after = {a.folder: (a.title, a.version) for a in local.installed}
            installed_now, updated = [], []
            for folder, (title, v_after) in sorted(after.items(), key=lambda x: x[1][0].lower()):
                if folder not in before:
                    installed_now.append(installed_item(title, v_after))
                elif before[folder][1] != v_after:
                    updated.append(updated_item(title, before[folder][1], v_after))
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
            await rescan_async()
            flash_summary('Installed', [installed_item(a.title or a.dir, a.version)
                                        for a in sorted(local.installed, key=lambda a: (a.title or a.dir).lower())
                                        if a.dir not in before])
            body.refresh()

        async def remove_unused():
            setting = remove_vars_setting()
            with_vars = [a for a in local.unused_deps(installed, opt=opt_deps()) if local.saved_variable_files(a)]
            if setting == 'ask' and with_vars:
                _open_confirm_remove_unused(local, with_vars, body.refresh)
            else:
                await _do_remove_unused(local, lambda addon: setting == 'yes')
                body.refresh()

        def export_list():
            out = io.StringIO()
            local.write_csv(out)
            ui.download(out.getvalue().encode(), 'addons.csv', 'text/csv')

        async def refresh_all():
            await run.io_bound(refresh_api)
            body.refresh()

        with ui.row().classes('w-full items-center gap-2'):
            summary = ['{installed} addon(s) installed, {updates} update(s) available.'
                       .format(installed=len(installed), updates=len(can_update))]
            if locked:
                summary.append('{count} version locked.'.format(count=len(locked)))
            if ambiguous:
                summary.append('{count} matching several ESOUI add-ons.'.format(count=len(ambiguous)))
            ui.label(' '.join(summary)).classes('text-caption flex-grow min-w-0')
            with ui.row().classes('gap-2 shrink-0 no-wrap'):
                ui.button('⬆️ Update all', on_click=update_all) \
                  .tooltip('Update every add-on with a newer ESOUI version (locked ones are skipped), '
                           'and install their missing dependencies').set_enabled(bool(can_update or ambiguous))
                ui.button('⬇️ Install missing', on_click=install_missing) \
                  .tooltip('Install dependencies that installed add-ons require but are not present.') \
                  .set_enabled(bool(missing))
                ui.button('🧹 Remove unused', on_click=remove_unused) \
                  .tooltip('Remove libraries that no installed add-on depends on.').set_enabled(bool(unused))
                ui.button('🔄 Refresh', on_click=refresh_all) \
                  .tooltip('Re-fetch the ESOUI add-on list and rescan the add-ons folder')
                ui.button('📤 Export', on_click=export_list).tooltip('Download the list of installed add-ons')

        not_found = [a for a in unmatched if a not in ambiguous]
        _warning_banner(ambiguous, '{count} add-on(s) match several ESOUI add-ons — pick the right one on each card:')
        _warning_banner(not_found, "{count} add-on(s) weren't found on ESOUI and can't be updated:")

        def refresh_list():
            addon_list.refresh(filter_state['term'], filter_state['kind'], filter_state['libs'])

        def set_filter(key):
            def handler(e):
                filter_state[key] = e.value or ('' if key == 'term' else 'all')
                refresh_list()
            return handler

        toggle_props = ('no-caps dense color=toggle-bg text-color=toggle-fg '
                        'toggle-color=primary toggle-text-color=button-fg')
        with ui.row().classes('w-full items-center no-wrap'):
            ui.input('Filter', placeholder='Filter installed add-ons…', value=filter_state['term'],
                     on_change=set_filter('term')).classes('flex-grow')
            ui.toggle({'all': 'All', 'outdated': 'Updateable', 'unused': 'Unused'}, value=filter_state['kind'],
                      on_change=set_filter('kind')).props(toggle_props)
            ui.toggle({'all': 'Both', 'libs': 'Libraries', 'addons': 'Add-ons'}, value=filter_state['libs'],
                      on_change=set_filter('libs')).props(toggle_props)
        ui.separator()

        @ui.refreshable
        def addon_list(term: str, kind: str, libs: str):
            children_map = defaultdict(list)
            for a in installed:
                if a.parent is not None:
                    children_map[a.parent].append(a)

            standalone = [a for a in installed if a.parent is None]
            if kind != 'all':
                matching = set(can_update if kind == 'outdated' else unused)
                standalone = [a for a in standalone if a in matching]
            def is_lib(a):
                return getattr(a, 'is_lib', False) is True

            if libs == 'addons':
                standalone = [a for a in standalone if not is_lib(a)]
            # Active filters narrow bundles down to their matching members
            narrowing = bool(term) or libs == 'libs'

            def own_ok(a):
                return (not term or fuzzy_score(term, a.title or a.dir) is not None) and (libs != 'libs' or is_lib(a))

            def child_ok(c):
                return (not term or fuzzy_score(term, c.title or c.dir) is not None) and (libs != 'libs' or is_lib(c))

            matching_children = {a: [c for c in children_map[a] if child_ok(c)] for a in standalone} \
                if narrowing else {}
            if narrowing:
                standalone = [a for a in standalone if own_ok(a) or matching_children[a]]
            scores = {}
            if term:
                for a in standalone:
                    candidates = [fuzzy_score(term, x.title or x.dir) for x in [a, *matching_children[a]]]
                    scores[a] = min(c for c in candidates if c is not None)

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
                # When filtering, how well the title matches comes first
                return (scores.get(a, ()), prio, (a.title or a.dir).lower())

            if not standalone:
                if kind == 'unused' and libs == 'addons':
                    ui.label('Only libraries can be marked as unused').classes('text-caption')
                    return
                ui.label({
                    ('all', 'all'): 'No addons to show',
                    ('all', 'libs'): 'No library addons to show',
                    ('all', 'addons'): 'No non-library addons to show',
                    ('outdated', 'all'): 'No out-of-date addons to show',
                    ('outdated', 'libs'): 'No out-of-date library addons to show',
                    ('outdated', 'addons'): 'No out-of-date non-library addons to show',
                    ('unused', 'all'): 'No unused addons to show',
                    ('unused', 'libs'): 'No unused library addons to show',
                }[kind, libs]).classes('text-caption')
                return

            for addon in sorted(standalone, key=_sort_key):
                children = children_map.get(addon, [])
                children_label = None
                if narrowing:
                    children_label = '{matching}/{total} bundled addon(s) match'.format(matching=len(matching_children[addon]),
                                                                                    total=len(children))
                    children = matching_children[addon]
                addon_card(addon, api, local, body.refresh, children=children or None, children_label=children_label,
                           dimmed=narrowing and not own_ok(addon), expanded=narrowing)

        addon_list(filter_state['term'], filter_state['kind'], filter_state['libs'])

    body()
    async def poll():
        if await poll_ambiguous_resolution():
            body.refresh()

    ui.timer(2.0, poll)
