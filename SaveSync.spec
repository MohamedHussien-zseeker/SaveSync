# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

a = Analysis(
    ['SaveSync.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'core', 'providers', 'state', 'logging_system',
        'cloud', 'config_sync', 'credential_store',
        'exceptions', 'transfer', 'customtkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter.test', 'PIL', 'Pillow', 'matplotlib',
              'numpy', 'pandas', 'scipy', 'cv2',
              'tkinterdnd2'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SaveSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=None,
)

app = BUNDLE(
    exe,
    name='SaveSync.app',
    icon=None,
    bundle_identifier=None,
)
