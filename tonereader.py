import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from tkinter import font as tkfont
from tkinter import simpledialog
import time
import os
import re
import threading
import queue
import json
import pyttsx3
import utils
import settings

# Try to import pythoncom for proper COM initialization on Windows threads.
# If it's missing we'll continue but the user should install pywin32 for best results.
try:
    import pythoncom
    _HAS_PYTHONCOM = True
except Exception:
    pythoncom = None
    _HAS_PYTHONCOM = False

# config constants and helpers are in utils
KEYWORD = utils.KEYWORD
MARKER_RE = utils.MARKER_RE

class ToneReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RAGE Tone Reader")
        self.root.geometry("700x320")

        # --- class variables ---
        self.log_file_path = tk.StringVar()
        self.status_text = tk.StringVar()
        self.current_volume = tk.DoubleVar(value=1.0)
        self.watch_thread = None
        self.watcher = None
        self.stop_event = threading.Event()

        # TTS worker encapsulated in a separate module for readability.
        try:
            from ttswrapper import TTSWorker
            self.tts = TTSWorker(self.current_volume.get)
            self.tts.start()
        except Exception:
            # Fallback: if the module isn't available for any reason, expose
            # minimal placeholders so the rest of the code can still function
            # without crashing. This should not normally happen.
            self.tts = None

        # track last seen chat_log (for .storage JSON files) so we only speak new lines
        self._last_chat_log = None

        self.create_widgets()
        # Load last-used log from settings file (if any)
        try:
            last = settings.load_settings()
            if last:
                self.log_file_path.set(last)
                self.status_text.set(f"Loaded last log: {last}")
        except Exception:
            pass

        self.status_text.set("Ready. Select a RAGEMP folder and press Start.")
        if not _HAS_PYTHONCOM:
            # warn in UI so user knows COM init support is missing (Windows only)
            self.add_log_entry("[WARN] pythoncom not available. If you are on Windows and TTS is unreliable or not working, install pywin32.")

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill="both", expand=True)

        file_frame = ttk.Frame(main_frame)
        file_frame.pack(fill="x", pady=5)
        ttk.Label(file_frame, text="Log File:").pack(side="left", padx=5)
        self.path_entry = ttk.Entry(file_frame, textvariable=self.log_file_path, state="readonly", width=50)
        self.path_entry.pack(side="left", fill="x", expand=True)
        self.browse_button = ttk.Button(file_frame, text="Browse...", command=self.browse_file)
        self.browse_button.pack(side="left", padx=5)

        volume_frame = ttk.Frame(main_frame)
        volume_frame.pack(fill="x", pady=5)
        ttk.Label(volume_frame, text="Volume:").pack(side="left", padx=5)
        self.volume_slider = ttk.Scale(
            volume_frame, from_=0.0, to=1.0, variable=self.current_volume,
            orient="horizontal", command=self.set_volume)
        self.volume_slider.pack(side="left", fill="x", expand=True)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=20)
        self.start_button = ttk.Button(button_frame, text="Start Watching", command=self.start_watching)
        self.start_button.pack(side="left", fill="x", expand=True, padx=5)
        self.stop_button = ttk.Button(button_frame, text="Stop Watching", command=self.stop_watching, state="disabled")
        self.stop_button.pack(side="left", fill="x", expand=True, padx=5)
        self.test_button = ttk.Button(button_frame, text="Test Tone", command=self.test_tone)
        self.test_button.pack(side="left", padx=5)
        self.feed_button = ttk.Button(button_frame, text="Feed Line", command=self.feed_line)
        self.feed_button.pack(side="left", padx=5)
        self.append_button = ttk.Button(button_frame, text="Append Log", command=lambda: self.add_log_entry("[MANUAL] Manual entry"))
        self.append_button.pack(side="left", padx=5)

        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill="both", expand=True, pady=(0,5))
        ttk.Label(log_frame, text="Log:").pack(anchor="w")
        self.log_pane = ScrolledText(log_frame, height=12, state='disabled', wrap='word')
        try:
            font = tkfont.Font(family='Consolas', size=11)
            self.log_pane.configure(font=font)
        except Exception:
            pass
        self.log_pane.pack(fill="both", expand=True)
        try:
            self.log_pane.configure(bg='white', fg='black', insertbackground='black')
        except Exception:
            pass

        status_bar = ttk.Label(self.root, textvariable=self.status_text, relief="sunken", anchor="w", padding="5")
        status_bar.pack(side="bottom", fill="x")

        self._max_log_lines = 200
        self._tts_lock = threading.Lock()

        try:
            self.add_log_entry("[INFO] Ready")
        except Exception:
            pass

    def browse_file(self):
        selected_dir = filedialog.askdirectory(title="Select your RAGEMP folder (parent of clientdata)")
        if not selected_dir:
            return

        found = None
        # Prefer the new client_resources .storage location. Many RAGEMP
        # installs have a structure like:
        #  client_resources/.storage/<hexid>/.storage
        # We'll look for subfolders that look like the hex id and let the
        # user pick one if there are multiple.
        cr_dir = os.path.join(selected_dir, 'client_resources')
        if os.path.isdir(cr_dir):
            storage_root = os.path.join(cr_dir, '.storage')
            if os.path.isdir(storage_root):
                # Find candidate subfolders that contain a '.storage' file.
                # Historically these folders are named with a hex id, but
                # some installations may use different naming—so prefer any
                # subfolder that contains a '.storage' file rather than
                # enforcing a strict regex on the folder name.
                hex_dirs = []
                for sub in os.listdir(storage_root):
                    subpath = os.path.join(storage_root, sub)
                    if os.path.isdir(subpath):
                        # The actual storage file inside that folder is also named '.storage'
                        candidate = os.path.join(subpath, '.storage')
                        if os.path.exists(candidate):
                            hex_dirs.append((sub, candidate))

                if len(hex_dirs) == 1:
                    # Single match — pick it
                    found = hex_dirs[0][1]
                elif len(hex_dirs) > 1:
                    # Multiple matches — ask the user to pick which hex-id to watch
                    ids = [h[0] for h in hex_dirs]
                    choice = self._ask_pick_from_list("Choose .storage folder", "Multiple .storage profiles were found under client_resources/.storage. Pick the folder to watch:", ids)
                    if choice:
                        for h, cand in hex_dirs:
                            if h == choice:
                                found = cand
                                break

        if not found:
            # If we did not find a candidate in the expected
            # client_resources/.storage/* directories, search the
            # selected RAGEMP folder for any '.storage' file. Many
            # installs place the .storage file inside a profile
            # subfolder; be permissive and locate it recursively.
            storage_candidates = []
            for dirpath, dirnames, filenames in os.walk(selected_dir):
                # prefer files literally named '.storage'
                for fn in filenames:
                    if fn == '.storage':
                        storage_candidates.append(os.path.join(dirpath, fn))
                # small short-circuit if many found
                if len(storage_candidates) >= 20:
                    break

            if len(storage_candidates) == 1:
                found = storage_candidates[0]
            elif len(storage_candidates) > 1:
                # Let the user pick which .storage to watch
                choice = self._ask_pick_from_list(
                    "Choose .storage file",
                    "Multiple .storage files were found under the selected folder. Pick the file to watch:",
                    storage_candidates
                )
                if choice:
                    found = choice

        if found:
            self.log_file_path.set(found)
            self.status_text.set(f"Found log: {found}")
            self.save_settings()
            return

        if messagebox.askyesno("Log not found", "No console file found in the selected folder's clientdata. Do you want to select a log file manually?"):
            file_path = filedialog.askopenfilename(
                title="Select a log file",
                initialdir=selected_dir,
                filetypes=(('Log files', '*.log'), ('Text files', '*.txt'), ('All files', '*.*'))
            )
            if file_path:
                self.log_file_path.set(file_path)
                self.status_text.set("Log file selected. Ready to start.")
                try:
                    settings.save_settings(self.log_file_path.get())
                except Exception:
                    pass
                return

        self.status_text.set("No log file selected. Please choose a RAGEMP folder with clientdata/console.txt.")

    def add_log_entry(self, entry):
        def _append():
            try:
                timestamp = time.strftime("%H:%M:%S")
                line = f"[{timestamp}] {entry.strip()}\n"
                self.log_pane.config(state='normal')
                self.log_pane.insert('end', line)
                try:
                    total_lines = int(self.log_pane.index('end-1c').split('.')[0])
                except Exception:
                    total_lines = 0
                if total_lines > self._max_log_lines:
                    delete_to = total_lines - self._max_log_lines + 1
                    try:
                        self.log_pane.delete('1.0', f"{delete_to}.0")
                    except Exception:
                        print("[WARN] Failed to trim log pane")
                self.log_pane.see('end')
                self.log_pane.config(state='disabled')
                try:
                    self.log_pane.update_idletasks()
                except Exception:
                    pass
                print(f"[LOG] {entry}")
            except Exception:
                import traceback
                print("[ERROR] add_log_entry failed:")
                traceback.print_exc()

        try:
            if threading.current_thread() is threading.main_thread():
                _append()
            else:
                self.root.after(0, _append)
        except Exception:
            import traceback
            print("[ERROR] Scheduling add_log_entry failed:")
            traceback.print_exc()

    def _ask_pick_from_list(self, title, prompt, options):
        """Show a small modal dialog with a listbox to pick one option.

        Returns the chosen string or None if cancelled.
        """
        result = {'choice': None}

        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=10)
        frm.pack(fill='both', expand=True)

        ttk.Label(frm, text=prompt, wraplength=480).pack(anchor='w')

        lb = tk.Listbox(frm, height=min(10, max(3, len(options))))
        for opt in options:
            lb.insert('end', opt)
        lb.pack(fill='both', expand=True, pady=8)

        btn_frame = ttk.Frame(frm)
        btn_frame.pack(fill='x')

        def on_ok():
            sel = lb.curselection()
            if sel:
                result['choice'] = lb.get(sel[0])
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        ok = ttk.Button(btn_frame, text='OK', command=on_ok)
        ok.pack(side='left', padx=5)
        cancel = ttk.Button(btn_frame, text='Cancel', command=on_cancel)
        cancel.pack(side='left')

        # Double-click as accept
        def on_dbl(ev):
            on_ok()
        lb.bind('<Double-Button-1>', on_dbl)

        # Center over parent
        self.root.update_idletasks()
        dlg.update_idletasks()
        x = self.root.winfo_rootx() + 40
        y = self.root.winfo_rooty() + 40
        dlg.geometry(f'+{x}+{y}')

        self.root.wait_window(dlg)
        return result['choice']

    def test_tone(self):
        test_line = f"[{time.strftime('%H:%M:%S')}] {KEYWORD} Test tone"
        self.add_log_entry("[TEST] Triggering test tone")
        # Use cleaned speak call (we pass raw including KEYWORD, speak will clean it)
        self.speak(test_line)

    def feed_line(self):
        """Prompt the user to paste a raw line exactly as it appears in-game
        and run it through the same read/extract/speak logic. Useful for
        debugging when you can't easily produce an in-game line.
        """
        try:
            s = simpledialog.askstring("Feed line", "Paste a raw log line to feed:", parent=self.root)
            if not s:
                return
            # Log the raw fed line and run through speak (which strips marker)
            try:
                self.add_log_entry(f"[FEED] {s}")
            except Exception:
                pass
            # If there's a marker, extract after it; otherwise pass whole line
            m = MARKER_RE.search(s)
            if m:
                extracted = s[m.end():].strip()
            else:
                extracted = s.strip()
            if extracted:
                # Also log what will be spoken
                try:
                    self.add_log_entry(f"[SPEAKING] {extracted}")
                except Exception:
                    pass
                self.speak(extracted)
        except Exception:
            import traceback
            traceback.print_exc()

    def settings_path(self):
        # Left for backward-compat; recommend using settings.get_settings_path()
        return settings.get_settings_path()

    def load_settings(self):
        # Deprecated: Use module-level settings.load_settings()
        try:
            last = settings.load_settings()
            if last:
                self.log_file_path.set(last)
                self.status_text.set(f"Loaded last log: {last}")
        except Exception:
            pass

    def save_settings(self):
        # Deprecated: Use settings.save_settings(last_log_path)
        try:
            settings.save_settings(self.log_file_path.get())
        except Exception:
            pass

    def set_volume(self, val):
        """Try to set volume on the worker's engine if available; otherwise just keep var updated."""
        try:
            # Slider passes a string value; current_volume already bound so we read it.
            vol = self.current_volume.get()
            if vol is None:
                return
            # If worker has a live engine pointer, attempt to update its property.
            # This may silently fail if engine is None or not accessible.
            try:
                # If worker exposes a live engine, try to update its property.
                if getattr(self, 'tts', None) is not None and getattr(self.tts, 'engine', None) is not None:
                    try:
                        self.tts.engine.setProperty('volume', vol)
                    except Exception:
                        pass
            except Exception:
                # Not critical; main worker will set volume next utterance.
                pass
        except Exception as e:
            self.status_text.set(f"Error setting volume: {e}")

    def start_watching(self):
        if not self.log_file_path.get():
            self.status_text.set("Error: Please select a log file first.")
            return

        log_path = self.log_file_path.get()
        if not os.path.exists(log_path):
            self.status_text.set(f"Error: Log file not found: {log_path}")
            return

        self.status_text.set("Status: Watching for tones...")
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.browse_button.config(state="disabled")
        self.stop_event.clear()

        # Use Watcher class to follow the file in a background thread.
        try:
            from watcher import Watcher
            # on_message will be called from watcher thread; schedule speak on main thread
            def _on_message(msg):
                try:
                    self.root.after(0, self.speak, msg)
                except Exception:
                    pass

            self.watcher = Watcher(log_path, _on_message, self.add_log_entry, MARKER_RE, stop_event=self.stop_event)
            self.watcher.start()
        except Exception:
            # Fallback to legacy thread method if watcher import fails
            self.watch_thread = threading.Thread(target=self.follow_file_thread, daemon=True)
            self.watch_thread.start()

    def stop_watching(self, status_message=None):
        if status_message:
            self.status_text.set(status_message)
        else:
            self.status_text.set("Status: Stopped.")
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self.browse_button.config(state="normal")
        # Stop the watcher thread if present
        try:
            if getattr(self, 'watcher', None) is not None:
                try:
                    self.watcher.stop()
                except Exception:
                    pass
                self.watcher = None
        except Exception:
            pass
        self.stop_event.set()

    def follow_file_thread(self):
        # Delegate to watcher implementation (short wrapper). The heavy
        # follow-file logic was moved to watcher.py; this function acts as
        # a safe fallback in case `start_watching` attempted to use it.
        log_path = self.log_file_path.get()
        try:
            from watcher import Watcher

            # Use the Watcher._run() directly here because we're already
            # running inside a dedicated thread when this fallback is used.
            def _on_message(msg):
                try:
                    self.root.after(0, self.speak, msg)
                except Exception:
                    pass

            w = Watcher(log_path, _on_message, self.add_log_entry, MARKER_RE, stop_event=self.stop_event)
            # Run the watch loop in this thread (blocking) as a fallback.
            w._run()
        except Exception:
            try:
                self.add_log_entry("[ERROR] Fallback watcher failed to start; ensure watcher.py is present")
            except Exception:
                pass

    def handle_thread_error(self, message):
        self.stop_watching(status_message=message)

    def speak(self, text):
        """Cleans text and enqueues for the worker to speak."""
        if self.stop_event.is_set():
            return

        # Use centralized cleaner (removes marker, timestamps, and keyword)
        clean_text = utils.clean_text(text)

        if not clean_text:
            return

        # Log it
        try:
            self.add_log_entry(clean_text)
        except Exception:
            pass

        # Put into TTS queue together with an enqueue timestamp so the
        # worker can delay speaking by ~2 seconds from the time the line
        # was read. We put a tuple (text, ts) for robust timing.
        try:
            if getattr(self, 'tts', None) is not None:
                self.tts.enqueue(clean_text, time.time())
            else:
                # If TTS worker missing, attempt to use pyttsx3 directly as a best-effort.
                try:
                    eng = pyttsx3.init()
                    eng.setProperty('volume', self.current_volume.get())
                    eng.say(clean_text)
                    eng.runAndWait()
                    try:
                        eng.stop()
                    except Exception:
                        pass
                except Exception as e:
                    self.status_text.set(f"TTS error: {e}")
        except Exception as e:
            self.status_text.set(f"TTS queue error: {e}")

    def _tts_worker_loop(self):
        """
        The worker thread that speaks queued text.
        Important: initialize COM on this thread (pythoncom.CoInitialize) before using pyttsx3 on Windows.
        We'll create an engine per-utterance (robust) but ensure COM is initialized while engine exists.
        """
        import traceback, time

        # NOTE: TTS worker logic has been moved to `ttswrapper.TTSWorker`.
        # This stub remains to preserve compatibility but does nothing.
        return

    def _stop_tts_worker(self):
        try:
            if getattr(self, 'tts', None) is not None:
                try:
                    self.tts.stop()
                except Exception:
                    pass
        except Exception:
            pass

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to exit?"):
            self.stop_event.set()
            try:
                self._stop_tts_worker()
                # Stop watcher if present
                try:
                    if getattr(self, 'watcher', None) is not None:
                        self.watcher.stop()
                except Exception:
                    pass
            except Exception:
                pass
            self.root.destroy()

# --- Run the Application ---
if __name__ == "__main__":
    root = tk.Tk()
    app = ToneReaderApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
