# Third-Party Notices

This file lists third-party Python packages used by TimeLens and the license files collected from the clean virtual environment created for this project.

Generated from:

- `src/requirements.txt`
- `src/venv` package metadata

## Direct Dependencies

| Package | Version | License | Purpose | License files |
| --- | ---: | --- | --- | --- |
| pywin32 | 311 | Python Software Foundation License | Windows foreground window, process, registry, and icon APIs | `docs/third-party-licenses/pywin32-311/license.txt`<br>`docs/third-party-licenses/pywin32-311/license-2.txt`<br>`docs/third-party-licenses/pywin32-311/license-3.txt`<br>`docs/third-party-licenses/pywin32-311/License-4.txt` |
| psutil | 7.2.2 | BSD-3-Clause | Process inspection and executable path detection | `docs/third-party-licenses/psutil-7.2.2/LICENSE` |
| Flask | 3.1.3 | BSD-3-Clause | Local web dashboard and API server | `docs/third-party-licenses/Flask-3.1.3/LICENSE.txt` |
| pystray | 0.19.5 | LGPL-3.0-or-later | Windows system tray integration | `docs/third-party-licenses/pystray-0.19.5/COPYING`<br>`docs/third-party-licenses/pystray-0.19.5/COPYING.LGPL` |
| pillow | 12.2.0 | MIT-CMU | Image and icon handling | `docs/third-party-licenses/pillow-12.2.0/LICENSE` |

## Transitive Runtime Dependencies

| Package | Version | License | Required by / purpose | License files |
| --- | ---: | --- | --- | --- |
| blinker | 1.9.0 | MIT | Flask runtime dependency | `docs/third-party-licenses/blinker-1.9.0/LICENSE.txt` |
| click | 8.4.1 | BSD-3-Clause | Flask command/runtime dependency | `docs/third-party-licenses/click-8.4.1/LICENSE.txt` |
| colorama | 0.4.6 | BSD-3-Clause | Click Windows console dependency | `docs/third-party-licenses/colorama-0.4.6/LICENSE.txt` |
| itsdangerous | 2.2.0 | BSD-3-Clause | Flask runtime dependency | `docs/third-party-licenses/itsdangerous-2.2.0/LICENSE.txt` |
| Jinja2 | 3.1.6 | BSD-3-Clause | Flask template engine | `docs/third-party-licenses/Jinja2-3.1.6/LICENSE.txt` |
| MarkupSafe | 3.0.3 | BSD-3-Clause | Jinja2/Flask escaping support | `docs/third-party-licenses/MarkupSafe-3.0.3/LICENSE.txt` |
| Werkzeug | 3.1.8 | BSD-3-Clause | Flask WSGI/runtime dependency | `docs/third-party-licenses/Werkzeug-3.1.8/LICENSE.txt`<br>`docs/third-party-licenses/Werkzeug-3.1.8/ICON_LICENSE.md` |
| six | 1.17.0 | MIT | pystray compatibility dependency | `docs/third-party-licenses/six-1.17.0/LICENSE` |

## Release Packaging Notes

- Source releases should include this file, the project `LICENSE`, `src/requirements.txt`, and `docs/third-party-licenses/`.
- Binary releases should include `LICENSE.txt`, `THIRD_PARTY_NOTICES.txt`, and a copy of `docs/third-party-licenses/` next to `TimeLens.exe` or inside the release archive.
- `pystray` is licensed under LGPL-3.0-or-later. When distributing a packaged executable, keep the corresponding license texts and allow users to replace or relink the LGPL-covered component as required by that license.
- Icons extracted from locally installed applications are displayed at runtime only and are not packaged as third-party artwork in this repository.

This notice is a convenience summary and is not legal advice. The license files in `docs/third-party-licenses/` are the controlling texts where provided by the package distributions.
