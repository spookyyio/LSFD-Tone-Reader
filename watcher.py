import threading
import time
import os
import json


class Watcher:
    """Follows a log file and calls back when marker lines are found.

    on_message(text): called for each extracted message (not including marker/timestamp)
    add_log_entry(text): thread-safe logging function (tonereader.add_log_entry is safe)
    marker_re: compiled regex to find markers in lines
    """

    def __init__(self, path, on_message, add_log_entry, marker_re, stop_event=None):
        self.path = path
        self.on_message = on_message
        self.add_log_entry = add_log_entry
        self.marker_re = marker_re
        self.stop_event = stop_event or threading.Event()
        self._thread = None
        self._last_chat_log = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout=2.0):
        try:
            self.stop_event.set()
            if self._thread:
                self._thread.join(timeout=timeout)
        except Exception:
            pass

    def _run(self):
        log_path = self.path
        try:
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
                            pass
                except Exception:
                    pass

                buffer = b''
                try:
                    last_stat = os.stat(log_path)
                except Exception:
                    last_stat = None

                while not self.stop_event.is_set():
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
                                                new_part = ''
                                                if prev and chat.startswith(prev):
                                                    new_part = chat[len(prev):]
                                                else:
                                                    overlap = 0
                                                    try:
                                                        max_ol = min(len(prev), len(chat))
                                                        for i in range(max_ol, 0, -1):
                                                            if prev.endswith(chat[:i]):
                                                                overlap = i
                                                                break
                                                    except Exception:
                                                        overlap = 0

                                                    if overlap > 0:
                                                        new_part = chat[overlap:]
                                                    else:
                                                        try:
                                                            self.add_log_entry("[DEBUG] .storage alignment failed; skipping speaking to avoid duplicates")
                                                        except Exception:
                                                            pass
                                                        new_part = ''

                                                if new_part:
                                                    for L in new_part.split('\n'):
                                                        if not L:
                                                            continue
                                                        m2 = self.marker_re.search(L)
                                                        if m2:
                                                            try:
                                                                self.add_log_entry(f"[READ] {L.strip()}")
                                                            except Exception:
                                                                pass
                                                            extracted2 = L[m2.end():].strip()
                                                            if extracted2:
                                                                try:
                                                                    self.on_message(extracted2)
                                                                except Exception:
                                                                    pass

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

                    try:
                        chunk = file.read(4096)
                    except Exception:
                        chunk = b''

                    if not chunk:
                        time.sleep(0.5)
                        continue

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
                            m = self.marker_re.search(line)
                            if m:
                                try:
                                    self.add_log_entry(f"[READ] {line.strip()}")
                                except Exception:
                                    pass
                                extracted = line[m.end():].strip()
                                if extracted:
                                    try:
                                        self.on_message(extracted)
                                    except Exception:
                                        pass

                        remainder = parts[-1]
                        buffer = remainder.encode('utf-8', errors='ignore')
                    else:
                        m = self.marker_re.search(text)
                        if m:
                            try:
                                self.add_log_entry(f"[READ] {text.strip()}")
                            except Exception:
                                pass
                            extracted = text[m.end():].strip()
                            if extracted:
                                try:
                                    self.on_message(extracted)
                                except Exception:
                                    pass
                            buffer = b''
            finally:
                try:
                    file.close()
                except Exception:
                    pass
        except FileNotFoundError:
            try:
                self.add_log_entry("[ERROR] Log file not found.")
            except Exception:
                pass
        except Exception as e:
            try:
                self.add_log_entry(f"[ERROR] Watcher error: {e}")
            except Exception:
                pass
