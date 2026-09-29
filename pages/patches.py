# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Patches page: browse saved addon patches."""

import io
import pathlib
import sys
import traceback
import warnings

from nicegui import run, ui

from gru import patch as gru_patch
from gru.patch import PatchError
from gru.config import user_config, encoding_open
from gru_ui import shell
from gru_ui.state import get_state, flash_warning, flash_info, logged_changes, rescan, diff_addon_patch
from gru_ui.utils import eso_colored
from gru_ui.components import global_progress, progress_factory


def _diff_content_equal(a: str, b: str) -> bool:
    """Compare two patch texts ignoring their Date/mtime header noise, which differs on every scan."""
    return gru_patch.parse_diff(io.StringIO(a)) == gru_patch.parse_diff(io.StringIO(b))


def _patch_status(addon, patch_path: pathlib.Path) -> str | None:
    """Whether `patch_path`'s changes are already present in `addon`'s files (read-only)"""
    try:
        with patch_path.open() as f:
            patch = gru_patch.parse_diff(f)
    except Exception:
        return None

    applied = True
    for (infile, outfile), changes in patch.items():
        if str(infile) == '/dev/null':
            outpath = addon.folder.joinpath(*outfile.parts[1:])
            if not outpath.exists():
                applied = False
            else:
                with encoding_open(outpath) as f:
                    if not gru_patch.is_patch_applied(f.read(), changes):
                        return 'conflict'
            continue
        if str(outfile) == '/dev/null':
            if addon.folder.joinpath(*infile.parts[1:]).exists():
                applied = False
            continue

        try:
            with encoding_open(addon.folder.joinpath(*infile.parts[1:])) as f:
                current = f.read()
        except FileNotFoundError:
            return 'conflict'
        if gru_patch.is_patch_applied(current, changes):
            continue
        applied = False
        try:
            _, values = gru_patch.apply_patch(current, changes)
        except Exception:
            return 'conflict'
        if not all(values):
            return 'conflict'
    return 'applied' if applied else 'pending'


async def _do_revert(addon, api, local, refresh):
    """Reinstall `addon` fresh from its matched ESOUI listing, discarding local changes."""
    title = addon.title
    async with global_progress(f'Reverting {title}...') as state:
        progress = progress_factory(state)

        def work():
            with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                local.unpack(addon.infos, api, path=addon.folder, progress=progress)
            return caught

        caught = await run.io_bound(work)
    for w in caught:
        flash_warning(str(w.message))
    rescan()
    flash_info(f'Reverted: <b>{eso_colored(title)}</b> to the installed ESOUI version')
    refresh()


def _open_confirm_partial_apply(addon, patch_path, result, refresh, commit_to=None):
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
        ui.html(f"<b>{eso_colored(addon.title)}</b>'s current files don't match what the patch expects "
                '— nothing was changed, the saved patch is unchanged.')
        for f in result.files:
            if f.failed:
                ui.label(f'- {f.path}: {", ".join(f.failed)}')
        ui.label("You can apply everything that still matches and save the rest next to the add-on's own "
                 'files as .rej, for manual reconciliation — or cancel and fix the patch first.') \
          .classes('text-caption')

        def apply_partial():
            try:
                partial_result = gru_patch.addon_patch_file(addon, patch_path, partial=True)
            except PatchError as exc:
                if commit_to is not None:
                    patch_path.unlink(missing_ok=True)
                dialog.close()
                flash_warning(f'Patch is invalid: {exc}')
                return

            if commit_to is not None:
                patch_path.replace(commit_to)
            dialog.close()
            applied = [f for f in partial_result.files if f.applied]
            rejects = [f for f in partial_result.files if f.reject]
            if applied:
                flash_info(f'Applied {len(applied)}/{len(partial_result.files)} file(s) for '
                           f'<b>{eso_colored(addon.title)}</b>.')
            else:
                flash_warning(f'No changes could be applied to <b>{eso_colored(addon.title)}</b>.')
            if rejects:
                reject_list = '<br/>'.join(f'<code>{f.reject}</code>' for f in rejects)
                flash_warning('Some hunks failed and were saved for manual reconciliation:<br/>'
                              f'{reject_list}<br/>The saved patch itself is unchanged — reinstalling this '
                              'add-on from the Installed Add-Ons page will discard these changes.')
            refresh()

        def cancel():
            if commit_to is not None:
                patch_path.unlink(missing_ok=True)
            dialog.close()

        with ui.row().classes('w-full'):
            ui.button('🔧 Apply what can be applied', on_click=apply_partial).classes('flex-grow')
            ui.button('Cancel', on_click=cancel).classes('flex-grow')
    dialog.open()


def _try_apply_patch(addon, patch_path: pathlib.Path, refresh, commit_to: pathlib.Path | None = None):
    """Apply the patch, offering a partial-apply dialog on conflict."""
    try:
        result = gru_patch.addon_patch_file(addon, patch_path)
    except PatchError as exc:
        if commit_to is not None:
            patch_path.unlink(missing_ok=True)
        flash_warning(f'Patch is invalid: {exc}')
        return

    if not result.files:
        if commit_to is not None:
            patch_path.unlink(missing_ok=True)
        flash_info('No changes to apply in patch.')
        refresh()
    elif result.backed_out:
        _open_confirm_partial_apply(addon, patch_path, result, refresh, commit_to=commit_to)
    else:
        if commit_to is not None:
            patch_path.replace(commit_to)
        flash_info(f'Applied patch successfully to <b>{eso_colored(addon.title)}</b>.')
        refresh()


@ui.page('/patches')
def patches_page():
    shell.frame('/patches')
    state = get_state()
    local = state.local
    api = state.api

    ui.label('Patches').classes('text-h4')
    ui.label('Save your local changes to addons to re-apply them after updates.').classes('text-caption')

    if local is None:
        ui.label('No addons directory configured. Go to Settings to set it up.').classes('text-warning')
        return

    patch_dir = user_config(local.game)
    upload_state = {'last_name': None}

    @ui.refreshable
    def body():
        patches = sorted(patch_dir.glob('*.patch')) if patch_dir.exists() else []

        async def confirm_squash(addon, action: str) -> bool:
            with ui.dialog() as confirm, ui.card():
                ui.html(f'The saved patch for <b>{eso_colored(addon.title)}</b> differs from what '
                        'scanning just found.')
                with ui.row().classes('w-full'):
                    ui.button(f'✅ {action}', on_click=lambda: confirm.submit(True)).classes('flex-grow')
                    ui.button('⏭️ Skip', on_click=lambda: confirm.submit(False)).classes('flex-grow')
            return bool(await confirm)

        async def scan_and_save():
            linked = [a for a in local.installed if a.infos is not None and a.folder.parent == local.root]
            if not linked:
                flash_warning('No addons linked to the API — try refreshing first.')
                return

            with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
                ui.label('Saving changes as patches…').classes('text-h6')
                log = ui.log(max_lines=50).classes('w-full h-48')
            dialog.open()

            n_saved = 0
            for addon in linked:
                log.push(f'Checking {addon.title}…')
                try:
                    n, text, messages = await run.io_bound(diff_addon_patch, addon, api, local)
                except Exception as exc:
                    print(f'Skipping {addon.dir}: failed to check for local changes', file=sys.stderr)
                    traceback.print_exc()
                    log.push(f'Skipped {addon.title}: {exc}')
                    continue
                for message in messages:
                    flash_warning(message)
                new_text = text if n > 0 else None

                patch_path = patch_dir / f'{addon.dir}.patch'
                existing = patch_path.read_text() if patch_path.exists() else None
                if existing == new_text or (existing is not None and new_text is not None and
                                            _diff_content_equal(existing, new_text)):
                    continue

                if existing is not None:
                    if new_text is None:
                        action = 'Remove'
                    elif _patch_status(addon, patch_path) == 'applied':
                        action = 'Update'
                    else:
                        action = 'Replace'
                    if not await confirm_squash(addon, action):
                        log.push(f'Skipped {addon.title}.')
                        continue

                if new_text is not None:
                    patch_dir.mkdir(exist_ok=True)
                    patch_path.write_text(new_text)
                    flash_info(f'Saved patch for <b>{eso_colored(addon.title)}</b> ({n} modified file(s))')
                    n_saved += 1
                else:
                    patch_path.unlink(missing_ok=True)
            dialog.close()
            flash_info(f'Done — {n_saved} patch(es) saved.')
            body.refresh()

        with ui.row().classes('w-full items-center gap-2'):
            ui.button('💾 Scan and Save', on_click=scan_and_save)
            if patches:
                ui.label(f'{len(patches)} patch(es) in {patch_dir}').classes('text-caption')

        async def handle_upload(e):
            if e.file.name == upload_state['last_name']:
                return
            upload_state['last_name'] = e.file.name
            text = await e.file.text()
            addon_dir = pathlib.Path(e.file.name).stem
            addon = next((a for a in local.installed if a.dir == addon_dir), None)

            if addon is None:
                flash_warning(f'No installed addon found matching <b>{addon_dir}</b>.')
                return

            patch_dir.mkdir(exist_ok=True)
            staging_path = patch_dir / f'{addon_dir}.patch.upload'
            staging_path.write_text(text)
            _try_apply_patch(addon, staging_path, body.refresh, commit_to=patch_dir / f'{addon_dir}.patch')

        ui.upload(label='Import a patch — drag & drop or browse', on_upload=handle_upload,
                  auto_upload=True).props('accept=.patch').classes('w-full')

        if not patches:
            ui.label('No saved patches found.')
            return

        for patch_file in patches:
            text = patch_file.read_text(errors='replace')

            header = {}
            body_start = 0
            for i, line in enumerate(text.splitlines()):
                if line.startswith('---'):
                    body_start = i
                    break
                if ': ' in line:
                    k, _, val = line.partition(': ')
                    header[k.strip()] = val.strip()

            addon_name = header.get('Addon', patch_file.stem)
            version = header.get('Version', '?')
            date = header.get('Date', '?')
            diff_body = '\n'.join(text.splitlines()[body_start:])
            n_files = sum(1 for line in diff_body.splitlines() if line.startswith('--- '))

            addon = next((a for a in local.installed if a.dir == patch_file.stem), None)
            pstatus = _patch_status(addon, patch_file) if addon else None
            status_suffix = {
                'applied': '  ·  ✅ Already applied',
                'conflict': "  ·  ⚠️ Doesn't match current files",
            }.get(pstatus, '')

            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center gap-2'):
                    ui.html(f'<b>{eso_colored(addon_name)}</b> — v{version}  ·  {date}  ·  '
                            f'{n_files} file(s) modified{status_suffix}').classes('flex-grow')

                    if pstatus == 'applied':
                        revert_btn = ui.button(
                            '↩️ Revert',
                            on_click=lambda a=addon, pf=patch_file: _do_revert(a, api, local, body.refresh))
                        revert_btn.set_enabled(addon.infos is not None)
                        revert_btn.tooltip('Reinstalls from ESOUI, discarding these changes -- not a '
                                           'hunk-by-hunk undo' if addon.infos else
                                           "Add-on isn't matched to an ESOUI listing")
                    else:
                        apply_btn = ui.button(
                            '▶️ Apply',
                            on_click=lambda a=addon, pf=patch_file: _try_apply_patch(a, pf, body.refresh))
                        apply_btn.set_enabled(addon is not None)
                        if addon is None:
                            apply_btn.tooltip("Add-on isn't installed")

                    ui.button('⬇️ Download',
                              on_click=lambda t=text, n=patch_file.name: ui.download(t.encode(), n))

                    def delete(pf=patch_file):
                        pf.unlink()
                        body.refresh()

                    ui.button('🗑️ Delete', on_click=delete)

                with ui.expansion('Show diff'):
                    ui.code(diff_body, language='diff').classes('w-full')

    body()
