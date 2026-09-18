"""Prepara i sorgenti riproducibili, escludendo dipendenze, cache e build locali."""

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {".gitignore", "AGENTS.md", "README.md", "THIRD_PARTY_NOTICES.md", "requirements.txt", "pyproject.toml", "run_app.py"}
FOLDERS = {".github", "blackboxdesk", "docs", "resources", "tests", "tools"}


def main():
    target = ROOT / "dist" / "Blackbox-Desk-sorgenti.zip"
    target.parent.mkdir(exist_ok=True)
    paths = [ROOT / name for name in TOP_FILES]
    for name in FOLDERS:
        paths.extend((ROOT / name).rglob("*"))
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            relative = path.relative_to(ROOT)
            if path.is_file() and not path.is_symlink() and "__pycache__" not in relative.parts and path.suffix != ".pyc":
                archive.write(path, Path("Blackbox-Desk-sorgenti") / relative)
    print(target)


if __name__ == "__main__":
    main()
