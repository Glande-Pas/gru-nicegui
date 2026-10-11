# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Dialog importing an exported add-on list: pick a file, review the plan, apply."""

import warnings

from nicegui import run, ui

from gru_ui.components import global_progress, progress_factory
from gru_ui.importing import (Group, ImportFormatError, apply_import, choose_listing, parse_import, plan_import,
                              settle)
from gru_ui.state import flash_warning, flash_warnings, flash_summary, logged_changes, opt_deps, \
    rescan_async, sortkey
from gru_ui.utils import installed_item, si_suffixed, strip_eso_colors


async def _pick_listing(item):
    """Ask which of the item's candidate listings the folder is. Returns it, or None if dismissed."""
    key = sortkey() or 'downloads'
    ranked = sorted(item.candidates, key=lambda c: c.metadata.get(key) or 0, reverse=True)
    options = {i: '{title} {version} by {author} ({downloads} downloads)'.format(
        title=strip_eso_colors(c.title), version=c.version, author=strip_eso_colors(c.author),
        downloads=si_suffixed(c.metadata.get('downloads') or 0)) for i, c in enumerate(ranked)}
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
        ui.label('Several ESOUI.com add-ons install a {folder} folder. Which one should be installed?'.format(
            folder=item.dir))
        choice = ui.radio(options, value=0)
        with ui.row().classes('w-full justify-end'):
            ui.button('Cancel', on_click=lambda: dialog.submit(None))
            ui.button('Use this one', on_click=lambda: dialog.submit(choice.value))
    picked = await dialog
    dialog.delete()
    return ranked[picked] if picked is not None else None


def open_import_dialog(api, local, on_done):
    """Show the import dialog; `on_done()` runs after changes were applied."""
    items = []

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-3xl relative'):
        ui.button(icon='close', on_click=lambda: dialog.close()).props('flat round dense') \
          .classes('absolute top-2 right-2').style('color: inherit !important').tooltip('Close')
        ui.label('Import add-ons').classes('text-h6 pr-8')
        ui.label('Installs the listed add-ons that are missing, at their latest version. Locked ones keep their '
                 'listed version; unlock them below to get the latest instead. Nothing already installed is '
                 'changed or removed, except by a locked version newer than the installed one, which replaces it, '
                 'and folders you choose to switch over to another listing.').classes('text-caption')
        content = ui.column().classes('w-full gap-2')

    async def apply():
        chosen = [i for i in items if i.active]
        dialog.close()
        errors = []
        async with global_progress('Importing add-ons...') as pstate:
            progress = progress_factory(pstate)
            before = {a.dir for a in local.installed}

            def work():
                with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                    errors.extend(apply_import(chosen, api, local, opt_deps(), progress=progress))
                return caught

            caught = await run.io_bound(work)
        flash_warnings(caught)
        await rescan_async()
        flash_summary('Installed', [installed_item(a.title or a.dir, a.version)
                                    for a in sorted(local.installed, key=lambda a: (a.title or a.dir).lower())
                                    if a.dir not in before])
        flash_summary('Failed', [strip_eso_colors(e) for e in errors], flash_warning)
        on_done()

    @ui.refreshable
    def plan_view():
        for group in Group:
            rows = [i for i in items if i.section is group]
            if not rows:
                continue
            opened = group in (Group.INSTALL, Group.UNAVAILABLE, Group.LOCK, Group.SWITCH, Group.MATCH,
                               Group.INCORRECT)
            with ui.expansion('{label} ({count})'.format(label=group.value, count=len(rows)),
                              value=opened).classes('w-full'):
                for item in rows:
                    with ui.row().classes('w-full items-center no-wrap'):
                        if item.selectable:
                            def on_select(e, item=item):
                                item.selected = e.value
                                settle(item)
                                plan_view.refresh()
                            box = ui.checkbox(value=item.selected, on_change=on_select)
                            if item.replace_candidate:
                                box.tooltip('Install the newer locked version. Unticked keeps the installed version '
                                            'and locks it')
                        with ui.column().classes('flex-grow min-w-0 gap-0'):
                            ui.label(item.title if item.group is not Group.INVALID
                                     else 'Line {line}'.format(line=item.line))
                            ui.label(item.note).classes('text-caption')
                        if item.candidates:
                            async def on_choose(item=item):
                                info = await _pick_listing(item)
                                if info is not None:
                                    await run.io_bound(choose_listing, item, info, api, local)
                                    plan_view.refresh()
                            ui.button('Choose…', on_click=on_choose).classes('shrink-0') \
                              .tooltip('Pick which ESOUI.com add-on this folder is, to install it')
                        if item.in_file_locked and item.group in (Group.INSTALL, Group.UNAVAILABLE, Group.LOCK,
                                                                  Group.SWITCH):
                            def on_lock(e, item=item):
                                item.locked = e.value
                                settle(item)
                                plan_view.refresh()
                            ui.switch('Locked', value=item.locked, on_change=on_lock).classes('shrink-0')
        count = sum(1 for i in items if i.active)
        with ui.row().classes('w-full justify-end'):
            ui.button('Cancel', on_click=dialog.close)
            ui.button('Import {count} add-on(s)'.format(count=count), on_click=apply).set_enabled(count > 0)

    async def handle_upload(e):
        content.clear()
        with content:
            ui.spinner('dots', size='lg')
        try:
            parsed = parse_import(await e.file.read())
        except ImportFormatError as err:
            flash_warning(str(err))
            content.clear()
            with content:
                show_upload()
            return
        await run.io_bound(plan_import, parsed, api, local)
        items[:] = parsed
        content.clear()
        with content:
            if items:
                plan_view()
            else:
                ui.label('The file lists no add-ons.')

    def show_upload():
        ui.upload(label='Drop an exported add-on list (.csv) or browse', on_upload=handle_upload, auto_upload=True,
                  max_file_size=1_000_000).props('accept=.csv').classes('w-full')

    with content:
        show_upload()
    dialog.open()
