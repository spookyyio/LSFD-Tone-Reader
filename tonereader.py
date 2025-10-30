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

# Try to import pythoncom for proper COM initialization on Windows threads.
# If it's missing we'll continue but the user should install pywin32 for best results.
try:
    import pythoncom
    _HAS_PYTHONCOM = True
except Exception:
    pythoncom = None
    _HAS_PYTHONCOM = False

# config
KEYWORD = "** STATION TONE"
MARKER_RE = re.compile(r"\*\*\s*\[?STATION\s+TONE\]?", re.IGNORECASE)

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
        self.stop_event = threading.Event()

        # TTS worker / queue
        self._tts_queue = queue.Queue()
        self._tts_worker_stop = threading.Event()
        self._tts_worker = threading.Thread(target=self._tts_worker_loop, daemon=True)
        # Exposed pointer to the worker's active engine object
        # It will be set from inside the worker thread, main thread may read it but should handle None.
        self.engine = None

        # start da worker
        self._tts_worker.start()

        # track last seen chat_log (for .storage JSON files) so we only speak new lines
        self._last_chat_log = None

        self.create_widgets()
        self.load_settings()

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
                self.save_settings()
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
        try:
            base = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base = os.getcwd()
        return os.path.join(base, 'tonereader_settings.json')

    def load_settings(self):
        path = self.settings_path()
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    last = data.get('last_log')
                    if last and os.path.exists(last):
                        self.log_file_path.set(last)
                        self.status_text.set(f"Loaded last log: {last}")
        except Exception:
            pass

    def save_settings(self):
        path = self.settings_path()
        try:
            data = {'last_log': self.log_file_path.get()}
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f)
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
                if self.engine is not None:
                    self.engine.setProperty('volume', vol)
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
        self.stop_event.set()

    def follow_file_thread(self):
        log_path = self.log_file_path.get()
        try:
            # Open file and monitor for truncation/replacement. Use bounded
            # reads so we can log small previews for debugging.
            file = open(log_path, 'rb')
            try:
                try:
                    file.seek(0, os.SEEK_END)
                except Exception:
                    pass

                try:
                    self.add_log_entry(f"[INFO] Watching file: {log_path}")
                except Exception:
                    pass

                # If this looks like a .storage JSON file, initialize our
                # last-seen chat_log so we don't immediately speak history.
                try:
                    with open(log_path, 'r', encoding='utf-8') as jf:
                        try:
                            data = json.load(jf)
                            chat = data.get('chat_log') if isinstance(data, dict) else None
                            if isinstance(chat, str):
                                self._last_chat_log = chat
                                try:
                                    self.add_log_entry(f"[DEBUG] Initialized chat_log length={len(chat)}")
                                except Exception:
                                    pass
                        except Exception:
                            # Not a JSON/.storage format or malformed; ignore
                            pass
                except Exception:
                    pass

                buffer = b''
                try:
                    last_stat = os.stat(log_path)
                except Exception:
                    last_stat = None

                while not self.stop_event.is_set():
                    # Detect rotation/truncation by checking file stat
                    try:
                        cur_stat = os.stat(log_path)
                    except Exception:
                        cur_stat = None

                    try:
                        cur_pos = None
                        try:
                            cur_pos = file.tell()
                        except Exception:
                            pass

                        if cur_stat and last_stat and cur_pos is not None:
                            if cur_stat.st_size < cur_pos:
                                try:
                                    self.add_log_entry("[DEBUG] File truncated; seeking to end")
                                except Exception:
                                    pass
                                try:
                                    file.seek(0, os.SEEK_END)
                                except Exception:
                                    pass

                            if cur_stat.st_mtime != last_stat.st_mtime or getattr(cur_stat, 'st_ino', None) != getattr(last_stat, 'st_ino', None):
                                # Reopen the file handle when replaced
                                try:
                                    file.close()
                                except Exception:
                                    pass
                                try:
                                    file = open(log_path, 'rb')
                                    file.seek(0, os.SEEK_END)
                                    try:
                                        self.add_log_entry("[DEBUG] File replaced; reopened handle")
                                    except Exception:
                                        pass
                                    # After reopening, try to parse .storage JSON and
                                    # only speak newly-added chat lines (if any).
                                    try:
                                        with open(log_path, 'r', encoding='utf-8') as jf:
                                            data = json.load(jf)
                                            chat = data.get('chat_log') if isinstance(data, dict) else None
                                            if isinstance(chat, str):
                                                prev = self._last_chat_log or ''
                                                if len(chat) > len(prev) and chat.startswith(prev):
                                                    new_part = chat[len(prev):]
                                                else:
                                                    # If we can't align, take last portion
                                                    new_part = chat
                                                # Process new lines for marker
                                                for L in new_part.split('\n'):
                                                    m2 = MARKER_RE.search(L)
                                                    if m2:
                                                        try:
                                                            self.add_log_entry(f"[READ] {L.strip()}")
                                                        except Exception:
                                                            pass
                                                        extracted2 = L[m2.end():].strip()
                                                        if extracted2:
                                                            self.root.after(0, self.speak, extracted2)
                                                self._last_chat_log = chat
                                    except Exception:
                                        pass
                                except Exception:
                                    time.sleep(0.5)
                                    last_stat = cur_stat
                                    time.sleep(0.1)
                                    continue

                        last_stat = cur_stat
                    except Exception:
                        pass

                    # Read new data in small chunks
                    try:
                        chunk = file.read(4096)
                    except Exception:
                        chunk = b''

                    if not chunk:
                        time.sleep(0.5)
                        continue

                    # Debug: log read size + small preview to aid diagnosis
                    try:
                        preview = chunk.decode('utf-8', errors='ignore')[:200].replace('\n', ' ')
                        self.add_log_entry(f"[DEBUG] Read {len(chunk)} bytes: {preview}")
                    except Exception:
                        pass

                    buffer += chunk
                    text = buffer.decode('utf-8', errors='ignore')

                    if '\n' in text:
                        parts = text.split('\n')
                        for line in parts[:-1]:
                            m = MARKER_RE.search(line)
                            if m:
                                try:
                                    self.add_log_entry(f"[READ] {line.strip()}")
                                except Exception:
                                    pass
                                extracted = line[m.end():].strip()
                                if extracted:
                                    self.root.after(0, self.speak, extracted)

                        remainder = parts[-1]
                        buffer = remainder.encode('utf-8', errors='ignore')
                    else:
                        m = MARKER_RE.search(text)
                        if m:
                            try:
                                self.add_log_entry(f"[READ] {text.strip()}")
                            except Exception:
                                pass
                            extracted = text[m.end():].strip()
                            if extracted:
                                self.root.after(0, self.speak, extracted)
                            buffer = b''
            finally:
                try:
                    file.close()
                except Exception:
                    pass
        except FileNotFoundError:
            self.root.after(0, self.handle_thread_error, "Error: Log file not found.")
        except Exception as e:
            self.root.after(0, self.handle_thread_error, f"Error: {e}")

    def handle_thread_error(self, message):
        self.stop_watching(status_message=message)

    def speak(self, text):
        """Cleans text and enqueues for the worker to speak."""
        if self.stop_event.is_set():
            return

        # If the incoming line still contains a marker, strip everything
        # before and including the marker so we only speak user text.
        m = MARKER_RE.search(text)
        if m:
            text = text[m.end():]

        # Clean timestamps and any leftover marker text
        clean_text = re.sub(r'\[\d{2}:\d{2}:\d{2}\]', '', text)
        # Also remove the literal KEYWORD if present as a fallback
        clean_text = clean_text.replace(KEYWORD, "")
        clean_text = clean_text.strip()

        if not clean_text:
            return

        # Log it
        try:
            self.add_log_entry(clean_text)
        except Exception:
            pass

        # Put into TTS queue
        try:
            self._tts_queue.put(clean_text, block=False)
        except queue.Full:
            # Rare: queue full; try again with blocking briefly
            try:
                self._tts_queue.put(clean_text, timeout=0.5)
            except Exception as e:
                self.status_text.set(f"TTS queue error: {e}")
        except Exception as e:
            self.status_text.set(f"TTS queue error: {e}")

    def _tts_worker_loop(self):
        """
        The worker thread that speaks queued text.
        Important: initialize COM on this thread (pythoncom.CoInitialize) before using pyttsx3 on Windows.
        We'll create an engine per-utterance (robust) but ensure COM is initialized while engine exists.
        """
        import traceback, time

        # Initialize COM on this thread if available (Windows/pywin32).
        if _HAS_PYTHONCOM:
            try:
                pythoncom.CoInitialize()
            except Exception as e:
                print(f"[WARN] pythoncom.CoInitialize() failed: {e}")

        try:
            while not self._tts_worker_stop.is_set():
                try:
                    try:
                        item = self._tts_queue.get(timeout=0.4)
                    except queue.Empty:
                        continue

                    # sentinel to stop immediately
                    if item is None:
                        break

                    # Create a fresh engine, set volume, speak, then stop and discard.
                    eng = None
                    try:
                        eng = pyttsx3.init()
                        # expose the engine pointer (main thread may attempt to set volume)
                        self.engine = eng
                        try:
                            eng.setProperty('volume', self.current_volume.get())
                        except Exception:
                            pass
                        eng.say(item)
                        eng.runAndWait()
                        try:
                            eng.stop()
                        except Exception:
                            pass
                    except Exception:
                        traceback.print_exc()
                        try:
                            if eng:
                                eng.stop()
                        except Exception:
                            pass
                    finally:
                        # Clear the engine pointer so main thread knows it's gone.
                        self.engine = None
                        # small pause to allow audio system to settle
                        time.sleep(0.05)

                except Exception:
                    traceback.print_exc()
                    time.sleep(0.2)
        finally:
            # Uninitialize COM if we initialized it earlier
            if _HAS_PYTHONCOM:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            # Ensure engine ref cleared
            self.engine = None

    def _stop_tts_worker(self):
        try:
            self._tts_worker_stop.set()
            # Wake the worker if blocked
            try:
                self._tts_queue.put(None, block=False)
            except Exception:
                pass
            try:
                self._tts_worker.join(timeout=2.0)
            except Exception:
                pass
        except Exception:
            pass

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to exit?"):
            self.stop_event.set()
            try:
                self._stop_tts_worker()
            except Exception:
                pass
            self.root.destroy()

# --- Run the Application ---
if __name__ == "__main__":
    root = tk.Tk()
    app = ToneReaderApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
