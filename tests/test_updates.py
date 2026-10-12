# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

from gru_ui.updates import is_newer


def test_is_newer():
    assert is_newer('0.6.1', '0.6.0')
    assert is_newer('0.10.0', '0.9.5')
    assert not is_newer('0.6.0', '0.6.0')
    assert not is_newer('0.6.0', 'v0.6.1-1-g348205a')  # dev build past a newer tag
    assert not is_newer('0.6.0', '0.6.0-3-gabcdef0')
    assert is_newer('0.7.0', 'v0.6.1-1-g348205a')
    assert not is_newer('0.6.0', 'unknown')
