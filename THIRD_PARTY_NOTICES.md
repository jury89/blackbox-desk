# Componenti di terze parti

Blackbox Desk utilizza Python, PySide6 / Qt, shiboken6, pySerial e il bootloader PyInstaller.

- Python: Python Software Foundation License, https://docs.python.org/3/license.html
- PySide6 / Qt e shiboken6: licenze del progetto Qt, incluse LGPLv3 e GPLv3; https://www.qt.io/licensing/ e https://doc.qt.io/qtforpython-6/licenses.html
- pySerial: BSD 3-Clause, https://github.com/pyserial/pyserial/blob/master/LICENSE.txt
- PyInstaller: GPL con eccezione per il bootloader, https://pyinstaller.org/en/stable/license.html

I testi delle licenze sono inclusi nella cartella `licenses` del pacchetto. I framework Qt rimangono librerie condivise sostituibili nel pacchetto; nessuna restrizione aggiuntiva impedisce modifiche o reverse engineering per il debug delle librerie LGPL. I sorgenti dell'app e la procedura di ricostruzione sono consegnati insieme all'eseguibile.

Sorgenti ufficiali delle versioni delle librerie, incluse le rispettive attribuzioni e componenti di terze parti:

- Qt 6.11.2: https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/ e https://github.com/qt/qtbase/tree/v6.11.2
- PySide6 / shiboken6 6.11.2: https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.11.2
- pySerial 3.5: https://github.com/pyserial/pyserial/tree/v3.5
- PyInstaller 6.22.3: https://github.com/pyinstaller/pyinstaller/tree/v6.22.3
- CPython: https://github.com/python/cpython (la versione esatta è nel nome della licenza Python inclusa).

La prima build Mac usa Python 3.14.6. Le successive build includono la licenza corrispondente al proprio interprete. `tools/collect_licenses.py` scarica i testi ufficiali al primo build e li conserva per le build successive.
