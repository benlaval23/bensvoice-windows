"""BensVoice for Windows: a tray app with two hold-to-talk hotkeys.

Right Alt = dictate (local Parakeet), Right Ctrl = compose with Claude Haiku. Tap once for hands-free, tap again to finish.
"""
import logging
import queue
import sys
import threading
import time
import winreg
import winsound
from concurrent.futures import ThreadPoolExecutor

import pystray
from PIL import Image, ImageDraw

from . import composer, winapi
from .config import APP_DIR, CONFIG_PATH, load_config
from .recorder import Recorder

DICTATE, COMPOSE = "dictate", "compose"
TAP_THRESHOLD = 0.3
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class App:
    def __init__(self):
        config = load_config()
        dictate_key = config.get("dictateKey", "right alt")
        compose_key = config.get("composeKey", "right ctrl")
        self.keys = {winapi.KEY_NAMES[dictate_key]: DICTATE, winapi.KEY_NAMES[compose_key]: COMPOSE}
        self.key_labels = {DICTATE: dictate_key.title(), COMPOSE: compose_key.title()}

        self.recorder = Recorder()
        self.transcriber = None
        self.work = ThreadPoolExecutor(max_workers=1)
        self.events = queue.Queue()

        self.recording = None
        self.hands_free = False
        self.pressed_at = 0.0
        self.down = set()
        self.target_app = None
        self.busy = False
        self.status = "Starting…"
        self.icon_gen = 0
        self.icon_lock = threading.Lock()

        self.icon = pystray.Icon("BensVoice", icon_image("ready"), "BensVoice", menu=pystray.Menu(
            pystray.MenuItem(lambda _: self.status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Hold {self.key_labels[DICTATE]}: dictate", None, enabled=False),
            pystray.MenuItem(f"Hold {self.key_labels[COMPOSE]}: compose with Haiku", None, enabled=False),
            pystray.MenuItem("Quick tap = hands-free, Esc = cancel", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Launch at Login", self.toggle_login, checked=lambda _: login_enabled()),
            pystray.MenuItem("Open Settings Folder", lambda: open_folder()),
            pystray.MenuItem("Quit BensVoice", lambda: self.icon.stop()),
        ))

    def run(self):
        threading.Thread(target=self.process_keys, daemon=True, name="keys").start()
        winapi.start_keyboard_hook(lambda vk, down: self.events.put((vk, down)))
        self.work.submit(self.load_model)
        self.icon.run()

    def load_model(self):
        from .transcriber import Transcriber
        self.set_status("Loading Parakeet (first run downloads ~650 MB)…")
        self.start_spinner()
        try:
            t = Transcriber()
            t.warm_up()
            self.transcriber = t
            self.set_status("Ready")
        except Exception as e:
            logging.exception("Model failed")
            self.set_status(f"Model failed: {e}")
        self.set_icon("ready")

    # MARK: Hotkeys

    def process_keys(self):
        while True:
            vk, down = self.events.get()
            try:
                self.handle(vk, down)
            except Exception:
                logging.exception("Key handling failed")

    def handle(self, vk, down):
        repeat = down and vk in self.down
        (self.down.add if down else self.down.discard)(vk)
        mode = self.keys.get(vk)
        if mode is None:
            if not down or repeat:
                return
            if vk == winapi.VK_ESCAPE and self.recording:
                self.cancel()
            # Another key while holding the hotkey means it's a shortcut, not dictation.
            elif self.recording and not self.hands_free and vk not in winapi.MODIFIERS and self.hotkey_held():
                self.cancel()
            return

        if down:
            if repeat:
                return
            if vk in winapi.ALT_KEYS:
                winapi.tap(winapi.VK_MASK)  # otherwise releasing Alt opens the focused app's menu bar
            if self.recording:
                if self.hands_free and self.recording == mode:
                    self.finish()
            elif not self.busy:
                self.begin(mode)
        else:
            if self.recording != mode or self.hands_free:
                return
            if time.monotonic() - self.pressed_at < TAP_THRESHOLD:
                self.hands_free = True
                self.set_status(f"{'Dictating' if mode == DICTATE else 'Composing'} (tap {self.key_labels[mode]} to finish)")
            else:
                self.finish()

    def hotkey_held(self):
        return any(vk in self.down for vk, m in self.keys.items() if m == self.recording)

    def begin(self, mode):
        if self.transcriber is None:
            winsound.MessageBeep()
            return
        self.target_app = winapi.foreground_app_name()
        try:
            self.recorder.start()
        except Exception as e:
            logging.exception("Mic error")
            self.set_status(f"Mic error: {e}")
            return
        self.recording = mode
        self.hands_free = False
        self.pressed_at = time.monotonic()
        beep(880)
        self.set_icon(mode)
        self.set_status("Dictating…" if mode == DICTATE else "Composing…")

    def cancel(self):
        self.recorder.stop()
        self.recording = None
        self.hands_free = False
        self.set_icon("ready")
        self.set_status("Cancelled")

    def finish(self):
        mode = self.recording
        audio = self.recorder.stop()
        self.recording = None
        self.hands_free = False
        self.busy = True
        beep(660)
        self.start_spinner()
        self.set_status("Transcribing…" if mode == DICTATE else "Thinking…")
        # Grab the selection now: the hotkey is released, and focus is still in the target app.
        selection = winapi.selected_text() if mode == COMPOSE else None
        self.work.submit(self.complete, mode, audio, selection, self.target_app)

    def complete(self, mode, audio, selection, app_name):
        try:
            text = self.transcriber.transcribe(audio)
            if mode == COMPOSE and text:
                text = composer.compose(text, selection, app_name)
            if text:
                winapi.insert(text)
                self.set_status("Ready")
            else:
                self.set_status("Heard nothing")
        except Exception as e:
            logging.exception("Failed")
            self.set_status(f"Error: {e}")
            winsound.MessageBeep(winsound.MB_ICONHAND)
        finally:
            self.busy = False
            self.set_icon("ready")

    # MARK: Tray

    def toggle_login(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if login_enabled():
                    winreg.DeleteValue(k, "BensVoice")
                else:
                    winreg.SetValueEx(k, "BensVoice", 0, winreg.REG_SZ, launch_command())
        except OSError as e:
            self.set_status(f"Login item: {e}")

    def set_status(self, text):
        self.status = text
        self.icon.title = f"BensVoice: {text}"[:127]
        self.icon.update_menu()

    def set_icon(self, state):
        with self.icon_lock:
            self.icon_gen += 1  # stops any running spinner
            self.icon.icon = icon_image(state)

    def start_spinner(self):
        """Rotating arc in the tray while transcribing / waiting on Haiku."""
        with self.icon_lock:
            self.icon_gen += 1
            gen = self.icon_gen

        def spin():
            angle = 0
            while True:
                with self.icon_lock:
                    if self.icon_gen != gen:
                        return
                    self.icon.icon = icon_image("busy", angle)
                angle = (angle - 30) % 360
                time.sleep(1 / 12)
        threading.Thread(target=spin, daemon=True).start()


COLORS = {"ready": (60, 60, 67), "dictate": (220, 50, 47), "compose": (124, 77, 255), "busy": (60, 60, 67)}


def icon_image(state, angle=0):
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, s - 2, s - 2), fill=COLORS[state])
    white = (255, 255, 255)
    if state == "busy":
        d.arc((14, 14, s - 14, s - 14), angle, angle + 270, fill=white, width=6)
    elif state == "compose":
        # four-point sparkle
        c, r, w = s / 2, 20, 6
        d.polygon([(c, c - r), (c + w, c - w), (c + r, c), (c + w, c + w), (c, c + r), (c - w, c + w), (c - r, c), (c - w, c - w)], fill=white)
    else:
        # waveform bars (ready) or the same bars, louder, on red (dictating)
        heights = [10, 22, 32, 22, 10] if state == "ready" else [18, 30, 36, 30, 18]
        for i, h in enumerate(heights):
            x = 14 + i * 9
            d.rounded_rectangle((x, s / 2 - h / 2, x + 5, s / 2 + h / 2), radius=2.5, fill=white)
    return img


def beep(freq):
    threading.Thread(target=winsound.Beep, args=(freq, 60), daemon=True).start()


def launch_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pythonw}" -m bensvoice'


def login_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "BensVoice")
            return True
    except OSError:
        return False


def open_folder():
    import os
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text("{\n}\n", encoding="utf-8")
    os.startfile(APP_DIR)
