# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Search page: find and install addons."""

from nicegui import run, ui

from gru_ui import shell
from gru_ui.state import get_state, sortkey, search_results, poll_ambiguous_resolution
from gru_ui.components import addon_card


@shell.page('/search')
async def search_page():
    state = get_state()
    api = state.api
    local = state.local

    ui.label('Search').classes('text-h4')

    if local is None:
        ui.label('No addons directory configured. Go to Settings to set it up.').classes('text-warning')
        return

    generation = 0
    labels = {'downloads': 'downloads', 'monthly': 'monthly downloads', 'favorites': 'favorites'}

    def popular() -> list:
        key = sortkey() or 'downloads'
        return sorted(api.addons.values(), key=lambda a: a.metadata.get(key) or 0, reverse=True)[:search_results()]

    @ui.refreshable
    async def results(term: str):
        nonlocal generation
        generation += 1
        mine = generation
        with ui.row().classes('items-center gap-2') as searching:
            ui.spinner()
            ui.label('Searching…')
        found = await run.io_bound(lambda: api.search(term, tiebreakattr=sortkey(), maxlen=search_results())
                                   if term else popular())
        if mine != generation:  # a newer search superseded this one
            return
        searching.delete()

        if not found:
            ui.label('No results found.')
            return

        heading = ('{count} result(s):'.format(count=len(found)) if term else
                   'Most popular add-ons by {key}:'.format(key=labels[sortkey() or 'downloads']))
        ui.label(heading).classes('text-caption')
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
    await results(search_state['term'])
    async def poll():
        if await poll_ambiguous_resolution():
            results.refresh(search_state['term'])

    ui.timer(2.0, poll)
