"""Settings page."""

import pathlib
import tkinter
import tkinter.filedialog

from nicegui import ui

from gru.config import save_config
from gru_ui import shell
from gru_ui.state import get_state, set_addons_root, GAME, flash_info
from gru_ui.themes import THEMES, DEFAULT_THEME


def _browse_directory() -> str | None:
    root = tkinter.Tk()
    root.withdraw()
    root.wm_attributes('-topmost', True)
    selected = tkinter.filedialog.askdirectory(parent=root, title='Select ESO addons directory')
    root.destroy()
    return selected or None


@ui.refreshable
def _addons_directory():
    state = get_state()
    current_root = state.config.get(f'{GAME}.addons', 'root') or '(not set)'
    ui.label(f'Current: {current_root}')

    with ui.row().classes('items-center w-full'):
        path_input = ui.input('Path', value='' if current_root == '(not set)' else current_root).classes('flex-grow')

        def browse():
            selected = _browse_directory()
            if selected:
                path_input.set_value(selected)

        ui.button('📂 Browse…', on_click=browse)

    def apply_directory():
        path = pathlib.Path(path_input.value or '')
        if not path.exists() or not path.is_dir():
            ui.notify(f'Directory not found: {path}', type='negative')
            return
        set_addons_root(path)
        flash_info(f'Addons directory set to {path}')
        _addons_directory.refresh()

    ui.button('✅ Apply directory', on_click=apply_directory)


@ui.page('/settings')
def settings_page():
    shell.frame('/settings')
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
    ui.label('Addons directory').classes('text-h6 mt-4')
    _addons_directory()

    ui.separator()
    ui.label('Optional dependencies').classes('text-h6')
    opt = config.getboolean(f'{GAME}.addons', 'optional')

    def on_opt_change(e):
        config.set(f'{GAME}.addons', 'optional', 'on' if e.value else 'off')
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.switch('Include optional dependencies', value=opt, on_change=on_opt_change)

    ui.separator()
    ui.label('Search sort order').classes('text-h6')
    sort_options = ['downloads', 'monthly', 'favorites']
    current_sort = config.get(f'{GAME}.addons', 'sortkey')

    def on_sort_change(e):
        config.set(f'{GAME}.addons', 'sortkey', e.value)
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.select(sort_options, value=current_sort if current_sort in sort_options else sort_options[0],
              label='Sort search results by', on_change=on_sort_change)

    ui.separator()
    ui.label('Patches').classes('text-h6')
    patch = config.getboolean(f'{GAME}.addons', 'patch_updates')

    def on_patch_change(e):
        config.set(f'{GAME}.addons', 'patch_updates', 'on' if e.value else 'off')
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.switch('Re-apply patches automatically on update', value=patch, on_change=on_patch_change)

    ui.separator()
    ui.label('Saved variables').classes('text-h6')
    vars_options = {'ask': 'Ask each time', 'yes': 'Always delete them', 'no': 'Always keep them'}
    current_vars = config.get(f'{GAME}.addons', 'remove_saved_variables')

    def on_vars_change(e):
        config.set(f'{GAME}.addons', 'remove_saved_variables', e.value)
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.select(vars_options, value=current_vars if current_vars in vars_options else 'ask',
              label='When removing an add-on, its saved variables should be', on_change=on_vars_change)

    ui.separator()
    ui.label('Change log').classes('text-h6')
    log_lines = config.getint(f'{GAME}.addons', 'log_lines')

    def on_log_lines_change(e):
        config.set(f'{GAME}.addons', 'log_lines', str(int(e.value)))
        save_config(config)
        ui.notify('Saved.', type='positive')

    ui.number('Number of installs, updates and removals to keep in the log', value=log_lines, min=0, step=10,
              on_change=on_log_lines_change)
