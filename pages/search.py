# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Search page: find and install addons."""

import json

from nicegui import run, ui

from gru_ui import shell
from gru_ui.state import get_state, page_params, remember_params, sortkey, search_results, poll_ambiguous_resolution
from gru_ui.components import addon_card


@shell.page('/search')
async def search_page():
    state = get_state()
    api = state.api
    local = state.local

    ui.label('Search online').classes('text-h4')

    if local is None:
        ui.label('No addons directory configured. Go to Settings to set it up.').classes('text-warning')
        return

    generation = 0
    cards: dict = {}

    def refresh_cards(ids):
        for addon_id in ids:
            if addon_id in cards:
                cards[addon_id]()

    labels = {'downloads': 'downloads', 'monthly': 'monthly downloads', 'favorites': 'favorites'}

    def ancestors(cat_id: int) -> set[int]:
        seen, todo = set(), [cat_id]
        while todo:
            current = todo.pop()
            if current in seen or current not in api.categories:
                continue
            seen.add(current)
            todo.extend(api.categories[current]['parent_ids'])
        return seen

    def in_category(addon, cat_id: int) -> bool:
        own = addon.metadata.get('category')
        return own is not None and cat_id in ancestors(own)

    def popular(cat_id: int | None) -> list:
        key = sortkey() or 'downloads'
        pool = [a for a in api.addons.values() if not cat_id or in_category(a, cat_id)]
        return sorted(pool, key=lambda a: a.metadata.get(key) or 0, reverse=True)[:search_results()]

    def category_options() -> dict:
        used = {a.metadata.get('category') for a in api.addons.values()}
        shown = {c for u in used if u in api.categories for c in ancestors(u)}
        names = {c: ' > '.join(api.cat_name_hierarchy(c)) for c in shown}
        ordered = sorted(names.items(), key=lambda kv: kv[1].lower())
        return {0: 'All categories', **dict(ordered)}

    @ui.refreshable
    async def results(term: str, cat_id: int | None = None):
        nonlocal generation
        generation += 1
        mine = generation
        with ui.row().classes('items-center gap-2') as searching:
            ui.spinner()
            ui.label('Searching…')
        def lookup() -> list:
            if not term:
                return popular(cat_id)
            if not cat_id:
                return api.search(term, tiebreakattr=sortkey(), maxlen=search_results())
            hits = api.search(term, tiebreakattr=sortkey(), maxlen=len(api.addons))
            return [a for a in hits if in_category(a, cat_id)][:search_results()]

        found = await run.io_bound(lookup)
        if mine != generation:  # a newer search superseded this one
            return
        searching.delete()
        cards.clear()

        if not found:
            ui.label('No results found.')
            return

        heading = ('{count} result(s):'.format(count=len(found)) if term else
                   'Most popular add-ons by {key}:'.format(key=labels[sortkey() or 'downloads']))
        ui.label(heading).classes('text-caption')
        ui.separator()
        for addon in found:
            addon_card(addon, api, local, lambda: results.refresh(term, cat_id), registry=cards,
                       refresh_cards=refresh_cards)

    options = category_options()
    try:
        initial_cat = int(page_params().get('cat', 0))
    except (TypeError, ValueError):
        initial_cat = 0
    search_state = {'term': state.pending_search or page_params().get('q', ''),
                    'cat': initial_cat if initial_cat in options else 0}
    state.pending_search = ''
    if search_state['term']:  # after NiceGUI's own history push for this navigation, which sees the URL as already set
        ui.timer(0.3, lambda: remember_params('/search', search_params()), once=True)

    def search_params() -> dict:
        params = {'q': search_state['term']}
        if search_state['cat']:
            params['cat'] = str(search_state['cat'])
        return params

    def on_search(e):
        search_state['term'] = e.value or ''
        remember_params('/search', search_params())
        results.refresh(search_state['term'], search_state['cat'])

    def on_category(e):
        search_state['cat'] = e.value or 0
        remember_params('/search', search_params())
        results.refresh(search_state['term'], search_state['cat'])

    with ui.row().classes('w-full items-center no-wrap'):
        ui.input('Search', placeholder='Search add-ons…', value=search_state['term'], on_change=on_search) \
          .props('debounce=300 dense').classes('flex-grow')
        category_select = ui.select(options, value=search_state['cat'], label='Category', on_change=on_category) \
            .props('dense options-dense').classes('w-72').tooltip('Includes subcategories')
        # NiceGUI's option dicts have no room for extras and are rebuilt on change, so option icons are looked up by index
        icons = json.dumps({i: api.categories.get(c, {}).get('icon') or '' for i, c in enumerate(options)})
        category_select.add_slot('option', '''
            <q-item v-bind="props.itemProps">
              <q-item-section avatar style="min-width: 0; padding-right: 6px">
                <img v-if='ICONS[props.opt.value]' :src='ICONS[props.opt.value]' style="width: 30px; height: 30px">
                <span v-else style="display: inline-block; width: 30px"></span>
              </q-item-section>
              <q-item-section>{{ props.opt.label }}</q-item-section>
            </q-item>'''.replace('ICONS', '(' + icons + ')'))
    await results(search_state['term'], search_state['cat'])
    async def poll():
        if await poll_ambiguous_resolution():
            results.refresh(search_state['term'], search_state['cat'])

    ui.timer(2.0, poll)
