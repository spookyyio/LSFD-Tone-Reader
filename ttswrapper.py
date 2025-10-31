"""TTS worker encapsulation for ToneReader.

Provides a TTSWorker class that manages the pyttsx3 engine thread, queue,
and COM initialization on Windows. Designed to be imported by the GUI
module so the GUI doesn't need to manage threading/pyttsx3 details.
"""
import threading
import queue
import time
import traceback
import pyttsx3

try:
    import pythoncom
    _HAS_PYTHONCOM = True
except Exception:
    pythoncom = None
    _HAS_PYTHONCOM = False


class TTSWorker:
    def __init__(self, get_volume_callable=None, queue_maxsize=0):
        """Create a TTSWorker.

        get_volume_callable: callable that returns current volume (0.0-1.0).
        queue_maxsize: maxsize for internal queue (0 means infinite).
        """
        self.get_volume = get_volume_callable or (lambda: 1.0)
        self._tts_queue = queue.Queue(maxsize=queue_maxsize)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        # Exposed engine pointer (set when an engine is active)
        self.engine = None

    def start(self):
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self, timeout=2.0):
        try:
            self._stop.set()
            # Wake the worker
            try:
                self._tts_queue.put(None, block=False)
            except Exception:
                pass
            try:
                self._thread.join(timeout=timeout)
            except Exception:
                pass
        except Exception:
            pass

    def enqueue(self, text, ts=None, block=False, timeout=None):
        if ts is None:
            ts = time.time()
        try:
            self._tts_queue.put((text, ts), block=block, timeout=timeout)
        except Exception:
            # Best-effort: drop if cannot enqueue
            pass

    def _loop(self):
        """Internal worker loop. Mirrors the original behaviour from the
        monolithic script but scoped inside this class.
        """
        if _HAS_PYTHONCOM:
            try:
                pythoncom.CoInitialize()
            except Exception as e:
                print(f"[WARN] pythoncom.CoInitialize() failed: {e}")

        try:
            while not self._stop.is_set():
                try:
                    try:
                        item = self._tts_queue.get(timeout=0.4)
                    except queue.Empty:
                        continue

                    if item is None:
                        break

                    if isinstance(item, str):
                        text_item, ts = item, time.time()
                    else:
                        try:
                            text_item, ts = item
                        except Exception:
                            text_item, ts = str(item), time.time()

                    speak_time = float(ts) + 2.0
                    while (time.time() < speak_time) and (not self._stop.is_set()):
                        time.sleep(0.05)

                    if self._stop.is_set():
                        break

                    eng = None
                    try:
                        eng = pyttsx3.init()
                        self.engine = eng
                        try:
                            eng.setProperty('volume', float(self.get_volume() or 1.0))
                        except Exception:
                            pass
                        eng.say(text_item)
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
                        self.engine = None
                        time.sleep(0.05)

                except Exception:
                    traceback.print_exc()
                    time.sleep(0.2)
        finally:
            if _HAS_PYTHONCOM:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            self.engine = None
