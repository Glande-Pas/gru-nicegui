# gru-nicegui

Gru is a desktop app, the Elder Scrolls Online (ESO) add-on manager: get, remove, update add-ons from ESOUI.com.

It runs a [NiceGUI](https://nicegui.io) interface shown in a native window through
[pywebview](https://pywebview.flowrl.com), and uses the [gru](https://gitlab.com/glandepas/gru) command line tool
for the heavy lifting, inheriting its fancier features such as:
- scanning your folder for installed addons (so it can't _forget_ it installed any)
- persisting changes to addons across updates as patches

Gru is an independent, unofficial tool. It is not affiliated with, endorsed by, or sponsored by ZeniMax Online Studios,
Bethesda Softworks, ESOUI, Minion, or the Desplicable Me franchise.
The Elder Scrolls Online and ESOUI are trademarks of their respective owners.

Add-on hosting, organization, and moderation are handled entirely by ESOUI.com.
Gru's code is licensed under [EUPL-1.2](LICENSE.md).

## Getting started

1. Install Gru:
   - **Windows**: from the [Microsoft Store](https://apps.microsoft.com/detail/9P1251PBNJMM).
   - **Linux**: download `gru-x86_64.flatpak` (or `gru-aarch64.flatpak` on ARM) from the
     [latest release](https://github.com/Glande-Pas/gru-nicegui/releases/latest), then
     `flatpak install --user gru-x86_64.flatpak`.
   - **Python**: `pip install gru-nicegui`, then run `gru-app`. On Linux this also needs WebKitGTK, see [Linux](#linux).
2. Start it. On first start, you may need to open **Settings** and point it at your ESO `AddOns` folder, typically
   `Documents\Elder Scrolls Online\live\AddOns` on Windows.
3. **Installed Add-Ons** lists what you have and what can be updated; **Search** finds add-ons on ESOUI;
   **Patches** saves your own edits to add-ons so they can be re-applied after updates.

Settings, saved patches and the change log are kept in Gru's config folder, shared with the `gru` command line
tool: `%APPDATA%\gru` on Windows, `~/.config/gru` on Linux, `~/Library/Preferences/gru` on macOS.

## Troubleshooting

The interface is a local web page: the app serves it on `127.0.0.1` and pywebview shows it in a window using
the system's web engine. Most problems come from that engine, not from Gru.

### First steps

- **Read the console.** Start Gru from a terminal (`flatpak run io.github.Glande_Pas.Gru`, or `gru-app` for pip
  installs) to see pywebview's errors and the address the interface is served on:
  `NiceGUI ready to go on http://127.0.0.1:<port>`. The Microsoft Store version has no console.
- **Open that address in a browser.** If the page works there, the app is fine and the problem is the
  window; you can keep using the browser until it's fixed.
- **Get more detail** by starting the app with `PYWEBVIEW_LOG=debug` set in the environment. With Flatpak, pass
  environment variables as `flatpak run --env=PYWEBVIEW_LOG=debug io.github.Glande_Pas.Gru`.
- **Pick the backend yourself** with `PYWEBVIEW_GUI`: `gtk` on Linux, `edgechromium` on Windows.

### Windows

- **Blank, broken or old-looking window:** pywebview needs the
  [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (version 86 or
  later) and [.NET Framework](https://dotnet.microsoft.com/en-us/download/dotnet-framework) 4.6.2 or later.
  Without WebView2 it falls back to the deprecated Internet Explorer engine, which can't display this interface.
  Windows 10 and 11 normally ship WebView2; install the Evergreen runtime if it's missing.
- **SmartScreen warns about `gru.exe`:** Install from the Microsoft Store, or choose **More info** → **Run anyway**.

### Linux

The Flatpak ships WebKitGTK and uses it directly; the first two points only apply to pip installs.

- **"You must have either QT or GTK with Python extensions installed":** install WebKitGTK 4.1 and PyGObject, e.g.
  `libwebkit2gtk-4.1-0 gir1.2-webkit2-4.1 python3-gi` on Debian/Ubuntu, `webkit2gtk4.1 python3-gobject` on Fedora,
  `webkit2gtk-4.1 python-gobject` on Arch, or `pip install PyGObject`.
- **KDE:** pywebview tries Qt first on KDE, logs a harmless error if it's missing, and falls back to GTK.
  Set `PYWEBVIEW_GUI=gtk` to skip the attempt.
- **Blank or white window, or flickering** (typically NVIDIA drivers or Wayland): try, one at a time, setting
  `WEBKIT_DISABLE_DMABUF_RENDERER=1`, `WEBKIT_DISABLE_COMPOSITING_MODE=1`, or `GDK_BACKEND=x11`, e.g.
  `flatpak run --env=WEBKIT_DISABLE_DMABUF_RENDERER=1 io.github.Glande_Pas.Gru`.

# Running from source

```sh
pip install -e .
gru-app
```

This installs gru-eso from PyPI. To use a gru checkout instead, `pip install -e path/to/gru` first.
On Linux, pywebview also needs WebKitGTK and PyGObject, see [Linux](#linux).

## Building the executable

```sh
pip install -e ".[build]"
pyinstaller gru.spec    # writes dist/gru or dist/gru.exe
```

Builds keep a console window open for logs by default; set `GRU_CONSOLE=0` to build without one.
