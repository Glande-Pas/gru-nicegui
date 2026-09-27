# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Recent changes page: installs, updates and removals logged to changes.csv."""

import datetime

from nicegui import ui

from gru.app import read_changes, NOT_INSTALLED
from gru_ui import shell
from gru_ui.components import external_link
from gru_ui.state import get_state, GAME


def _date(value: str):
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def _change(entry) -> str:
    if entry.version == NOT_INSTALLED:
        return '🗑️ Removed'
    elif entry.previous_state == NOT_INSTALLED:
        return '⬇️ Installed'
    return '⬆️ Updated'


@ui.page('/changes')
def changes_page():
    shell.frame('/changes')
    state = get_state()
    local = state.local

    ui.label('Recent Changes').classes('text-h4')

    if local is None:
        ui.label('No addons directory configured. Go to Settings to set it up.').classes('text-warning')
        return

    changes = read_changes(local)
    log_lines = state.config.getint(f'{GAME}.addons', 'log_lines')
    ui.label(f'The last {log_lines} changes are kept, which can be changed in Settings.').classes('text-caption')

    if not changes:
        ui.label('No changes recorded yet.')
        return

    rows = [{
        'date': _date(entry.date),
        'addon': entry.dir,
        'change': _change(entry),
        'from': '' if entry.previous_state == NOT_INSTALLED else entry.previous_state,
        'to': '' if entry.version == NOT_INSTALLED else entry.version,
        'link': entry.link or None,
    } for entry in reversed(changes)]

    kinds = ['⬇️ Installed', '⬆️ Updated', '🗑️ Removed']
    kind_state = {k: True for k in kinds}

    @ui.refreshable
    def table():
        active = {k for k, v in kind_state.items() if v}
        visible = [r for r in rows if r['change'] in active]
        with ui.column().classes('w-full gap-0'):
            with ui.row().classes('w-full font-bold border-b pb-1'):
                ui.label('Date').classes('w-40')
                ui.label('Add-on').classes('w-52')
                ui.label('Change').classes('w-28')
                ui.label('From').classes('w-24')
                ui.label('To').classes('w-24')
                ui.label('ESOUI').classes('w-20')
            for r in visible:
                with ui.row().classes('w-full items-center py-1 border-b border-white/10'):
                    ui.label(r['date'].strftime('%Y-%m-%d %H:%M') if r['date'] else '?').classes('w-40')
                    ui.label(r['addon']).classes('w-52')
                    ui.label(r['change']).classes('w-28')
                    ui.label(r['from']).classes('w-24')
                    ui.label(r['to']).classes('w-24')
                    with ui.element('div').classes('w-20'):
                        if r['link']:
                            external_link('🔗 page', r['link'])

    def on_toggle(k, value):
        kind_state[k] = value
        table.refresh()

    with ui.row():
        for k in kinds:
            ui.checkbox(k, value=True, on_change=lambda e, k=k: on_toggle(k, e.value))

    table()
