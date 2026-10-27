"""The Windows plumbing: a global low-level keyboard hook, clipboard save/restore, synthetic key presses."""
import ctypes
import os
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.EnumClipboardFormats.restype = wintypes.UINT
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE

WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
LLKHF_INJECTED = 0x10
KEYEVENTF_KEYUP = 0x2

VK_ESCAPE = 0x1B
VK_CONTROL = 0x11
VK_RCONTROL, VK_LCONTROL = 0xA3, 0xA2
VK_RMENU, VK_LMENU = 0xA5, 0xA4
VK_C, VK_V = 0x43, 0x56
VK_MASK = 0xE8  # unassigned key code, used to stop a lone Alt press from opening the app's menu bar
MODIFIERS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}
ALT_KEYS = {0x12, VK_LMENU, VK_RMENU}

KEY_NAMES = {"right alt": VK_RMENU, "left alt": VK_LMENU, "right ctrl": VK_RCONTROL, "left ctrl": VK_LCONTROL,
             "right shift": 0xA1, "right win": 0x5C, "caps lock": 0x14, "scroll lock": 0x91, "pause": 0x13,
             "insert": 0x2D, **{f"f{n}": 0x6F + n for n in range(1, 25)}}


def start_keyboard_hook(on_key):
    """Calls on_key(vk, is_down) for every physical key event, on a dedicated thread.

    The hook callback must return fast or Windows drops it, so it only forwards events; it never blocks keys.
    """
    def run():
        def proc(n_code, w_param, l_param):
            if n_code == 0:
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not kb.flags & LLKHF_INJECTED:  # ignore our own Ctrl+V / Ctrl+C
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        on_key(kb.vkCode, True)
                    elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                        on_key(kb.vkCode, False)
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        callback = HOOKPROC(proc)  # keep a reference so it isn't garbage collected
        if not user32.SetWindowsHookExW(13, callback, None, 0):  # WH_KEYBOARD_LL
            raise ctypes.WinError(ctypes.get_last_error())
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass

    threading.Thread(target=run, daemon=True, name="keyboard-hook").start()


def tap(vk):
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def ctrl_combo(vk):
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    tap(vk)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# MARK: Clipboard

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x2


class Clipboard:
    def __enter__(self):
        for _ in range(50):  # another app may briefly hold it
            if user32.OpenClipboard(None):
                return self
            time.sleep(0.01)
        raise OSError("Couldn't open the clipboard")

    def __exit__(self, *exc):
        user32.CloseClipboard()


def _set(fmt, data):
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(len(data), 1))
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    user32.SetClipboardData(fmt, h)


def save_clipboard():
    """Copies every memory-backed format so it can be put back after we paste (images, rich text, files...)."""
    saved = []
    with Clipboard():
        fmt = 0
        while fmt := user32.EnumClipboardFormats(fmt):
            if fmt in (2, 3, 14):  # CF_BITMAP, CF_METAFILEPICT, CF_ENHMETAFILE are GDI handles; Windows recreates them
                continue
            h = user32.GetClipboardData(fmt)
            if not h:
                continue
            p = kernel32.GlobalLock(h)
            if not p:
                continue
            try:
                saved.append((fmt, ctypes.string_at(p, kernel32.GlobalSize(h))))
            finally:
                kernel32.GlobalUnlock(h)
    return saved


def restore_clipboard(saved):
    with Clipboard():
        user32.EmptyClipboard()
        for fmt, data in saved:
            _set(fmt, data)


def set_clipboard_text(text, transient=True):
    with Clipboard():
        user32.EmptyClipboard()
        _set(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
        if transient:
            # Keep our temporary entry out of Win+V history and cloud clipboard.
            _set(user32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing"), b"\0")
            _set(user32.RegisterClipboardFormatW("CanIncludeInClipboardHistory"), (0).to_bytes(4, "little"))


def get_clipboard_text():
    with Clipboard():
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else None
        finally:
            kernel32.GlobalUnlock(h)


def clear_clipboard():
    with Clipboard():
        user32.EmptyClipboard()


def clipboard_sequence():
    return user32.GetClipboardSequenceNumber()


# MARK: Text insertion

def insert(text):
    """Pastes text into the focused field via a temporary clipboard swap, then restores the clipboard."""
    saved = save_clipboard()
    set_clipboard_text(text)
    seq = clipboard_sequence()
    ctrl_combo(VK_V)

    def restore():
        if clipboard_sequence() != seq:  # user copied something new meanwhile
            return
        try:
            restore_clipboard(saved) if saved else clear_clipboard()
        except OSError:
            pass
    threading.Timer(0.6, restore).start()


def selected_text():
    """Selected text in the focused app, by sending Ctrl+C and reading the clipboard (then putting it back)."""
    saved = save_clipboard()
    clear_clipboard()
    seq = clipboard_sequence()
    ctrl_combo(VK_C)
    deadline = time.time() + 0.3
    while clipboard_sequence() == seq and time.time() < deadline:
        time.sleep(0.02)
    text = get_clipboard_text() if clipboard_sequence() != seq else None
    restore_clipboard(saved) if saved else clear_clipboard()
    return text


def foreground_app_name():
    """'Slack', 'Outlook', 'WindowsTerminal'... from the focused window's executable."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None
        name = os.path.splitext(os.path.basename(buf.value))[0]
        return name.capitalize() if name.islower() or name.isupper() else name
    finally:
        kernel32.CloseHandle(h)


def single_instance():
    """False if BensVoice is already running."""
    kernel32.CreateMutexW(None, False, "BensVoiceWindowsSingleInstance")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
