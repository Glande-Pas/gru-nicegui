import pytest

from gru_ui.links import find_url, parse


class TestParse:
    @pytest.mark.parametrize('url, expected', [
        ('gru://www.esoui.com/downloads/info7-LibAddonMenu.html', 7),
        ('GRU://esoui.com/downloads/info1234.html', 1234),
        ('  gru://www.esoui.com/downloads/info7-Lib-Addon.html  ', 7),
    ])
    def test_addon_page(self, url, expected):
        assert parse(url) == expected

    @pytest.mark.parametrize('url', [
        'https://www.esoui.com/downloads/info7-LibAddonMenu.html',
        'gru://www.esoui.com/downloads/fileinfo.php?id=7',
        'gru://evil.com/downloads/info7.html',
        'gru://www.esoui.com.evil.com/downloads/info7.html',
        'gru://www.esoui.com/downloads/infoabc.html',
        'gru://addon/7',
        'gru://' + 'a' * 600,
        None,
    ])
    def test_rejected(self, url):
        assert parse(url) is None


def test_find_url():
    assert find_url(['--x', 'gru://www.esoui.com/downloads/info1.html', 'other']) \
        == 'gru://www.esoui.com/downloads/info1.html'
    assert find_url(['--x']) is None
