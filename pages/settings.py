# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Settings page."""

import pathlib

import webview
from nicegui import app, run, ui

from gru.config import root_key, save_config
from gru_ui import autostart, shell, tray
from gru_ui.state import get_state, set_addons_root, GAME, flash_info, CARD_DETAILS, card_detail, set_card_detail, \
    update_by_date, set_update_by_date
from gru_ui.components import action_button
from gru_ui.utils import open_folder
from gru_ui.themes import THEMES, DEFAULT_THEME


async def _browse_directory(start: str) -> str | None:
    selected = await app.native.main_window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
    return selected[0] if selected else None


@ui.refreshable
def _addons_directory(target: str):
    state = get_state()
    current_root = state.config.get(f'{GAME}.addons', root_key(target)) or None
    with ui.row().classes('items-center gap-1'):
        ui.label('Current:')
        current = ui.label(current_root or '(not set)')
        if current_root:
            current.classes('cursor-pointer underline').tooltip('Open in the file explorer')
            current.on('click', lambda: open_folder(current_root))

    with ui.row().classes('items-center w-full'):
        path_input = ui.input('Path', value=current_root or '').classes('flex-grow')

        async def browse():
            selected = await _browse_directory(path_input.value or '')
            if selected:
                path_input.set_value(selected)

        ui.button('📂 Browse…', on_click=browse).tooltip('Pick the add-ons folder in a file dialog')

    async def apply_directory():
        path = pathlib.Path(path_input.value or '')
        if not path.exists() or not path.is_dir():
            ui.notify('Directory not found: {path}'.format(path=path), type='negative')
            return
        had_target = state.target_available(target)
        await set_addons_root(path, target)
        if not had_target or target == state.target:
            ui.navigate.reload()
            return
        flash_info('{target} addons directory set to {path}'.format(target=target.upper(), path=path))
        _addons_directory.refresh()

    async def clear_directory():
        was_active = target == state.target
        await set_addons_root(None, target)
        if was_active:
            ui.navigate.reload()
        _addons_directory.refresh()

    with ui.row():
        action_button('✅ Apply directory', '⏳ Applying…', apply_directory).tooltip('Use this folder and rescan')
        if target != 'live':
            ui.button('🗑️ Clear', on_click=clear_directory).tooltip('Forget this folder')


@shell.page('/settings', needs_addons=False)
def settings_page():
    state = get_state()
    config = state.config

    ui.label('Settings').classes('text-h4')

    ui.label('Theme').classes('text-h6 mt-4')
    current_theme = config.get('app', 'theme', fallback=DEFAULT_THEME)

    def on_theme_change(e):
        config.set('app', 'theme', e.value)
        save_config(config)
        ui.navigate.reload()

    ui.select(list(THEMES), value=current_theme if current_theme in THEMES else DEFAULT_THEME,
              on_change=on_theme_change)

    ui.separator()
    ui.label('Live addons directory').classes('text-h6 mt-4')
    _addons_directory('live')
    ui.label('PTS addons directory (optional)').classes('text-h6 mt-4')
    _addons_directory('pts')

    ui.separator()
    ui.label('Updates').classes('text-h6')

    def on_auto_update_change(e):
        config.set('app', 'auto_update', 'on' if e.value else 'off')
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.switch('Update add-ons automatically on launch', value=config.getboolean('app', 'auto_update', fallback=False),
              on_change=on_auto_update_change) \
      .tooltip('Runs Update all once the installed list is shown. Add-ons matching several ESOUI.com listings are skipped')

    def on_by_date_change(e):
        set_update_by_date(e.value)
        ui.notify('Saved.', type='positive')
        ui.navigate.reload()

    ui.switch('Detect same-version updates', value=update_by_date(), on_change=on_by_date_change)
    ui.label('Some add-ons have been found to reuse the same visible version number across successive uploads. '
             'When the versions match, this option checks the installation date to detect that and offer the update. '
             'Turn it off if you get spurious updates due to other programs changing the file modification dates.'
             ).classes('text-caption')

    if tray.available():
        def on_tray_change(e):
            config.set('app', 'tray', 'on' if e.value else 'off')
            save_config(config)
            if e.value:
                tray.ensure_running()
            ui.notify('Saved.', type='positive')

        tray_switch = ui.switch('Show a tray icon with the number of updates', value=tray.enabled(config),
                                on_change=on_tray_change) \
          .tooltip('Checks for updates hourly in a small background process that outlives the window. '
                   'Some desktops (e.g. GNOME) need an extension to display tray icons')

        if autostart.supported():
            async def on_autostart_change(e):
                try:
                    await run.io_bound(autostart.set_enabled, e.value)
                except autostart.AutostartError as error:
                    ui.notify(str(error), type='negative')
                    autostart_switch.set_value(not e.value)
                    return
                ui.notify('Saved.', type='positive')

            autostart_switch = ui.switch('Start the tray icon at login', value=autostart.is_enabled(),
                                         on_change=on_autostart_change) \
                                 .bind_enabled_from(tray_switch, 'value')

    ui.separator()
    ui.label('Add-on cards').classes('text-h6')

    def on_detail_change(e):
        set_card_detail(e.value)
        ui.notify('Saved.', type='positive')

    ui.select(CARD_DETAILS, value=card_detail(), label='Detail level', on_change=on_detail_change) \
      .tooltip('Compact hides the dependency lines and the directory and API version. Standard shows what '
               'an add-on requires and, for libraries, what uses them. Full also shows optional dependencies, '
               'the directory and the API version. Also available on the Installed Add-Ons page.')

    ui.separator()
    ui.label('Search sort order').classes('text-h6')
    sort_options = {'downloads': 'Downloads', 'monthly': 'Monthly downloads', 'favorites': 'Favorites'}
    current_sort = config.get(f'{GAME}.addons', 'sortkey')

    def on_sort_change(e):
        config.set(f'{GAME}.addons', 'sortkey', e.value)
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.select(sort_options, value=current_sort if current_sort in sort_options else 'downloads',
              label='Sort search results by', on_change=on_sort_change).classes('w-full max-w-xl')

    def on_search_results_change(e):
        config.set('app', 'search_results', str(int(e.value or 20)))
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.number('Number of add-ons listed on the Search page', value=config.getint('app', 'search_results', fallback=20),
              min=1, max=200, step=5, precision=0, on_change=on_search_results_change).classes('w-full max-w-xl')

    ui.separator()
    ui.label('Patches').classes('text-h6')
    patches = config.getboolean('app', 'patches', fallback=False)
    patch = config.getboolean(f'{GAME}.addons', 'patch_updates')

    def on_patches_change(e):
        config.set('app', 'patches', 'on' if e.value else 'off')
        save_config(config)
        ui.navigate.reload()

    ui.switch('Advanced: keep local edits to add-ons as patches', value=patches, on_change=on_patches_change) \
      .tooltip('Shows the Patches page and a Save changes button on each add-on')

    def on_patch_change(e):
        config.set(f'{GAME}.addons', 'patch_updates', 'on' if e.value else 'off')
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.switch('Re-apply patches automatically on update', value=patch, on_change=on_patch_change) \
      .set_visibility(patches)

    ui.separator()
    ui.label('Saved variables').classes('text-h6')
    vars_options = {'ask': 'Ask each time', 'yes': 'Always delete them', 'no': 'Always keep them'}
    current_vars = config.get(f'{GAME}.addons', 'remove_saved_variables')

    def on_vars_change(e):
        config.set(f'{GAME}.addons', 'remove_saved_variables', e.value)
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.select(vars_options, value=current_vars if current_vars in vars_options else 'ask',
              label='When removing an add-on, its saved variables should be', on_change=on_vars_change) \
      .classes('w-full max-w-xl')

    ui.separator()
    ui.label('Change log').classes('text-h6')
    log_lines = config.getint(f'{GAME}.addons', 'log_lines')

    def on_log_lines_change(e):
        config.set(f'{GAME}.addons', 'log_lines', str(int(e.value)))
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.number('Number of installs, updates and removals to keep in the log', value=log_lines, min=0, step=10,
              on_change=on_log_lines_change).classes('w-full max-w-xl')
