# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Search page: find and install addons."""

from nicegui import ui

from gru_ui import shell
from gru_ui.state import get_state, sortkey, poll_ambiguous_resolution
from gru_ui.components import addon_card


@shell.page('/search')
def search_page():
    state = get_state()
    api = state.api
    local = state.local

    ui.label('Search').classes('text-h4')

    if local is None:
        ui.label('No addons directory configured. Go to Settings to set it up.').classes('text-warning')
        return

    @ui.refreshable
    def results(term: str):
        if not term:
            return
        found = api.search(term, tiebreakattr=sortkey(), maxlen=20)

        if not found:
            ui.label('No results found.')
            return

        ui.label('{count} result(s):'.format(count=len(found))).classes('text-caption')
        ui.separator()
        for addon in found:
            addon_card(addon, api, local, lambda: results.refresh(term))

    search_state = {'term': state.pending_search}
    state.pending_search = ''

    def on_search(e):
        search_state['term'] = e.value or ''
        results.refresh(search_state['term'])

    ui.input('Search', placeholder='Search add-ons…', value=search_state['term'], on_change=on_search) \
      .props('debounce=300').classes('w-full')
    results(search_state['term'])
    ui.timer(2.0, lambda: results.refresh(search_state['term']) if poll_ambiguous_resolution() else None)
