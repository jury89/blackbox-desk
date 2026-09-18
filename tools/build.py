"""Build locale per il sistema corrente; non effettua pubblicazioni."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from collect_licenses import collect


ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform not in ("darwin", "win32"):
        raise SystemExit("Compila su macOS o Windows.")
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
    # Il controllo completo precede sempre la build.
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, env=environment, check=True)
    licenses = collect(ROOT)
    assets = ROOT / "build" / "icons"
    assets.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    sys.path.insert(0, str(ROOT))
    from blackboxdesk.app import app_icon
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    icon = app_icon(1024)
    if sys.platform == "darwin":
        iconset = assets / "BlackboxDesk.iconset"
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                suffix = "@2x" if scale == 2 else ""
                icon.scaled(size * scale, size * scale, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(str(iconset / f"icon_{size}x{size}{suffix}.png"))
        icon_path = assets / "BlackboxDesk.icns"
        subprocess.run(["/usr/bin/iconutil", "-c", "icns", "-o", str(icon_path), str(iconset)], check=True)
    else:
        icon_path = assets / "BlackboxDesk.ico"
        if not icon.scaled(256, 256).save(str(icon_path), "ICO"):
            raise SystemExit("Creazione dell'icona Windows non riuscita.")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
               "--name", "Blackbox Desk", "--icon", str(icon_path), "--paths", str(ROOT),
               "--add-data", str(ROOT / "README.md") + os.pathsep + ".",
               "--add-data", str(ROOT / "THIRD_PARTY_NOTICES.md") + os.pathsep + ".",
               "--add-data", str(licenses) + os.pathsep + "licenses"]
    for name in ("PySide6-Essentials", "shiboken6", "pyserial"):
        command += ["--copy-metadata", name]
    if sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "local.jury.blackboxdesk", "--target-arch", "x86_64" if os.uname().machine == "x86_64" else "arm64"]
    command += [str(ROOT / "run_app.py")]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    if sys.platform == "darwin":
        artifact = ROOT / "dist" / "Blackbox Desk.app"
        executable = artifact / "Contents" / "MacOS" / "Blackbox Desk"
    else:
        artifact = ROOT / "dist" / "Blackbox Desk"
        executable = artifact / "Blackbox Desk.exe"
    subprocess.run([str(executable), "--smoke-test"], env=environment, timeout=30, check=True)
    if sys.platform == "darwin":
        archive = ROOT / "dist" / f"Blackbox-Desk-macOS-{os.uname().machine}.zip"
        subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(artifact), str(archive)], check=True)
    else:
        archive = Path(shutil.make_archive(str(ROOT / "dist" / "Blackbox-Desk-Windows-x64"), "zip", root_dir=ROOT / "dist", base_dir=artifact.name))
    print(f"Build e avvio verificati: {artifact}")
    print(f"Pacchetto distribuibile: {archive}")


if __name__ == "__main__":
    main()
