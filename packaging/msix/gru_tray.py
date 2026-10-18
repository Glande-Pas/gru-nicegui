# Copyright Glande-Pas and contributors
# Licensed under the EUPL, see LICENSE.md

"""Target of the MSIX startup task, which can't pass arguments: starts `gru.exe --tray` next to it and exits."""

import os
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')  # let gru.exe unpack afresh
subprocess.Popen([os.path.join(os.path.dirname(sys.executable), 'gru.exe'), '--tray'], env=env,
                 creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS, close_fds=True)
