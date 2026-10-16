# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Hand gru:// links to an already running instance: it advertises its port and a secret in a file in the user
cache dir, and a later launch posts the link there instead of opening a second window."""

import atexit
import json
import os
import secrets
import socket

import requests
from gru import config as gruconfig

from .links import TOKEN_HEADER, register_routes


def _info_path():
    return gruconfig.user_cache('instance.json')


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def forward(url: str) -> bool:
    """Post `url` to the running instance. False if there is none (or it is gone: a stale file after a crash)."""
    try:
        info = json.loads(_info_path().read_text())
        response = requests.post('http://127.0.0.1:{port}/_open'.format(port=int(info['port'])), json={'url': url},
                                 headers={TOKEN_HEADER: info['token']}, timeout=5)
        return response.ok
    except (OSError, ValueError, KeyError, requests.RequestException):
        return False


_token = ''


def prepare() -> None:
    """Start accepting forwarded links (call before the server starts)."""
    global _token
    _token = secrets.token_urlsafe(32)
    register_routes(_token)


def publish(port: int) -> None:
    """Advertise this instance as the one links are forwarded to (call once the server is up)."""
    path = _info_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    mine = json.dumps({'port': port, 'token': _token})
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(mine)

    def cleanup():
        try:
            if path.read_text() == mine:  # a newer instance may have taken over
                path.unlink()
        except OSError:
            pass
    atexit.register(cleanup)
