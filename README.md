# LSFD Tone Reader

> A small Windows utility that watches RAGE:MP log files (including
> the newer `client_resources/.storage/.../.storage` JSON) and speaks
> station-tone lines using your system TTS (pyttsx3 / SAPI).

Features
- Watches a chosen RAGE installation and prefers `.storage` profile files.
- Detects station-tone markers (e.g. "** [STATION TONE]") and reads only the spoken text.
- Uses a background TTS worker to make repeated Test Tone and live TTS reliable.
- Small GUI with a visible log, Test Tone, and Feed Line debug helper.

Requirements
- Windows (recommended for SAPI voices)
- Python 3.8+ (3.11/3.13 tested in development)
- Packages: pyttsx3, (optional) pywin32, (optional) comtypes

Quick start (run from source)
1. Create a virtualenv and activate it:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install pyttsx3
# optional (recommended) for more reliable COM init on Windows
pip install pywin32
```

3. Run the app:

```powershell
python tonereader.py
```

Usage notes
- Click Browse and select the top-level RAGE installation folder (the folder that contains `client_resources`).
- The app will prefer any `.storage` files under `client_resources/.storage/*` and will also search the whole selected folder for `.storage` files — it will not fallback to `console.txt` if a `.storage` is present.
- Use Test Tone to confirm TTS works repeatedly. Use Feed Line to paste sample lines for debugging.

Packaging to a Windows executable (PyInstaller)
- For debugging builds use `--onedir` so settings can be saved next to the exe. For a single-file build note that settings written beside the script will be written into a temp extraction folder and not persist across runs.

Example (recommended first pass):

```powershell
# create venv, install build deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pyinstaller pyttsx3 pywin32

# build a one-folder distribution (easier to debug / keep settings)
pyinstaller --noconfirm --onedir --windowed tonereader.py
```

If you prefer a single EXE (onefile):

```powershell
pyinstaller --noconfirm --onefile --windowed tonereader.py
```

Common packaging tips
- Add hidden imports if PyInstaller misses pyttsx3 drivers or COM libs: `--hidden-import=pyttsx3.drivers.sapi5 --hidden-import=comtypes --hidden-import=pythoncom`.
- Use a `.spec` file to include data files (`tonereader_settings.json`) and to control onefile vs onedir behavior.
- If TTS fails only in the packaged exe, run without `--windowed` to see console errors when debugging.

Settings storage note
- The app stores `tonereader_settings.json` next to the script by default. When using a onefile EXE this ends up in the temporary extraction dir and won't persist across runs. Use `--onedir` for persistent sidecar files or modify the code to store settings in `%APPDATA%`.

Troubleshooting
- No audio: ensure Windows voices are installed and system sound is working. Test with a small Python snippet using pyttsx3.
- pyttsx3 errors / COM init errors: install `pywin32` in the same environment used to build the exe; consider bundling `comtypes` as a fallback.
- App still picking console.txt: ensure the chosen RAGE folder actually contains a `.storage` file under `client_resources/.storage/` or elsewhere; use Browse -> select the RAGEMP root folder and the app will locate `.storage` automatically.

Contributing
- Fixes and improvements welcome. If you change the TTS backend, adjust worker COM initialization accordingly.

License
- MIT

Enjoy — let me know if you want a tailored `tonereader.spec` or a `requirements.txt` and I can add them to the repo and run a build for you.
