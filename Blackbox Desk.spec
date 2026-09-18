# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import copy_metadata

datas = [('/Users/jury/jury/blackbox-desk/README.md', '.'), ('/Users/jury/jury/blackbox-desk/THIRD_PARTY_NOTICES.md', '.'), ('/Users/jury/jury/blackbox-desk/resources/licenses', 'licenses')]
datas += copy_metadata('PySide6-Essentials')
datas += copy_metadata('shiboken6')
datas += copy_metadata('pyserial')


a = Analysis(
    ['/Users/jury/jury/blackbox-desk/run_app.py'],
    pathex=['/Users/jury/jury/blackbox-desk'],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Blackbox Desk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='x86_64',
    codesign_identity=None,
    entitlements_file=None,
    icon=['/Users/jury/jury/blackbox-desk/build/icons/BlackboxDesk.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Blackbox Desk',
)
app = BUNDLE(
    coll,
    name='Blackbox Desk.app',
    icon='/Users/jury/jury/blackbox-desk/build/icons/BlackboxDesk.icns',
    bundle_identifier='local.jury.blackboxdesk',
)
