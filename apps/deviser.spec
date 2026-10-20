# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [('iptinfo', '.'), ('ipt2obj', '.'), ('ipt2step', '.'),
         ('ipt2devp', '.'), ('ipt2deva', '.'), ('ipt2devd', '.'),
         ('ipt2devx', '.')]
binaries = []
hiddenimports = ['uuid', 're', 'struct', 'datetime', 'argparse', 'json',
                'webbrowser', 'threading']

for pkg in ['zstandard', 'olefile']:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# only the 5 Qt modules we use; their .so deps pull the right Qt libs
for mod in ['PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtNetwork', 'PySide6.QtOpenGL']:
    hiddenimports.append(mod)

# Qt platform plugins (xcb for real desktops, offscreen for headless test)
import PySide6, os
_qtlib = os.path.join(os.path.dirname(PySide6.__file__), 'Qt', 'lib')
_plugins = os.path.join(os.path.dirname(PySide6.__file__), 'Qt', 'plugins')
for p in os.listdir(os.path.join(_plugins, 'platforms')):
    if p.endswith('.so'):
        binaries.append((os.path.join(_plugins, 'platforms', p), 'PySide6/Qt/plugins/platforms'))
# also imageformats (for PNG loading) and iconengines
for sub in ['imageformats', 'iconengines']:
    d = os.path.join(_plugins, sub)
    if os.path.isdir(d):
        for p in os.listdir(d):
            if p.endswith('.so'):
                binaries.append((os.path.join(d, p), f'PySide6/Qt/plugins/{sub}'))

a = Analysis(['deviser_qt.py'],
             pathex=[],
             binaries=binaries,
             datas=datas,
             hiddenimports=hiddenimports,
             hookspath=[],
             excludes=['PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtQuick3D',
                       'PySide6.QtDesigner', 'PySide6.QtPdf', 'PySide6.QtWebEngine',
                       'PySide6.QtCharts', 'PySide6.QtDataVisualization',
                       'PySide6.Qt3D', 'PySide6.QtMultimedia', 'PySide6.QtPositioning',
                       'PySide6.QtSensors', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
                       'PySide6.QtSerialPort', 'PySide6.QtTest', 'PySide6.QtXml',
                       'PySide6.QtSql', 'PySide6.QtSvg', 'PySide6.QtUiTools',
                       'PySide6.QtConcurrent', 'PySide6.QtStateMachine',
                       'PySide6.QtScxml', 'PySide6.QtHttpServer',
                       'PyQt5', 'tkinter', 'cadquery', 'OCP'],
             noarchive=False)
pyz = PYZ(a.pure)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.datas,
          [],
          name='Deviser',
          debug=False,
          strip=False,
          upx=False,
          console=False)
