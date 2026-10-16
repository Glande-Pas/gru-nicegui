# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Import of an exported add-on list: parse and validate, plan, apply. No UI.

Add-ons are installed at their latest version, except rows marked locked, which keep their listed version.
plan_import() and apply_import() do HTTP and disk work: call them from a worker."""

import csv
import enum
import io
import re
import typing
from dataclasses import dataclass, field

import requests
from gru.addon import _parse_version
from gru.api import AmbiguousDirectory

MAX_BYTES = 1_000_000
MAX_ROWS = 2000
_DIR = re.compile(r'^\w[\w. -]*$')
_LINK = re.compile(r'^https?://(?:www\.)?esoui\.com/downloads/info(\d+)(?:-[^/?#]*)?\.html')
_MAX_VERSION = 100
_MERGED = {'LibGroupSocket': 'LibGroupBroadcast'}  # folders now shipped by another listing


class ImportFormatError(ValueError):
    """The file isn't a usable add-on list."""


class Group(enum.Enum):
    INSTALL = 'To install'
    UNAVAILABLE = 'Locked version unavailable'
    LOCK = 'To lock (already installed)'
    SWITCH = 'To switch to another listing'
    INSTALLED = 'Already installed'
    MATCH = 'Ambiguous'
    NOT_FOUND = 'Not found'
    INCORRECT = 'Incorrect'
    INVALID = 'Invalid rows'


@dataclass(eq=False)
class Item:
    line: int
    dir: str
    version: str = ''
    link: str = ''
    locked: bool = False  # lock to apply; the plan lets the user turn it off
    in_file_locked: bool = False
    group: Group = Group.INSTALL
    note: str = ''
    selected: bool = False
    link_id: int | None = None
    candidates: list = field(default_factory=list)  # listings sharing the folder name
    info: typing.Any = None  # AddonInfo
    installed: typing.Any = None  # InstalledAddon
    needs_old: bool = False  # locked at a version other than the latest
    archived: typing.Any = None  # PreviousVersion
    replace_candidate: bool = False  # installed copy is older than the file's locked version, which is fetchable
    replace: bool = False  # that version replaces the installed one: the row is locked and ticked
    newer_missing: str = ''  # why a newer locked version can't be installed: 'unavailable' or 'unchecked'

    @property
    def title(self) -> str:
        if self.group is Group.INCORRECT:
            return self.dir  # the link resolved to another add-on: the folder name is the reliable source
        return (self.info.title if self.info is not None else '') or self.dir

    @property
    def section(self) -> Group:
        """Where the plan lists the item: ambiguous rows stay in Ambiguous after a listing was chosen."""
        return Group.MATCH if self.candidates else self.group

    @property
    def selectable(self) -> bool:
        return self.group in (Group.INSTALL, Group.LOCK, Group.SWITCH)

    @property
    def active(self) -> bool:
        """Whether applying does something with the item: a replace candidate always at least locks."""
        return self.selectable and (self.selected or (self.replace_candidate and self.locked) or self.lock_only)

    @property
    def lock_only(self) -> bool:
        """An unmatched installed folder, unticked for a switch, that a locked row still locks as it is."""
        return (self.group is Group.SWITCH and self.locked and not self.selected and self.installed is not None
                and self.installed.infos is None and not self.installed.locked)

    @property
    def installs(self) -> bool:
        """Whether applying downloads the add-on."""
        return self.group is Group.INSTALL or self.replace or (self.group is Group.SWITCH and self.selected)


def _invalid(item: Item, reason: str) -> Item:
    item.group, item.note, item.selected = Group.INVALID, reason, False
    return item


def parse_import(data: bytes) -> list[Item]:
    """Rows of an exported list, as items. Bad rows come back grouped as INVALID; a bad file raises."""
    if len(data) > MAX_BYTES:
        raise ImportFormatError('File is too large ({size} KB, at most {max} KB).'.format(
            size=len(data) // 1000, max=MAX_BYTES // 1000))
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ImportFormatError('File is not UTF-8 text.') from None
    reader = csv.DictReader(io.StringIO(text, newline=''))
    fields = {(name or '').strip().lower() for name in reader.fieldnames or []}
    if not {'dir', 'link'} <= fields:
        raise ImportFormatError('Not an exported add-on list: it needs "dir" and "link" columns.')

    items, seen = [], set()
    try:
        for line, raw in enumerate(reader, 2):
            if len(items) >= MAX_ROWS:
                raise ImportFormatError('Too many rows (at most {max}).'.format(max=MAX_ROWS))
            row = {(k or '').strip().lower(): (v or '').strip() for k, v in raw.items() if k is not None}
            item = Item(line, row.get('dir', ''), row.get('version', '')[:_MAX_VERSION], row.get('link', ''),
                        locked=row.get('locked', '').lower() == 'locked')
            item.in_file_locked = item.locked
            if item.dir and (item.dir in ('.', '..') or not _DIR.match(item.dir)):
                items.append(_invalid(item, 'Not a folder name'))
                continue
            link_id = None
            if item.link:
                match = _LINK.match(item.link)
                if match is None:
                    items.append(_invalid(item, 'Not an ESOUI.com add-on link'))
                    continue
                link_id = int(match.group(1))
            if not item.dir and link_id is None:
                items.append(_invalid(item, 'Neither folder nor link'))
                continue
            key = link_id if link_id is not None else item.dir
            if key in seen:
                items.append(_invalid(item, 'Duplicate of an earlier row'))
                continue
            seen.add(key)
            item.link_id = link_id
            items.append(item)
    except csv.Error as err:
        raise ImportFormatError('Malformed CSV: {error}'.format(error=err)) from None
    return items


def settle(item: Item) -> None:
    """Set an installable item's group and note from its current lock choice."""
    if item.group in (Group.INSTALL, Group.UNAVAILABLE) and item.installed is None:
        latest = item.info.version
        if item.locked and item.needs_old:
            if item.archived is not None:
                item.group = Group.INSTALL
                item.note = 'Locked: will install {version} (latest is {latest})'.format(
                    version=item.version, latest=latest)
            else:
                item.group = Group.UNAVAILABLE
                item.note = 'Locked at {version}, which is no longer available (latest is {latest}). ' \
                            'Unlock to install the latest.'.format(version=item.version, latest=latest)
        else:
            item.group = Group.INSTALL
            item.note = 'Will install {version} (latest)'.format(version=latest)
        item.selected = item.group is Group.INSTALL
    elif item.group is Group.SWITCH:
        version = item.version if item.locked and item.needs_old and item.archived is not None else item.info.version
        infos = item.installed.infos
        if item.lock_only:
            item.note = 'Will keep the installed {dir} ({installed}) and lock it, unmatched to a listing'.format(
                dir=item.installed.dir, installed=item.installed.version)
            return
        item.note = 'Will replace the installed {other} ({installed}) with {title} {version}'.format(
            other=infos.title if infos is not None else item.installed.dir, installed=item.installed.version,
            title=item.info.title, version=version)
    elif item.group is Group.LOCK:
        item.replace = item.replace_candidate and item.locked and item.selected
        if not item.locked:
            item.note = 'Not locked'
        elif item.replace:
            item.note = 'Will replace {version} with {listed} and lock it'.format(
                version=item.installed.version, listed=item.version)
        elif item.newer_missing == 'unavailable':
            item.note = 'Will keep {version} and lock it ({listed} is no longer available)'.format(
                version=item.installed.version, listed=item.version)
        elif item.newer_missing == 'unchecked':
            item.note = 'Will keep {version} and lock it (could not check whether {listed} is available)'.format(
                version=item.installed.version, listed=item.version)
        elif item.version and item.version != item.installed.version:
            item.note = 'Will keep {version} and lock it (the file has {listed})'.format(
                version=item.installed.version, listed=item.version)
        else:
            item.note = 'Will be locked at {version}'.format(version=item.installed.version)


def _find_newer_locked(item: Item, api) -> None:
    """Flag an installed add-on whose locked version in the file is newer than the installed one and fetchable."""
    item.replace_candidate, item.newer_missing = False, ''
    listed, current = _parse_version(item.version), _parse_version(item.installed.version)
    if listed is None or current is None or listed <= current:
        return
    if item.version == item.info.version:
        item.needs_old, item.archived, item.replace_candidate = False, None, True
        return
    try:
        versions = api.previous_versions(item.info.id)
    except requests.RequestException:
        item.newer_missing = 'unchecked'
        return
    item.archived = next((v for v in versions if v.version == item.version), None)
    item.needs_old = item.replace_candidate = item.archived is not None
    item.newer_missing = '' if item.replace_candidate else 'unavailable'


def _find_archived(item: Item, info, api) -> None:
    """For a locked row listing another version than the latest, look that version up among the archived ones."""
    item.needs_old = item.locked and bool(item.version) and item.version != info.version
    if item.needs_old:
        try:
            versions = api.previous_versions(info.id)
        except requests.RequestException:
            versions = []
        item.archived = next((v for v in versions if v.version == item.version), None)


def _resolve(item: Item, info, installed: dict, api) -> None:
    """Classify an item whose online listing is known. May do HTTP (archived versions)."""
    item.info = info
    folders = info.metadata.get('directories') or []
    if item.dir and item.dir != info.dir and item.dir not in folders and _MERGED.get(item.dir) != info.dir:
        item.group = Group.INCORRECT
        item.note = 'Link points to {title} (folder {dir}) instead of {listed}'.format(
            title=info.title, dir=info.dir, listed=item.dir)
        return

    item.installed = installed.get(info.dir)
    if item.installed is not None:
        other = item.installed.infos
        # An unmatched folder can be switched over to a listing the file's link or the user's pick names
        unmatched = other is None and (item.link_id is not None or bool(item.candidates))
        if (other is not None and other.id != info.id) or unmatched:
            item.group, item.selected = Group.SWITCH, False
            _find_archived(item, info, api)
            settle(item)
        elif item.locked and not item.installed.locked:
            item.group, item.selected = Group.LOCK, True
            _find_newer_locked(item, api)
            settle(item)
        else:
            item.group, item.note = Group.INSTALLED, 'Version {version}'.format(version=item.installed.version)
            if item.candidates:  # shown under Ambiguous, so say what the pick led to
                item.note += ' – Already installed'
        return

    _find_archived(item, info, api)
    item.group = Group.INSTALL
    settle(item)


def plan_import(items: list[Item], api, local) -> None:
    """Resolve each item against the online listings and the installed add-ons, in place. Does HTTP."""
    installed = {a.dir: a for a in local.installed}
    seen: dict = {}  # listing id -> first row resolved to it
    for item in items:
        if item.group is Group.INVALID:
            continue
        try:
            info = api.addon(item.link_id) if item.link_id is not None else api.dir(item.dir)
        except AmbiguousDirectory as err:
            item.group, item.candidates = Group.MATCH, list(err.candidates)
            item.note = 'No link provided: several ESOUI.com add-ons use this folder name'
            continue
        except (KeyError, FileNotFoundError):
            item.group, item.note = Group.NOT_FOUND, 'Not listed on ESOUI.com'
            continue
        _resolve(item, info, installed, api)
        first = seen.setdefault(info.id, item)
        if first is not item and item.group in (Group.INSTALL, Group.LOCK, Group.SWITCH, Group.INSTALLED):
            item.group, item.selected, item.replace, item.candidates = Group.INSTALLED, False, False, []
            item.note = 'Same add-on as {dir}'.format(dir=first.dir or first.title)


def choose_listing(item: Item, info, api, local) -> None:
    """Settle an ambiguous item on the listing the user picked, as if its link had pointed there. Does HTTP."""
    item.installed, item.needs_old, item.archived, item.selected = None, False, None, False
    item.replace_candidate, item.replace, item.newer_missing = False, False, ''
    _resolve(item, info, {a.dir: a for a in local.installed}, api)
    item.selected = item.group in (Group.INSTALL, Group.LOCK)  # a switch replaces another listing: opt-in


def apply_import(items: list[Item], api, local, opt: bool, progress=None) -> list[str]:
    """Install and lock the selected items, then save the state. Returns one message per failure."""
    errors, to_lock, fetched = [], set(), set()
    for item in items:
        if not item.active:
            continue
        if item.installs and item.info.id not in fetched:
            fetched.add(item.info.id)
            url = None
            if item.locked and item.needs_old and item.archived is not None:
                url = local.url_template.format(id=item.info.id) + f'&aid={item.archived.aid}'
            try:
                local.install(item.info, api, progress=progress, deps=True, opt=opt, url_override=url)
            except Exception as err:  # one failed download shouldn't stop the others
                errors.append('{title}: {err}'.format(title=item.title, err=err))
                continue
        if item.locked:
            to_lock.add(item.info.dir)
    for addon in local.installed:
        if addon.parent is None and addon.dir in to_lock:
            addon.locked = True
    local.export_state()
    return errors
