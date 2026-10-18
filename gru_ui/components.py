# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Reusable addon card component and the install/remove/update actions behind its buttons."""

import contextlib
import html
import importlib.resources
import inspect
import pathlib
import re
import warnings
import webbrowser

from nicegui import run, ui

from gru.addon import AddonBundle, InstalledAddon, AddonInfo, parse_version
from .utils import open_folder, si_suffixed, eso_colored, strip_eso_colors, anchor_id, bold, code, \
    installed_item, updated_item, hint
from .state import (opt_deps, rescan_async, flash_warning, flash_info, flash_summary, flash_warnings,
                    remove_vars_setting, patches_enabled, logged_changes, update_pending, update_moot, set_locked,
                    ambiguous_candidates, ranked_candidates, set_match, mark_local, mark_online, save_addon_patch, search_for,
                    dependency_search_term, card_detail, run_work, show_installed_card)


def split_source(source: str) -> tuple[str, str]:
    """(remote, ref) of a `git+<remote>[@<ref>]` source; ('', '') otherwise."""
    if not source.startswith('git+'):
        return '', ''
    rest = source[4:].removeprefix('git+')
    remote, _, ref = rest.rpartition('@')
    if not remote or ':' in ref or '/' in ref:
        return rest, ''
    return remote, ref


_SCP_REMOTE = re.compile(r'^(?:[\w.~-]+@)?([\w-]+(?:\.[\w-]+)+):([^/\\][^\\]*)$')
_SSH_REMOTE = re.compile(r'^ssh://(?:[^@/]+@)?([^:/]+)(?::\d+)?/(.+)$')


def web_url(remote: str) -> str:
    """The web page of a git `remote` (http(s), `ssh://` or `user@host:path`); '' if it has none."""
    if remote.startswith(('http://', 'https://')):
        return remote.removesuffix('.git')
    match = _SSH_REMOTE.match(remote) or _SCP_REMOTE.match(remote)
    return 'https://{host}/{path}'.format(host=match[1], path=match[2].removesuffix('.git').strip('/')) if match else ''


def external_link(inner_html: str, url: str, style: str = '') -> None:
    """A link that opens in the system browser, not the native app window (no back/close there)."""
    ui.html(f'<a style="cursor:pointer;{style}">{inner_html}</a>').on('click', lambda: webbrowser.open(url))


class _ProgressState:
    def __init__(self, message: str):
        self.message = message
        self.size = 0
        self.done = 0
        self.frac: float | None = None


@contextlib.asynccontextmanager
async def global_progress(label: str):
    """A floating progress card pinned to a corner of the page."""
    state = _ProgressState(label)
    with ui.context.client.content, \
            ui.card().classes('fixed bottom-4 right-4 z-[9999] w-96 shadow-lg gap-1') as card:
        label_el = ui.label(label)
        bar = ui.linear_progress(value=0, show_value=False)
        timer = ui.timer(0.15, lambda: tick())

    def tick():
        label_el.set_text('{message} {fraction:.0%}'.format(message=state.message, fraction=state.frac)
                          if state.frac is not None else state.message)
        bar.set_value(state.frac or 0)
        bar.props(f'indeterminate={"true" if state.frac is None else "false"}')

    try:
        yield state
    finally:
        timer.deactivate()
        card.delete()


def progress_factory(state: _ProgressState):
    """A gru ProgressFactory (size, message) -> ProgressProtocol that updates `state`."""
    def factory(size, message):
        return _StepProgress(state, size, message)
    return factory


class _StepProgress:
    def __init__(self, state: _ProgressState, size: int, message: str):
        self.state = state
        state.message = message
        state.size = size
        state.done = 0
        state.frac = 0.0 if size else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, size: int):
        self.state.done += size
        self.state.frac = min(self.state.done / self.state.size, 1.0) if self.state.size else None


def _category_label(api, category_id: int) -> str:
    try:
        return ' > '.join(api.cat_name_hierarchy(category_id))
    except Exception:
        return str(category_id)


def _category_icon(api, category_id: int) -> str | None:
    """The category's remote icon URL, fetched by the browser."""
    try:
        return api.cat(category_id)['icon'] or None
    except Exception:
        return None


def action_button(label: str, busy_label: str, on_click) -> ui.button:
    """A button that is disabled and shows `busy_label` while its (possibly async) `on_click` runs."""
    btn = ui.button(label)

    async def clicked():
        was_enabled = btn.enabled
        btn.disable()
        btn.set_text(busy_label)
        try:
            result = on_click()
            if inspect.isawaitable(result):
                await result
        finally:
            btn.set_text(label)
            btn.set_enabled(was_enabled)
    btn.on_click(clicked)
    return btn


def _bold_diff_suffix(current: str, upstream: str) -> str:
    """Return upstream with the first character that differs from current bolded to end."""
    for i, (a, b) in enumerate(zip(current, upstream)):
        if a != b:
            return upstream[:i] + f'<b>{upstream[i:]}</b>'
    common = min(len(current), len(upstream))
    return upstream[:common] + f'<b>{upstream[common:]}</b>'


def _api_label(local, version: int) -> str:
    """An API version number, with the game update it belongs to when known."""
    name = local.api_versions.name(version) if local is not None and local.api_versions else None
    return '{version} ({name})'.format(version=version, name=name) if name else str(version)


def _api_short(local, version: int) -> str:
    """"Season One (U51)": the update's name and number, just the name for "Update 44" and the number if unnamed."""
    name = local.api_versions.name(version) if local is not None and local.api_versions else None
    if not name:
        return str(version)
    if re.fullmatch(r'Update \d+', name):
        return name
    return '{name} (U{number})'.format(name=name, number=version % 100)


def _api_info(addon, local) -> tuple[list[int], str | None, int | None]:
    """The API versions an installed add-on declares, how they compare to the game's ('newer', 'older' or None)
    and the game's version."""
    declared = sorted({v for member in getattr(addon, 'members', [addon]) for v in getattr(member, 'api', [])})
    state = local.api_vs_game(addon) if local is not None else None
    game = local.game_api_version() if local is not None else None
    return declared, state, game


def _api_closest(declared: list[int], game: int | None) -> int:
    """The declared API version nearest the game's (the lower one on a tie), else the highest."""
    return min(declared, key=lambda v: (abs(v - game), v)) if game is not None else max(declared)


def _api_message(state: str, declared: list[int], game: int, local) -> str:
    if state == 'newer':
        return ('Written for game version {api}, newer than current {game}. It may use features not yet available in '
                'this version of the game, for instance ones only on the PTS.').format(
                    api=_api_label(local, _api_closest(declared, game)), game=_api_label(local, game))
    return ('Written for game version {api}, older than current {game}. Will be marked "Obsolete" in game, '
            'though there is usually nothing to worry about.') \
                    .format(api=_api_label(local, _api_closest(declared, game)), game=_api_label(local, game))


def _api_cell(addon, local) -> str | None:
    """The API versions as a metadata value, marked with a tooltip when newer or older than the game's."""
    declared, state, game = _api_info(addon, local)
    if not declared:
        return None
    text = _api_short(local, _api_closest(declared, game))
    if state is not None and game is not None:
        marker = '🚧' if state == 'newer' else '🕰️'
        return hint('{text} {marker}'.format(text=text, marker=marker), _api_message(state, declared, game, local))
    return hint(text, ', '.join(_api_label(local, v) for v in declared))


def _metadata_rows(addon, api, local, full: bool = True) -> list[tuple]:
    """Return (label, value, span) triples for display."""
    is_installed = isinstance(addon, InstalledAddon)
    is_embedded = is_installed and local is not None and addon.parent is not None

    if is_installed:
        infos = addon.infos
        meta = infos.metadata if infos else {}
        version = addon.version
        upstream_version = infos.version if infos else None
    else:
        meta = addon.metadata
        version = addon.version
        upstream_version = None

    date = meta.get('date')
    category = meta.get('category')
    downloads = meta.get('downloads')
    monthly = meta.get('monthly')
    favorites = meta.get('favorites')

    if is_installed and addon.locked:
        version_str = ('{version} 🔒 (latest: {latest})' if addon.can_update else '{version} 🔒') \
            .format(version=version, latest=upstream_version)
    elif upstream_version and addon.can_update and not update_moot(addon):
        version_str = version + ' → ' + _bold_diff_suffix(version, upstream_version)
        if addon.update_by_date and addon.override is None and parse_version(version) is not None \
                and parse_version(version) == parse_version(upstream_version):
            version_str = hint(version_str, 'Newer (re)upload')
    else:
        version_str = version

    api_cell = _api_cell(addon, local) if full and is_installed and local is not None else None
    if is_embedded:
        return [
            ('Author',    eso_colored(addon.author) if addon.author else '?', 3),
            ('Version',   version_str,                                         1),
            *([('Directory', addon.folder, 3 if api_cell else 4)] if full else []),
            *([('API', api_cell, 1)] if api_cell else []),
        ]

    source = getattr(addon, 'source', '') if is_installed else ''
    if source:
        remote, ref = split_source(source)
        source_label, source_str = ('Git ref', html.escape(ref)) if ref else ('Source', 'Git' if remote else 'Local')
        rows = [
            ('Author',    eso_colored(addon.author) if addon.author else '?', 2),
            (source_label, source_str,                                         1),
            ('Version',   version_str,                                        1),
        ]
    else:
        rows = [
            ('Author',    eso_colored(addon.author) if addon.author else '?', 2),
            ('Downloads', '{total} ({monthly}/mo)'.format(total=si_suffixed(downloads), monthly=si_suffixed(monthly))
                          if downloads else '?', 1),
            ('Version',   version_str,                                         1),
            ('Category',  _category_label(api, category) if category else '?', 2),
            ('Favorites', si_suffixed(favorites) if favorites else '?',        1),
            ('Updated',   date.strftime('%x') if date else '?',               1),
        ]

    if is_installed and full:
        rows.append(('Directory', addon.folder, 3 if api_cell else 4))
        if api_cell:
            rows.append(('API', api_cell, 1))

    return rows


def _render_meta_grid(addon, api, local, full: bool = True):
    def value(val):
        if not isinstance(val, pathlib.Path):
            return f'<span>{val}</span>'
        path = html.escape(str(val), quote=True)
        return f'<span class="gru-meta-nowrap"><a data-path="{path}" style="cursor:pointer">{path}</a></span>'

    cells = ''.join(
        f'<div class="gru-meta-cell" style="grid-column:span {span}">'
        f'<span class="gru-meta-lbl">{lbl}</span>{value(val)}</div>'
        for lbl, val, span in _metadata_rows(addon, api, local, full)
    )
    ui.html(
        f'<div style="display:grid; grid-template-columns:repeat(4,1fr); width:100%;'
        f' gap:0.3rem 0.75rem; font-size:0.85em;">'
        f'{cells}</div>'
    ).classes('w-full').on(
        'click', lambda e: open_folder(e.args), js_handler='(e) => {'
        ' const a = e.target.closest("[data-path]"); if (a) emit(a.dataset.path); }')


def _installed_copy(dep, local):
    """Any installed copy of a dependency's folder, whatever its version."""
    return next((a for a in local.dir(dep.dir) if not isinstance(a, AddonBundle)), None)


def _dependency_link(dep, addon, local, optional: bool) -> None:
    """One dependency: linked to its card on Installed Add-Ons if installed, else to a search for it.
    The game ignores versions of optional dependencies, so any installed copy counts for those. """
    too_old = False
    if optional:
        found = _installed_copy(dep, local)
    else:
        found = local.find_installed(dep)
        if found is None:
            found = _installed_copy(dep, local)
            too_old = found is not None
    if found is None:
        ui.html(f'<a style="cursor:pointer">{"➕" if optional else "❌"} {dep.dir}</a>').on(
            'click', lambda: search_for(dependency_search_term(dep.dir))).tooltip(
                'Not installed, but optional: search online for it' if optional else
                'Missing, and needed: search online for it')
        return
    top, own_top = found, addon
    while top.parent is not None:
        top = top.parent
    while own_top.parent is not None:
        own_top = own_top.parent
    updatable = update_pending(found)
    mark = '⚠️' if too_old else '🔄' if updatable else '✅'
    if top is own_top:
        tip = ('Bundled with this add-on, but older than required' if too_old else
               'Bundled with this add-on, update available' if updatable else 'Bundled with this add-on')
        ui.html(f'<span>{mark} {dep.dir}</span>').tooltip(tip)
    else:
        tip = (('Installed, but older than required, update available: go to its card' if updatable else
                'Installed, but older than required: go to its card') if too_old else
               'Installed, update available: go to its card' if updatable else 'Installed: go to its card')
        ui.html(f'<a href="#{anchor_id(top.dir)}">{mark} {dep.dir}</a>').tooltip(tip)


def _render_dependencies(addon, local, dimmed: bool, with_optional: bool = True) -> None:
    for label, deps, optional in (('Requires', addon.deps, False), ('Works with', addon.optdeps, True)):
        if not deps or (optional and not with_optional):
            continue
        with ui.row().classes('w-full items-baseline gap-x-2 gap-y-0' + (' opacity-50' if dimmed else '')) \
                .style('font-size:0.85em'):
            ui.html(f'<span class="gru-meta-lbl">{label}</span>').tooltip(
                'Needed by this add-on: it will not load if any of them is missing' if not optional else
                'Optional extras: this add-on uses them when installed, but works fine without them')
            for dep in deps:
                _dependency_link(dep, addon, local, optional)


def _render_dependents(addon, local, dimmed: bool) -> None:
    """For a library: the installed add-ons that depend on it, or a red cross when none does."""
    if getattr(addon, 'is_lib', False) is not True:
        return
    required, optional = [], []
    for other in local.installed:
        if other is addon:
            continue
        if any(dep.dir == addon.dir for dep in other.deps):
            required.append(other)
        elif any(dep.dir == addon.dir for dep in other.optdeps):
            optional.append(other)
    own_top = addon
    while own_top.parent is not None:
        own_top = own_top.parent
    with ui.row().classes('w-full items-baseline gap-x-2 gap-y-0' + (' opacity-50' if dimmed else '')) \
            .style('font-size:0.85em'):
        ui.html('<span class="gru-meta-lbl">Used by</span>').tooltip(
            'The installed add-ons that depend on this library')
        if not required and not optional:
            ui.html('<span>❌ None</span>').tooltip('No installed add-on uses this library: it can be removed')
            return
        groups = ((required, '',
                   'Needs this library, bundled with it', 'Needs this library: go to its card'),
                  (optional, ' (optional)',
                   'Optionally uses this library, bundled with it', 'Optionally uses this library: go to its card'))
        for others, mark, bundled_tip, linked_tip in groups:
            for other in sorted(others, key=lambda a: (a.title or a.dir).lower()):
                top = other
                while top.parent is not None:
                    top = top.parent
                name = '{icon} {name}{mark}'.format(
                    icon='📗' if getattr(other, 'is_lib', False) is True else '🧩',
                    name=html.escape(strip_eso_colors(other.title or other.dir)), mark=mark)
                if top is own_top:
                    ui.html(f'<span>{name}</span>').tooltip(bundled_tip)
                else:
                    ui.html(f'<a href="#{anchor_id(top.dir)}">{name}</a>').tooltip(linked_tip)


# Cards the user opened to full detail this session, whatever the card detail setting
_OPENED: set = set()


def reset_opened_cards() -> None:
    _OPENED.clear()


def addon_card(addon, api, local, refresh, children: list | None = None, children_label: str | None = None,
               dimmed: bool = False, expanded: bool = False, on_lock_change=None, registry: dict | None = None,
               refresh_cards=None):
    """Render a single addon as a card with action buttons. When filtering, `children` holds only the matching
    bundled addons with `children_label` as their dropdown text, `dimmed` greys out the card itself and `expanded`
    opens the dropdown. `on_lock_change` is called after locking or unlocking, which only refreshes this card.
    A page can give a `registry` to be filled with each online add-on's id -> card refresh function, and a
    `refresh_cards` called with the ids of the cards to refresh after an install, instead of `refresh`."""
    @ui.refreshable
    def card():
        is_installed = isinstance(addon, InstalledAddon)
        setting = card_detail()
        key = (is_installed, addon.folder if is_installed else getattr(addon, 'id', None))
        opened = key in _OPENED
        level = 'full' if opened else setting
        has_id = getattr(addon, 'id', None) is not None
        can_update = update_pending(addon) if has_id and is_installed else False
        is_locked = is_installed and addon.locked
        is_lib = getattr(addon, 'is_lib', False) is True
        unused = is_lib and is_installed and local is not None and local.depcount(addon) == 0
        is_embedded = is_installed and local is not None and addon.parent is not None

        title = eso_colored(addon.title) if addon.title else ''
        link = (addon.infos.metadata.get('link') if is_installed and addon.infos else None) or \
               (addon.metadata.get('link') if not is_installed else None)

        candidates = ambiguous_candidates(addon) if is_installed else []

        installed_copies = ([a for a in local.installed if getattr(a, 'id', None) == addon.id]
                            if not is_installed and has_id and local is not None else [])
        ambiguous_copies = ([a for a in local.installed if a.infos is None and not a.source and
                             any(c.id == addon.id for c in ambiguous_candidates(a))]
                            if not is_installed and has_id and local is not None else [])
        already_installed = bool(installed_copies)
        installed_top = None
        for copy in sorted(installed_copies, key=update_moot)[:1]:
            installed_top = copy
            while installed_top.parent is not None:
                installed_top = installed_top.parent
        locked_copy = any(a.locked for a in installed_copies + ambiguous_copies)

        missing = local.missing_deps([addon]) if is_installed and not is_embedded and local is not None else []
        has_missing = bool(missing)
        only_outdated = has_missing and all(_installed_copy(dep, local) is not None for dep in missing)

        # Title badges as (text, explanation).
        locked_badge = ('🔒 Version locked', 'Kept at current version: updates ignored until unlocked.')
        version_badges = []
        if candidates:
            version_badges.append((
                '❓ Matches {count} ESOUI.com add-ons'.format(count=len(candidates)),
                'Several ESOUI.com add-ons install this folder name and gru cannot tell which one this is, '
                'so updates cannot be detected. Pick the right one with "Match ESOUI.com listing".'))
            if is_locked:
                version_badges.append(locked_badge)
        elif is_installed and can_update and addon.parent is not None:
            version_badges.append((
                '🔄 Update available as a standalone library',
                'This library is bundled inside another add-on. '
                'A newer version exists on ESOUI.com as its own download.'))
        elif is_installed and can_update:
            version_badges.append(('🔄 Update available', 'A newer version is available on ESOUI.com.'))
        elif is_locked:
            version_badges.append(locked_badge)
            if addon.can_update and not update_moot(addon):
                version_badges.append((
                    '🔄 Update available',
                    'A newer version exists on ESOUI.com, but it will not be installed while the version is locked.'))
        elif ambiguous_copies:
            version_badges.append((
                '❓ Possibly installed',
                "An installed folder has this add-on's folder name but is not matched to this ESOUI.com listing, "
                'so it may be this add-on, or another with the same folder name.'))
            if locked_copy:
                version_badges.append(locked_badge)
        elif already_installed:
            version_badges.append(('✅ Installed', 'This add-on is installed.'))
            if locked_copy:
                version_badges.append(locked_badge)

        # From the game's AddOnSettings.txt
        disabled = local.disabled_in_game(addon) if is_installed and local is not None and not is_embedded else None

        badges = []
        if is_installed and has_missing:
            is_disabled = disabled is not None and disabled.everywhere
            if only_outdated:
                tip = ('Some add-ons needed by this add-on are installed in an older version than it requires, '
                       'so it will not load in game. It is currently disabled in game, '
                       'so this only matters once it is enabled.' if is_disabled else
                       'Some add-ons needed by this add-on are installed in an older version than it requires, '
                       'so it will not load in game.')
            else:
                tip = ('Some add-ons needed by this add-on are not installed, so it will not load in game. '
                       'It is currently disabled in game, so this only matters once it is enabled.' if is_disabled else
                       'Some add-ons needed by this add-on are not installed, so it will not load in game.')
            badges.append(('❌ Missing dependencies', tip))
        badges.extend(version_badges)
        source = getattr(addon, 'source', '') if is_installed and not is_embedded else ''
        if source.startswith('git+'):
            badges.append(('🌿 Git', 'A git checkout of {remote}: never matched on ESOUI.com nor updated by gru.'
                                  .format(remote=split_source(source)[0])))
        elif source:
            badges.append(('📁 Local', 'Marked as local: never matched on ESOUI.com nor updated by gru.'))
        if disabled is not None:
            listed = ', '.join(str(character) for character in disabled.characters)
            if disabled.everywhere:
                badges.append(('⏸ Disabled on all characters',
                               'Disabled in game for all characters. '
                               'It is still kept up to date, so it can be enabled at any time.'))
            else:
                badges.append(('⏸ Disabled on {count} character(s)'.format(count=len(disabled.characters)),
                               'Disabled in game on: {listed}. It is still kept up to date, so it can be enabled '
                               'at any time.'.format(listed=listed)))
        if is_installed and addon.infos is not None and len(addon.infos.folders) > 1 and addon.version_rank:
            if addon.version_rank == 'active':
                badges.append(('🟢 active copy',
                               'Several copies of this add-on are installed. '
                               'This one has the newest version, so will be the one loaded in game.'))
            else:
                badges.append(('⚪ superseded copy',
                               'Several copies of this add-on are installed. '
                               'A newer copy exists, so this one is not loaded in game.'))
        if isinstance(addon, AddonBundle):
            badges.append(('📦 bundle', 'Not an add-on itself, but a folder grouping several add-ons, downloaded as a '
                                        'single bundle. Updating or removing it affects all bundled addons.'))
        elif is_installed and is_lib and unused:
            badges.append(('🧹 Unused library',
                           'A library, which provides code for other add-ons. No installed add-on depends on it, '
                           'so it can safely be removed.'))
        elif is_installed and is_lib:
            badges.append(('📗 Library', 'Provides code for other add-ons. '
                                         'See "Used by" for which ones require this library.'))
        status_parts = [hint(text, tip) for text, tip in badges]
        status_span = (
            ' <span style="display:inline-block; font-size:0.85em; font-weight:600; opacity:0.75">'
            + ', '.join(status_parts) + '</span>' if status_parts else ''
        )
        anchor = f' id="{anchor_id(addon.dir)}"' if is_installed and addon.parent is None else ''
        collapsible = is_installed and setting != 'full'
        chevron = ('<span style="display:inline-block; width:1em; opacity:0.6">{mark}</span>'.format(
            mark='▾' if opened else '▸') if collapsible else '')
        title_html = (
            f'<div{anchor} class="gru-card-title">'
            f'  {chevron}<span style="display:inline-block; font-size:1.25em; font-weight:600">{title}</span>'
            f'  {status_span}'
            f'</div>'
        )

        def toggle_opened():
            _OPENED.symmetric_difference_update({key})
            card.refresh()

        with ui.card().classes('w-full gap-2'):
            dim = ' opacity-50' if dimmed else ''
            title_box = ui.html(title_html).classes(dim)
            if collapsible:
                title_box.classes('cursor-pointer').on('click', toggle_opened)

            with ui.row().classes('w-full items-start no-wrap gap-4' + dim):
                if not is_embedded:
                    category = (addon.infos.metadata if is_installed and addon.infos else
                                addon.metadata if not is_installed else {}).get('category')
                    icon_url = _category_icon(api, category) if category else None
                    special = 'git' if source.startswith('git+') else 'local' if source else \
                        'ambiguous' if candidates else None
                    if special:
                        icon_url = str(importlib.resources.files('gru_ui').joinpath('assets', special + '.png'))
                    if icon_url:
                        ui.image(icon_url).classes('w-10 h-10 shrink-0')

                with ui.column().classes('flex-grow gap-1 min-w-0'):
                    _render_meta_grid(addon, api, local, full=level == 'full')

                if not is_embedded:
                    with ui.column().classes('items-end shrink-0').style('min-width:10rem'):
                        if link:
                            external_link('🔗 ESOUI.com page', link, style='font-size:0.85em')
                        elif candidates:
                            ui.html('<span style="font-size:0.85em">Could be any of:</span>')
                            for c in candidates:
                                external_link('🔗 {title}'.format(title=eso_colored(c.title)), c.metadata['link'])
                        elif source:
                            remote = split_source(source)[0]
                            url = web_url(remote)
                            if url:
                                external_link('🔗 Git repository', url, style='font-size:0.85em')
                            elif remote:
                                ui.html('<span style="font-size:0.85em">Git repository</span>').tooltip(remote)
                        else:
                            ui.html('<span class="gru-badge-warn" title="No ESOUI.com add-on uses this folder name, '
                                    'so it can\'t be updated.">❔ Not found on ESOUI.com</span>')
                        if installed_top is not None:
                            ui.html('<a style="cursor:pointer;font-size:0.85em">📦 Installed Add-Ons</a>').on(
                                'click', lambda: show_installed_card(anchor_id(installed_top.dir))) \
                                .tooltip('Go to the installed copy of this add-on')

            if is_installed and local is not None:
                if level != 'compact':
                    _render_dependencies(addon, local, dimmed, with_optional=level == 'full')
                    _render_dependents(addon, local, dimmed)

            with ui.row().classes('w-full justify-end gap-1' + dim):
                if not is_installed and has_id:
                    install_help = ('Unlock the installed version first' if locked_copy else
                                    'Replaces the installed {folders} folder and records it as this add-on'.format(
                                        folders=', '.join(str(a.folder.relative_to(local.root))
                                                          for a in ambiguous_copies)) if ambiguous_copies else None)
                    btn = action_button('🔁 Reinstall' if already_installed else '⬇️ Install',
                                        '⏳ Reinstalling…' if already_installed else '⏳ Installing…',
                                        lambda: _run_install(addon, api, local, refresh, refresh_cards))
                    btn.set_enabled(not locked_copy)
                    btn.tooltip(install_help or (
                        'Download this add-on again from ESOUI.com, replacing the installed copy'
                        if already_installed else 'Download this add-on from ESOUI.com into your add-ons folder'))

                if is_installed:
                    if can_update:
                        latest = addon.infos.version if addon.infos else None
                        label = ('⬆️ Install {version} standalone' if is_embedded else '⬆️ Update to {version}') \
                            .format(version=latest) if latest else \
                            '⬆️ Install standalone' if is_embedded else '⬆️ Update'
                        up_btn = action_button(label, '⏳ Installing…' if is_embedded else '⏳ Updating…',
                                               lambda: _run_update(addon, api, local, refresh))
                        up_btn.props('color=update text-color=update-fg').tooltip('Install the update as a standalone library add-on' if is_embedded else
                                       'Update to the latest ESOUI.com version')

                    action_button('🗑️ Remove', '⏳ Removing…', lambda: _handle_remove(addon, local, refresh)) \
                      .tooltip("Delete this add-on's folder, including any add-ons bundled inside it")

                    # Only offered while unmatched: once set (by hand or by auto-resolve), a match is
                    # permanent -- remove the add-on and install the right one instead of changing it.
                    if not is_embedded and candidates:
                        ui.button('🔗 Match ESOUI.com listing', on_click=lambda: open_choose_match(addon, refresh)) \
                          .tooltip('Select which ESOUI.com add-on this folder is, which several share')

                    if not is_embedded and not source:
                        lock_label = '🔓 Unlock version' if is_locked else '🔒 Lock version'
                        lock_btn = action_button(
                            lock_label, '⏳ Unlocking…' if is_locked else '⏳ Locking…',
                            lambda: _handle_lock(addon, is_locked, card.refresh, on_lock_change))
                        lock_btn.tooltip('Allow updates for this add-on again' if is_locked else
                                         'Pin to the installed version: skip updates')

                    if not is_embedded and addon.infos is not None and patches_enabled():
                        action_button('💾 Save changes', '⏳ Saving…',
                                      lambda: _handle_save(addon, api, local, card.refresh)) \
                            .tooltip('Save local changes as a patch, to re-apply after updates')

                    if is_installed and addon.parent is None:
                        if not source and addon.infos is None:
                            action_button('📁 Mark as local', '⏳ Marking…',
                                          lambda: _handle_mark(mark_local, addon, refresh)) \
                                .tooltip('Never match this folder on ESOUI.com nor update it')
                        elif source and not source.startswith('git+'):
                            action_button('🌐 Match online', '⏳ Matching…',
                                          lambda: _handle_mark(mark_online, addon, refresh)) \
                                .tooltip('Look this folder up on ESOUI.com again')

            if children:
                with ui.expansion(children_label or '{count} bundled addon(s)'.format(count=len(children)), icon='expand_more',
                                  value=expanded).classes('w-full'):
                    for child in sorted(children, key=lambda a: a.title.lower()):
                        addon_card(child, api, local, refresh, on_lock_change=on_lock_change)

    if registry is not None and getattr(addon, 'id', None) is not None:
        registry[addon.id] = card.refresh
    card()


async def _handle_mark(action, addon, refresh):
    await action(addon)
    refresh()


async def _handle_lock(addon, is_locked: bool, refresh_card, on_change=None):
    await set_locked(addon, not is_locked)
    refresh_card()
    if on_change is not None:
        on_change()


async def _handle_save(addon, api, local, refresh):
    try:
        async with global_progress('Checking {title}...'.format(title=addon.title)):
            n, messages = await run.io_bound(save_addon_patch, addon, api, local)
    except Exception as exc:
        flash_warning('Failed to check {title}: {error}'.format(title=bold(addon.title), error=exc))
        return
    for message in messages:
        flash_warning(message)
    if n:
        flash_info('Saved patch for {title} ({count} modified file(s))'.format(title=bold(addon.title), count=n))
    elif n == 0:
        flash_info('No local changes to save for {title}.'.format(title=bold(addon.title)))
    refresh()


async def _handle_remove(addon: InstalledAddon, local, refresh):
    setting = remove_vars_setting()
    if setting == 'ask' and local.saved_variable_files(addon):
        _open_confirm_remove(addon, local, refresh)
    else:
        await _do_remove(addon, local, remove_vars=setting == 'yes')
        refresh()


async def _do_remove(addon: InstalledAddon, local, remove_vars: bool = False):
    title = addon.title or addon.dir

    def work():
        with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
            local.remove(addon, remove_vars=remove_vars)
        return caught

    async with global_progress('Removing {title}...'.format(title=title)):
        caught = await run_work(work, 'Failed to remove {title}'.format(title=bold(title)))
        await rescan_async()
    flash_warnings(caught)
    flash_info('Removed: {title}'.format(title=bold(title)))


def _open_confirm_remove(addon: InstalledAddon, local, refresh):
    files = local.saved_variable_files(addon)
    with ui.dialog() as dialog, ui.card():
        ui.html('{title} has saved variables:'.format(title=bold(addon.title)))
        ui.code('\n'.join(str(path) for path in files))
        ui.label("Deleting them discards this add-on's settings and data for all characters.").classes('text-caption')

        async def choose(delete: bool):
            dialog.close()
            await _do_remove(addon, local, remove_vars=delete)
            refresh()

        with ui.row().classes('w-full'):
            ui.button('🗑️ Delete them too', on_click=lambda: choose(True)).classes('flex-grow') \
              .tooltip('Remove the add-on and its saved variables')
            ui.button('💾 Keep them', on_click=lambda: choose(False)).classes('flex-grow') \
              .tooltip('Remove the add-on but keep its saved variables')
    dialog.open()


async def _run_install(addon: AddonInfo, api, local, refresh, refresh_cards=None):
    before = {a.dir for a in local.installed}
    async with global_progress('Installing {title}...'.format(title=addon.title)) as state:
        progress = progress_factory(state)

        def work():
            with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                installed = list(local.unpack(addon, api, progress=progress))
                local.install_deps(installed, api, opt=opt_deps(), progress=progress)
            return caught

        caught = await run_work(work, 'Failed to install {title}'.format(title=bold(addon.title)))
    flash_warnings(caught)
    await rescan_async()
    new = [a for a in sorted(local.installed, key=lambda a: (a.title or a.dir).lower()) if a.dir not in before]
    flash_summary('Installed', [installed_item(a.title or a.dir, a.version) for a in new])
    if refresh_cards is None:
        refresh()
    else:
        refresh_cards({addon.id, *(getattr(a, 'id', None) for a in new)} - {None})


async def _run_update(addon: InstalledAddon, api, local, refresh):
    if addon.locked:
        flash_warning('{title} is version locked, not updating.'.format(title=bold(addon.title)))
        return
    if addon.infos is None:
        flash_warning('{title} is not matched to a single ESOUI.com add-on, not updating.'
                      .format(title=bold(addon.title)))
        return
    if update_moot(addon):
        flash_warning('{title} is superseded by a newer copy, not updating.'.format(title=bold(addon.title)))
        return

    before = {a.folder: (a.title, a.version) for a in local.installed}
    async with global_progress('Updating {title}...'.format(title=addon.title)) as state:
        progress = progress_factory(state)
        path = addon.folder if addon.parent is None else None

        def work():
            with logged_changes(), warnings.catch_warnings(record=True, category=UserWarning) as caught:
                updated = list(local.unpack(addon.infos, api, path=path, progress=progress))
                local.install_deps(updated, api, opt=opt_deps(), progress=progress)
            return caught

        caught = await run_work(work, 'Failed to update {title}'.format(title=bold(addon.title)))
    flash_warnings(caught)
    await rescan_async()
    after = {a.folder: (a.title, a.version) for a in local.installed}
    installed, updated = [], []
    for folder, (title, v_after) in sorted(after.items(), key=lambda x: x[1][0].lower()):
        if folder not in before:
            installed.append(installed_item(title, v_after))
        elif before[folder][1] != v_after:
            updated.append(updated_item(title, before[folder][1], v_after))
    flash_summary('Installed', installed)
    flash_summary('Updated', updated)
    refresh()


def open_choose_match(addon: InstalledAddon, refresh, context: str | None = None):
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
        if context:
            ui.label(context).classes('text-caption')
        ui.html('Several ESOUI.com add-ons install a {folder} folder. Which one is {title} {version} by {author}?'
                .format(folder=code(addon.dir), title=bold(addon.title), version=addon.version,
                        author=eso_colored(addon.author or '?')))
        spinner = ui.spinner('dots', size='lg')
        content = ui.column().classes('w-full gap-2')
    dialog.open()

    async def load():
        ranked = await run.io_bound(ranked_candidates, addon)
        spinner.delete()

        def label(candidate):
            text = '{title} {version} by {author} ({downloads} downloads)'.format(
                title=strip_eso_colors(candidate.title), version=candidate.version,
                author=strip_eso_colors(candidate.author),
                downloads=si_suffixed(candidate.metadata.get('downloads') or 0))
            if candidate is ranked[0]:
                text = '{text} — best guess'.format(text=text)
            if candidate is addon.infos:
                text = '{text} — current match'.format(text=text)
            return text

        with content:
            current_index = next((i for i, c in enumerate(ranked) if c is addon.infos), 0)
            picked_box = {'value': ranked[current_index]}
            link_html = ui.html('')
            link_html.on('click', lambda: webbrowser.open(picked_box['value'].metadata['link']))

            def show_link():
                link_html.set_content('<a style="cursor:pointer">🔗 View it on ESOUI.com</a>')

            def on_pick(e):
                picked_box['value'] = ranked[e.value] if isinstance(e.value, int) else e.value
                show_link()
                confirm_btn.set_enabled(picked_box['value'] is not addon.infos)

            radio_options = {i: label(c) for i, c in enumerate(ranked)}
            ui.radio(radio_options, value=current_index, on_change=on_pick)
            show_link()

            async def confirm():
                await set_match(addon, picked_box['value'])
                dialog.submit(True)
                refresh()

            async def make_local():
                dialog.submit(True)
                await mark_local(addon)
                refresh()

            with ui.row().classes('gap-2'):
                confirm_btn = ui.button('✅ Confirm', on_click=confirm) \
                    .tooltip('Use the selected ESOUI.com listing for this folder')
                confirm_btn.set_enabled(picked_box['value'] is not addon.infos)
                if addon.infos is None and not addon.source:
                    ui.button('📁 None of these, mark as local', on_click=make_local) \
                        .tooltip('Never match this folder on ESOUI.com nor update it')

    ui.timer(0.01, load, once=True)
    return dialog
