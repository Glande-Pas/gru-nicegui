from types import SimpleNamespace as NS

import pytest
import requests
from gru.api import AmbiguousDirectory

from gru_ui.importing import (Group, ImportFormatError, apply_import, choose_listing, parse_import, plan_import,
                              settle)

HEADER = 'dir,version,link,locked\n'


def info(id_, dir_, version, title=None):
    return NS(id=id_, dir=dir_, version=version, title=title or dir_, metadata={'directories': [dir_]})


class FakeAPI:
    def __init__(self, *infos, archived=None):
        self.by_id = {i.id: i for i in infos}
        self.archived = archived or {}

    def addon(self, id_):
        return self.by_id[id_]

    def dir(self, dir_):
        found = [i for i in self.by_id.values() if i.dir == dir_]
        if len(found) > 1:
            raise AmbiguousDirectory(dir_, found)
        if not found:
            raise FileNotFoundError(dir_)
        return found[0]

    def previous_versions(self, id_):
        return self.archived.get(id_, [])


class FakeLocal:
    url_template = 'https://cdn/getfile.php?id={id}'

    def __init__(self, *installed):
        self.installed = list(installed)
        self.calls = []
        self.exported = False

    def install(self, addon, api, progress=None, deps=True, opt=False, url_override=None):
        self.calls.append((addon.dir, url_override))
        self.installed.append(NS(dir=addon.dir, parent=None, locked=False, version=addon.version, infos=addon))

    def export_state(self):
        self.exported = True


def plan(csv_text, api, local):
    items = parse_import(csv_text.encode())
    plan_import(items, api, local)
    return items


def test_file_validation():
    with pytest.raises(ImportFormatError):
        parse_import(b'foo,bar\n1,2\n')
    for header in (b'dir\nFoo\n', b'link\nhttps://www.esoui.com/downloads/info7-Foo.html\n'):
        with pytest.raises(ImportFormatError):
            parse_import(header)
    with pytest.raises(ImportFormatError):
        parse_import(b'\xff\xfe')
    with pytest.raises(ImportFormatError):
        parse_import(b'x' * 2_000_000)


def test_row_validation():
    items = parse_import((HEADER + '../etc,1,,\n'
                          'Good,1,https://evil.example/downloads/info1-x.html,\n'
                          'A,1,https://www.esoui.com/downloads/info5-A.html,\n'
                          'A,2,https://www.esoui.com/downloads/info5-A.html,\n'
                          ',,,\n').encode('utf-8-sig'))
    assert [i.group for i in items] == [Group.INVALID, Group.INVALID, Group.INSTALL, Group.INVALID, Group.INVALID]


def test_install_latest_ignores_listed_version():
    api = FakeAPI(info(5, 'A', '2.0'))
    items = plan(HEADER + 'A,1.0,https://www.esoui.com/downloads/info5-A.html,\n', api, FakeLocal())
    assert items[0].group is Group.INSTALL and items[0].selected
    local = FakeLocal()
    assert apply_import(items, api, local, False) == []
    assert local.calls == [('A', None)]


def test_installed_is_skipped_and_never_downgraded():
    api = FakeAPI(info(5, 'A', '2.0'))
    local = FakeLocal(NS(dir='A', parent=None, locked=False, version='3.0', infos=None))
    items = plan(HEADER + 'A,1.0,,\n', api, local)
    assert items[0].group is Group.INSTALLED


def test_locked_old_version_uses_archive_and_can_be_unlocked():
    arch = NS(version='1.0', aid=77)
    api = FakeAPI(info(5, 'A', '2.0'), archived={5: [arch]})
    local = FakeLocal()
    items = plan(HEADER + 'A,1.0,,locked\n', api, local)
    item = items[0]
    assert item.group is Group.INSTALL and item.archived is arch
    assert apply_import(items, api, local, False) == []
    assert local.calls == [('A', 'https://cdn/getfile.php?id=5&aid=77')]
    assert local.installed[0].locked and local.exported

    local = FakeLocal()
    item.locked = False
    settle(item)
    apply_import(items, api, local, False)
    assert local.calls == [('A', None)] and not local.installed[0].locked


def test_locked_unavailable_version_is_not_installed_until_unlocked():
    api = FakeAPI(info(5, 'A', '2.0'))
    items = plan(HEADER + 'A,0.1,,locked\n', api, FakeLocal())
    item = items[0]
    assert item.group is Group.UNAVAILABLE and not item.selected
    item.locked = False
    settle(item)
    assert item.group is Group.INSTALL and item.selected


def test_locked_matching_latest_installs_and_locks():
    api = FakeAPI(info(5, 'A', '2.0'))
    items = plan(HEADER + 'A,2.0,,locked\n', api, FakeLocal())
    assert items[0].group is Group.INSTALL and items[0].locked and not items[0].needs_old


def test_installed_gets_lock_only():
    api = FakeAPI(info(5, 'A', '2.0'))
    addon = NS(dir='A', parent=None, locked=False, version='1.0', infos=info(5, 'A', '2.0'))
    local = FakeLocal(addon)
    items = plan(HEADER + 'A,1.0,,locked\n', api, local)
    assert items[0].group is Group.LOCK
    apply_import(items, api, local, False)
    assert addon.locked and local.calls == []


def test_lock_note_shows_file_version_when_it_differs():
    api = FakeAPI(info(5, 'A', '2.0'))
    addon = NS(dir='A', parent=None, locked=False, version='1.5', infos=info(5, 'A', '2.0'))
    same, other = (plan(HEADER + 'A,%s,,locked\n' % v, api, FakeLocal(addon))[0] for v in ('1.5', '1.0'))
    assert same.note == 'Will be locked at 1.5'
    assert other.note == 'Will keep 1.5 and lock it (the file has 1.0)'


def _installed(version):
    return NS(dir='A', parent=None, locked=False, version=version, infos=info(5, 'A', '3.0'))


def test_locked_newer_than_installed_replaces_it_with_latest():
    api = FakeAPI(info(5, 'A', '3.0'))
    addon = _installed('1.0')
    local = FakeLocal(addon)
    [item] = plan(HEADER + 'A,3.0,,locked\n', api, local)
    assert item.group is Group.LOCK and item.replace
    assert item.note == 'Will replace 1.0 with 3.0 and lock it'
    apply_import([item], api, local, False)
    assert local.calls == [('A', None)]


def test_unticked_replacing_row_keeps_installed_version_and_locks_it():
    api = FakeAPI(info(5, 'A', '3.0'))
    addon = _installed('1.0')
    local = FakeLocal(addon)
    [item] = plan(HEADER + 'A,3.0,,locked\n', api, local)
    item.selected = False
    settle(item)
    assert not item.replace and item.active
    assert item.note == 'Will keep 1.0 and lock it (the file has 3.0)'
    apply_import([i for i in [item] if i.active], api, local, False)
    assert local.calls == [] and addon.locked


def test_unlocking_a_replacing_row_leaves_the_installed_version_alone():
    api = FakeAPI(info(5, 'A', '3.0'))
    local = FakeLocal(_installed('1.0'))
    [item] = plan(HEADER + 'A,3.0,,locked\n', api, local)
    item.locked = False
    settle(item)
    assert not item.replace and item.note == 'Not locked'
    apply_import([item], api, local, False)
    assert local.calls == []


def test_locked_newer_than_installed_replace_uses_archive():
    archived = NS(version='2.0', aid=77)
    api = FakeAPI(info(5, 'A', '3.0'), archived={5: [archived]})
    local = FakeLocal(_installed('1.0'))
    [item] = plan(HEADER + 'A,2.0,,locked\n', api, local)
    assert item.replace
    apply_import([item], api, local, False)
    assert local.calls == [('A', 'https://cdn/getfile.php?id=5&aid=77')]


def test_locked_older_or_unavailable_only_locks_at_installed_version():
    api = FakeAPI(info(5, 'A', '3.0'))
    for listed, installed in (('1.0', '2.0'), ('2.5', '2.0')):  # older than installed; newer but not archived
        [item] = plan(HEADER + 'A,%s,,locked\n' % listed, api, FakeLocal(_installed(installed)))
        assert item.group is Group.LOCK and not item.replace and not item.replace_candidate


def test_newer_locked_version_notes_say_why_it_is_not_installed():
    [gone] = plan(HEADER + 'A,2.5,,locked\n', FakeAPI(info(5, 'A', '3.0')), FakeLocal(_installed('2.0')))
    assert gone.note == 'Will keep 2.0 and lock it (2.5 is no longer available)'

    class Failing(FakeAPI):
        def previous_versions(self, id_):
            raise requests.ConnectionError

    [unchecked] = plan(HEADER + 'A,2.5,,locked\n', Failing(info(5, 'A', '3.0')), FakeLocal(_installed('2.0')))
    assert unchecked.note == 'Will keep 2.0 and lock it (could not check whether 2.5 is available)'


def test_rows_resolving_to_one_listing_install_it_once():
    class ByFolder(FakeAPI):
        def dir(self, dir_):
            return next(i for i in self.by_id.values() if dir_ in i.metadata['directories'])

    listing = NS(id=1, dir='Bundle', version='1.0', title='Bundle', metadata={'directories': ['Bundle', 'Extra']})
    api, local = ByFolder(listing), FakeLocal()
    items = plan(HEADER + 'Bundle,1.0,,\nExtra,1.0,,\n', api, local)
    assert [i.group for i in items] == [Group.INSTALL, Group.INSTALLED]
    assert items[1].note == 'Same add-on as Bundle'
    apply_import(items, api, local, False)
    assert local.calls == [('Bundle', None)]


def test_folder_from_another_listing_can_be_switched_over_opt_in():
    api = FakeAPI(info(5, 'A', '3.0', title='Old A'), info(6, 'A', '2.0', title='New A'))
    addon = NS(dir='A', parent=None, locked=False, version='1.0', infos=info(5, 'A', '3.0', title='Old A'))
    local = FakeLocal(addon)
    link = 'https://www.esoui.com/downloads/info6-A.html'
    [item] = plan(HEADER + 'A,1.0,%s,\n' % link, api, local)
    assert item.group is Group.SWITCH and item.selectable and not item.selected
    assert item.note == 'Will replace the installed Old A (1.0) with New A 2.0'
    apply_import([i for i in [item] if i.active], api, local, False)
    assert local.calls == []
    item.selected = True
    apply_import([i for i in [item] if i.active], api, local, False)
    assert local.calls == [('A', None)]


def test_picking_a_listing_for_an_unmatched_installed_folder_offers_the_switch():
    one, two = info(1, 'A', '1.0', title='One'), info(2, 'A', '2.0', title='Two')
    api = FakeAPI(one, two)
    addon = NS(dir='A', parent=None, locked=False, version='0.9', infos=None)
    local = FakeLocal(addon)
    [item] = plan(HEADER + 'A,1.0,,\n', api, local)
    assert item.group is Group.MATCH and item.candidates
    choose_listing(item, two, api, local)
    assert item.group is Group.SWITCH and item.selectable and not item.selected
    assert item.note == 'Will replace the installed A (0.9) with Two 2.0'
    item.selected = True
    apply_import([item], api, local, False)
    assert local.calls == [('A', None)]


def test_link_row_for_an_unmatched_installed_folder_can_reinstall_or_just_lock():
    api = FakeAPI(info(5, 'A', '2.0', title='Two'))
    addon = NS(dir='A', parent=None, locked=False, version='0.9', infos=None)
    local = FakeLocal(addon)
    link = 'https://www.esoui.com/downloads/info5-A.html'
    [item] = plan(HEADER + 'A,0.9,%s,locked\n' % link, api, local)
    assert item.group is Group.SWITCH and not item.selected and item.lock_only
    assert item.note == 'Will keep the installed A (0.9) and lock it, unmatched to a listing'
    apply_import([item], api, local, False)
    assert local.calls == [] and addon.locked
    addon.locked = False
    item.selected = True
    settle(item)
    assert item.note == 'Will replace the installed A (0.9) with Two 2.0'
    apply_import([item], api, local, False)
    assert local.calls == [('A', None)]


def test_picking_the_installed_listing_of_an_ambiguous_row_says_already_installed():
    one, two = info(1, 'A', '1.0'), info(2, 'A', '2.0')
    api = FakeAPI(one, two)
    addon = NS(dir='A', parent=None, locked=False, version='1.0', infos=one)
    local = FakeLocal(addon)
    [item] = plan(HEADER + 'A,1.0,,\n', api, local)
    choose_listing(item, one, api, local)
    assert item.group is Group.INSTALLED and item.note == 'Version 1.0 – Already installed'


def test_ambiguous_and_missing():
    api = FakeAPI(info(1, 'A', '1'), info(2, 'A', '1'))
    items = plan(HEADER + 'A,1,,\nB,1,,\nC,1,https://www.esoui.com/downloads/info9-C.html,\n', api, FakeLocal())
    assert [i.group for i in items] == [Group.MATCH, Group.NOT_FOUND, Group.NOT_FOUND]
    assert items[0].note.startswith('No link provided: ') and len(items[0].candidates) == 2


def test_choosing_a_listing_makes_it_installable_and_selected():
    api = FakeAPI(info(1, 'A', '1'), info(2, 'A', '3'))
    local = FakeLocal()
    [item] = plan(HEADER + 'A,1,,\n', api, local)
    choose_listing(item, api.by_id[2], api, local)
    assert item.group is Group.INSTALL and item.selected and item.info.id == 2
    assert item.section is Group.MATCH and len(item.candidates) == 2  # stays listed as ambiguous
    choose_listing(item, api.by_id[1], api, local)  # the choice can be changed
    assert item.info.id == 1 and item.selected
    assert apply_import([item], api, local, False) == []
    assert local.calls == [('A', None)]


def test_link_not_matching_folder_is_incorrect():
    api = FakeAPI(info(5, 'A', '2.0', title='Alpha'))
    local = FakeLocal(NS(dir='B', parent=None, locked=False, version='1', infos=None))
    items = plan(HEADER + 'B,1,https://www.esoui.com/downloads/info5-A.html,\n', api, local)
    assert items[0].group is Group.INCORRECT and not items[0].selected
    assert items[0].note == 'Link points to Alpha (folder A) instead of B'
    assert items[0].title == 'B'


def test_merged_folder_is_not_incorrect():
    api = FakeAPI(info(5, 'LibGroupBroadcast', '2.0'))
    items = plan(HEADER + 'LibGroupSocket,1,https://www.esoui.com/downloads/info5-X.html,\n', api, FakeLocal())
    assert items[0].group is Group.INSTALL
