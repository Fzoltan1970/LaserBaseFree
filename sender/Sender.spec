# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['sender/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('sender/lang', 'lang'),
        ('defaults', 'defaults'),
    ],
    hiddenimports=['sender.sender_worker'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Sender',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='assets/app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Sender',
)