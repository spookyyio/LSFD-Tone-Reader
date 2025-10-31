# Building a Windows executable with PyInstaller

This project is packaged easily with PyInstaller. Below are PowerShell-friendly steps that were used successfully during development on Windows.

Quick build (single-file, windowed):

```powershell
# optional: create and activate a venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# install build deps
pip install --upgrade pip
pip install pyinstaller pyttsx3 pywin32

# build a single-file, windowed exe named ToneReader.exe
python -m PyInstaller --onefile --windowed --name ToneReader tonereader.py
```

Notes and recommended alternatives
- For easier debugging and to preserve sidecar files (like `tonereader_settings.json`), use `--onedir` instead of `--onefile`:

```powershell
python -m PyInstaller --onedir --windowed --name ToneReader tonereader.py
```

- If the built EXE fails to include pyttsx3 drivers or COM libs, add hidden imports:

```powershell
python -m PyInstaller --onefile --windowed --hidden-import=pyttsx3.drivers.sapi5 --hidden-import=comtypes --hidden-import=pythoncom --name ToneReader tonereader.py
```

- To include an .ico for the app, pass `--icon path\to\icon.ico` to PyInstaller.
- When debugging runtime errors from the packaged app, omit `--windowed` so a console appears and shows tracebacks.

Where to find the output
- On success PyInstaller writes the executable to `dist\ToneReader.exe` inside the project folder. A `.spec` and `build/` folder are also created.

Testing on other machines
- The EXE bundles the Python runtime, but it still depends on Windows system components for audio (SAPI). Test the EXE on a clean Windows machine to ensure voices and audio drivers are present.

If you want, I can add a `tonereader.spec` pre-configured with hidden imports and bundled data, or create an Inno Setup installer script to produce a Windows installer.
