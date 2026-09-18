"""Include i testi delle licenze ufficiali nel pacchetto; cache locale riutilizzabile."""

from pathlib import Path
import platform
from urllib.request import urlopen


def collect(root: Path) -> Path:
    destination = root / "resources" / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    urls = {
        "Qt-LGPL-3.0.txt": "https://raw.githubusercontent.com/qt/qtbase/v6.11.2/LICENSES/LGPL-3.0-only.txt",
        "Qt-GPL-3.0.txt": "https://raw.githubusercontent.com/qt/qtbase/v6.11.2/LICENSES/GPL-3.0-only.txt",
        "Qt-GPL-exception.txt": "https://raw.githubusercontent.com/qt/qtbase/v6.11.2/LICENSES/Qt-GPL-exception-1.0.txt",
        "pyserial-BSD.txt": "https://raw.githubusercontent.com/pyserial/pyserial/v3.5/LICENSE.txt",
        "PyInstaller.txt": "https://raw.githubusercontent.com/pyinstaller/pyinstaller/v6.22.3/COPYING.txt",
        f"Python-{platform.python_version()}.txt": f"https://raw.githubusercontent.com/python/cpython/v{platform.python_version()}/LICENSE",
    }
    for name, url in urls.items():
        target = destination / name
        if target.exists() and target.stat().st_size > 100:
            continue
        with urlopen(url, timeout=30) as response:
            data = response.read()
        if len(data) < 100 or b"<html" in data.lower():
            raise RuntimeError(f"Licenza non disponibile: {url}")
        target.write_bytes(data)
    return destination
