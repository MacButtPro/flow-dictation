"""
Flow - PyQt6 Overlay UI
Wispr Flow-style floating pill + full Settings panel.
"""

import sys
import builtins
import math
import random
import threading
import time
import os
import json
import wave
import tempfile
import ctypes
import ctypes.wintypes
import pyaudio
import pyperclip

# ── LOGGING ───────────────────────────────────────────────────────────────────
import datetime
import ctypes.wintypes

# ── APP DATA DIRECTORY ────────────────────────────────────────────────────────
# When running as a PyInstaller .exe, __file__ points inside a temp extraction
# folder that is deleted on exit — put persistent files in AppData instead.
# When running as a plain script, keep files next to the script (dev mode).
if getattr(sys, "frozen", False):
    # Packaged .exe  →  %APPDATA%\Flow\
    _APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Flow")
else:
    # Dev / script mode  →  same folder as flow_ui.py
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

os.makedirs(_APP_DIR, exist_ok=True)

_LOG_PATH = os.path.join(_APP_DIR, "flow_log.txt")
_log_file = None

def console_print(*args, **kwargs):
    try:
        builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [
            arg.encode("ascii", errors="replace").decode("ascii")
            if isinstance(arg, str) else arg
            for arg in args
        ]
        builtins.print(*safe_args, **kwargs)

print = console_print

def _init_log():
    global _log_file
    try:
        _log_file = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)  # line-buffered
        _log_file.write(f"\n{'='*60}\n")
        _log_file.write(f"Flow started at {datetime.datetime.now()}\n")
        _log_file.write(f"{'='*60}\n")
    except Exception as e:
        print(f"⚠️  Could not open log file: {e}")

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        # Windows CMD (cp1252) can't display emoji — print ASCII-safe fallback
        print(line.encode("ascii", errors="replace").decode("ascii"))
    if _log_file:
        try:
            _log_file.write(line + "\n")
        except Exception:
            pass

# ── PASTE VIA SendInput (bypasses keyboard library hooks entirely) ─────────────
def _send_paste():
    """
    Send Ctrl+V using Windows SendInput API directly.
    This bypasses the keyboard library's suppress hook, which was causing
    the keyboard to freeze after a few pastes.
    """
    INPUT_KEYBOARD  = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL      = 0x11
    VK_V            = 0x56
    modifier_vks    = [0xA2, 0xA3, 0xA4, 0xA5, 0xA0, 0xA1, 0x5B, 0x5C]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.wintypes.WORD),
            ("wScan",       ctypes.wintypes.WORD),
            ("dwFlags",     ctypes.wintypes.DWORD),
            ("time",        ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("ki",   KEYBDINPUT),
            # Pad to 32 bytes so that sizeof(INPUT) == 40 on 64-bit Windows.
            # Windows MOUSEINPUT is 32 bytes (ULONG_PTR dwExtraInfo is 8-byte
            # aligned at offset 24).  If the union is only 24 bytes, SendInput
            # receives cbSize=32 instead of 40 and silently drops every event.
            ("_pad", ctypes.c_byte * 32),
        ]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("_input",)
        _fields_    = [("type", ctypes.wintypes.DWORD), ("_input", _INPUT_UNION)]

    release_inputs = [
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, dwFlags=KEYEVENTF_KEYUP))
        for vk in modifier_vks
    ]
    paste_inputs = [
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=VK_CONTROL)),
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=VK_V)),
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=VK_V,       dwFlags=KEYEVENTF_KEYUP)),
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=VK_CONTROL, dwFlags=KEYEVENTF_KEYUP)),
    ]
    inputs = (INPUT * (len(release_inputs) + len(paste_inputs)))(*(release_inputs + paste_inputs))
    n_sent = ctypes.windll.user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
    if n_sent != len(inputs):
        err = ctypes.windll.kernel32.GetLastError()
        log(f"  ⚠️  SendInput sent {n_sent}/{len(inputs)} events (GetLastError={err}, cbSize={ctypes.sizeof(INPUT)})")

def _send_text_unicode(text):
    if not text:
        return False
    try:
        INPUT_KEYBOARD = 1
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        modifier_vks = [0xA2, 0xA3, 0xA4, 0xA5, 0xA0, 0xA1, 0x5B, 0x5C, 0x11, 0x12, 0x10]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.wintypes.WORD),
                ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class _INPUT_UNION(ctypes.Union):
            _fields_ = [
                ("ki",   KEYBDINPUT),
                ("_pad", ctypes.c_byte * 32),  # match MOUSEINPUT so INPUT = 40 bytes
            ]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("_input",)
            _fields_ = [("type", ctypes.wintypes.DWORD), ("_input", _INPUT_UNION)]

        events = []
        for vk in modifier_vks:
            events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, dwFlags=KEYEVENTF_KEYUP)))
        for ch in text:
            code_unit = ord(ch)
            events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wScan=code_unit, dwFlags=KEYEVENTF_UNICODE)))
            events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wScan=code_unit, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)))
        inputs = (INPUT * len(events))(*events)
        ctypes.windll.user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
        return True
    except Exception:
        return False

def _send_paste_message(hwnd):
    if not hwnd:
        return False
    try:
        WM_PASTE = 0x0302
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.wintypes.ULONG_PTR()
        ok = ctypes.windll.user32.SendMessageTimeoutW(
            hwnd,
            WM_PASTE,
            0,
            0,
            SMTO_ABORTIFHUNG,
            200,
            ctypes.byref(result),
        )
        return bool(ok)
    except Exception:
        return False

def _get_window_class_name(hwnd):
    if not hwnd:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, len(buf))
        return buf.value or ""
    except Exception:
        return ""

def _get_uiautomation():
    try:
        import comtypes.client
        from comtypes.gen import UIAutomationClient
        auto = comtypes.client.CreateObject(UIAutomationClient.CUIAutomation8)
        return auto, UIAutomationClient
    except Exception:
        return None, None

def _uia_element_from_point(point):
    if not point:
        return None, "", ""
    auto, UIAutomationClient = _get_uiautomation()
    if not auto or not UIAutomationClient:
        return None, "", ""
    try:
        pt = UIAutomationClient.tagPOINT(point[0], point[1])
        element = auto.ElementFromPoint(pt)
        if not element:
            return None, "", ""
        return element, (element.CurrentClassName or ""), (element.CurrentName or "")
    except Exception:
        return None, "", ""

def _uia_focus_point(point):
    element, class_name, name = _uia_element_from_point(point)
    if not element:
        return False, class_name, name
    try:
        element.SetFocus()
        time.sleep(0.03)
        return True, class_name, name
    except Exception:
        return False, class_name, name

def _uia_set_value_at_point(point, text):
    if not point or not text:
        return False, "", ""
    auto, UIAutomationClient = _get_uiautomation()
    if not auto or not UIAutomationClient:
        return False, "", ""
    element, class_name, name = _uia_element_from_point(point)
    if not element:
        return False, class_name, name
    try:
        pattern = element.GetCurrentPattern(UIAutomationClient.UIA_ValuePatternId)
        if pattern:
            try:
                value_pattern = pattern.QueryInterface(UIAutomationClient.IUIAutomationValuePattern)
                if not value_pattern.CurrentIsReadOnly:
                    value_pattern.SetValue(text)
                    return True, class_name, name
            except Exception:
                pass
    except Exception:
        pass
    try:
        pattern = element.GetCurrentPattern(UIAutomationClient.UIA_LegacyIAccessiblePatternId)
        if pattern:
            try:
                legacy_pattern = pattern.QueryInterface(UIAutomationClient.IUIAutomationLegacyIAccessiblePattern)
                legacy_pattern.SetValue(text)
                return True, class_name, name
            except Exception:
                pass
    except Exception:
        pass
    return False, class_name, name

def _get_focused_control(hwnd):
    if not hwnd:
        return 0
    try:
        user32 = ctypes.windll.user32
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("flags", ctypes.wintypes.DWORD),
                ("hwndActive", ctypes.wintypes.HWND),
                ("hwndFocus", ctypes.wintypes.HWND),
                ("hwndCapture", ctypes.wintypes.HWND),
                ("hwndMenuOwner", ctypes.wintypes.HWND),
                ("hwndMoveSize", ctypes.wintypes.HWND),
                ("hwndCaret", ctypes.wintypes.HWND),
                ("rcCaret", RECT),
            ]

        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if target_tid and user32.GetGUIThreadInfo(target_tid, ctypes.byref(info)):
            return int(info.hwndFocus or 0)
    except Exception:
        pass
    return 0

def _focus_window(hwnd):
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        parent_hwnd = user32.GetAncestor(hwnd, 2)
        current_hwnd = user32.GetForegroundWindow()
        current_tid = user32.GetWindowThreadProcessId(current_hwnd, None) if current_hwnd else 0
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        this_tid = ctypes.windll.kernel32.GetCurrentThreadId()

        attached_to_current = False
        attached_to_target = False
        try:
            if current_tid and current_tid != this_tid:
                attached_to_current = bool(user32.AttachThreadInput(this_tid, current_tid, True))
            if target_tid and target_tid != this_tid:
                attached_to_target = bool(user32.AttachThreadInput(this_tid, target_tid, True))

            if parent_hwnd:
                user32.SetForegroundWindow(parent_hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
            time.sleep(0.03)
            return user32.GetFocus() == hwnd or user32.GetForegroundWindow() == parent_hwnd
        finally:
            if attached_to_target:
                user32.AttachThreadInput(this_tid, target_tid, False)
            if attached_to_current:
                user32.AttachThreadInput(this_tid, current_tid, False)
    except Exception:
        return False

def _get_cursor_pos():
    try:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return (int(pt.x), int(pt.y))
    except Exception:
        pass
    return None

def _window_from_point(point):
    if not point:
        return 0
    try:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT(point[0], point[1])
        return ctypes.windll.user32.WindowFromPoint(pt)
    except Exception:
        return 0

def _click_point(point):
    if not point:
        return False
    try:
        INPUT_MOUSE = 0
        MOUSEEVENTF_MOVE = 0x0001
        MOUSEEVENTF_ABSOLUTE = 0x8000
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        SM_CXSCREEN = 0
        SM_CYSCREEN = 1

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.wintypes.LONG),
                ("dy", ctypes.wintypes.LONG),
                ("mouseData", ctypes.wintypes.DWORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class _INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("_input",)
            _fields_ = [("type", ctypes.wintypes.DWORD), ("_input", _INPUT_UNION)]

        user32 = ctypes.windll.user32
        screen_w = max(1, user32.GetSystemMetrics(SM_CXSCREEN) - 1)
        screen_h = max(1, user32.GetSystemMetrics(SM_CYSCREEN) - 1)
        x, y = point
        abs_x = int(x * 65535 / screen_w)
        abs_y = int(y * 65535 / screen_h)
        current_pos = _get_cursor_pos()
        inputs = (INPUT * 3)(
            INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx=abs_x, dy=abs_y, dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)),
            INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dwFlags=MOUSEEVENTF_LEFTDOWN)),
            INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dwFlags=MOUSEEVENTF_LEFTUP)),
        )
        user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
        if current_pos:
            user32.SetCursorPos(current_pos[0], current_pos[1])
        return True
    except Exception:
        return False

def _get_foreground_window():
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return 0

def _restore_window(hwnd):
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        SW_RESTORE = 9
        ASFW_ANY = 0xFFFFFFFF
        current_hwnd = user32.GetForegroundWindow()
        current_tid = user32.GetWindowThreadProcessId(current_hwnd, None) if current_hwnd else 0
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        this_tid = ctypes.windll.kernel32.GetCurrentThreadId()

        user32.AllowSetForegroundWindow(ASFW_ANY)
        user32.ShowWindow(hwnd, SW_RESTORE)

        attached_to_current = False
        attached_to_target = False
        try:
            if current_tid and current_tid != this_tid:
                attached_to_current = bool(user32.AttachThreadInput(this_tid, current_tid, True))
            if target_tid and target_tid != this_tid:
                attached_to_target = bool(user32.AttachThreadInput(this_tid, target_tid, True))

            user32.BringWindowToTop(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.05)
            return user32.GetForegroundWindow() == hwnd
        finally:
            if attached_to_target:
                user32.AttachThreadInput(this_tid, target_tid, False)
            if attached_to_current:
                user32.AttachThreadInput(this_tid, current_tid, False)
    except Exception:
        return False


# ── PROPER WINDOWS HOTKEY MANAGER ─────────────────────────────────────────────
# Uses WH_KEYBOARD_LL with CallNextHookEx (no suppress) + a real message pump.
# Keys pass through normally to every other app — nothing ever gets swallowed.

WH_KEYBOARD_LL = 13
WM_KEYDOWN     = 0x0100
WM_KEYUP       = 0x0101
WM_SYSKEYDOWN  = 0x0104
WM_SYSKEYUP    = 0x0105
WM_QUIT        = 0x0012

# Map friendly names → Windows VK codes
_NAME_TO_VK = {
    "right alt":   0xA5,  "left alt":    0xA4,
    "right ctrl":  0xA3,  "left ctrl":   0xA2,
    "right shift": 0xA1,  "left shift":  0xA0,
    "right win":   0x5C,  "left win":    0x5B,
    "space":       0x20,  "enter":       0x0D,
    "tab":         0x09,  "backspace":   0x08,
    "delete":      0x2E,  "insert":      0x2D,
    "home":        0x24,  "end":         0x23,
    "page up":     0x21,  "page down":   0x22,
    "up":          0x26,  "down":        0x28,
    "left":        0x25,  "right":       0x27,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},   # F1–F24
    **{chr(c).lower(): c for c in range(0x41, 0x5B)},  # a–z
    **{str(i): 0x30 + i for i in range(10)},            # 0–9
}

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      ctypes.wintypes.DWORD),
        ("scanCode",    ctypes.wintypes.DWORD),
        ("flags",       ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int,
    ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
)

_call_next_hook_ex = ctypes.windll.user32.CallNextHookEx
_call_next_hook_ex.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
_call_next_hook_ex.restype = ctypes.c_ssize_t

# Reverse map: VK code → friendly name (for capture mode reporting)
_VK_TO_NAME = {v: k for k, v in _NAME_TO_VK.items()}

# Keys that would break shortcuts if used as a hotkey
_BANNED_HOTKEYS = {
    "left ctrl", "right ctrl",
    "left shift", "right shift",
    "left alt",   # right alt is fine
    "left win",   "right win",
}

class HotkeyManager:
    """
    Installs a WH_KEYBOARD_LL hook on its own thread with a proper message pump.
    Calls CallNextHookEx so all keys pass through — zero interference with other apps.
    Also supports capture mode: temporarily captures the NEXT key pressed (any key)
    and reports it via a callback. Works regardless of which window has focus.
    """
    def __init__(self):
        self._hook            = None
        self._hook_proc       = None
        self._thread          = None
        self._thread_id       = None
        self._vk              = None
        self._on_press        = None
        self._on_release      = None
        self._key_down        = False
        self._capture_cb      = None   # set during capture mode

    def register(self, key_name, on_press, on_release):
        """Register a new hotkey. Safe to call from any thread."""
        vk = _NAME_TO_VK.get(key_name.lower())
        if vk is None:
            log(f"⚠️  HotkeyManager: unknown key '{key_name}'")
            return
        log(f"🎹 HotkeyManager.register('{key_name}', vk=0x{vk:02X})")
        self._capture_cb = None   # cancel any active capture
        self._vk         = vk
        self._on_press   = on_press
        self._on_release = on_release
        self._key_down   = False
        self._restart_thread()

    def start_capture(self, callback):
        """
        Enter capture mode: the next key pressed (any key) is passed to callback(key_name).
        Uses the global hook so it works even when the settings window isn't focused.
        """
        log("🎹 HotkeyManager: capture mode ON — waiting for any key")
        self._capture_cb = callback

    def cancel_capture(self):
        """Cancel capture mode without firing the callback."""
        log("🎹 HotkeyManager: capture mode cancelled")
        self._capture_cb = None

    def unregister(self):
        """Stop the hook thread cleanly."""
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2)
        self._thread_id = None
        self._thread    = None

    def _restart_thread(self):
        self.unregister()
        self._thread = threading.Thread(target=self._hook_thread, daemon=True,
                                        name="HotkeyHookThread")
        self._thread.start()

    def _hook_thread(self):
        """Runs the low-level hook with its own GetMessage pump."""
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        log(f"🔗 Hook thread started (tid={self._thread_id}, vk=0x{self._vk:02X})")

        def _proc(nCode, wParam, lParam):
            if nCode >= 0:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents

                # Ignore injected keys (SendInput) — LLKHF_INJECTED = bit 4.
                LLKHF_INJECTED = 0x10
                if kb.flags & LLKHF_INJECTED:
                    return ctypes.windll.user32.CallNextHookEx(
                        self._hook, nCode, wParam, lParam)

                # ── Capture mode: grab the next keydown, any key ──────────────
                if self._capture_cb and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    key_name = _VK_TO_NAME.get(kb.vkCode)
                    log(f"🎹 Capture: vk=0x{kb.vkCode:02X} → '{key_name}'")
                    if key_name and key_name not in _BANNED_HOTKEYS:
                        cb = self._capture_cb
                        self._capture_cb = None
                        threading.Thread(target=cb, args=(key_name,),
                                         daemon=True, name="CaptureCallback").start()
                    elif key_name in _BANNED_HOTKEYS:
                        log(f"  ⛔ '{key_name}' is banned — waiting for another key")
                        # stay in capture mode, let the UI show warning
                        threading.Thread(
                            target=lambda: self._capture_cb and
                                signals.capture_banned_key.emit(key_name)
                            if hasattr(signals, 'capture_banned_key') else None,
                            daemon=True).start()
                    # pass key through regardless
                    return ctypes.windll.user32.CallNextHookEx(
                        self._hook, nCode, wParam, lParam)

                # ── Normal hotkey mode ────────────────────────────────────────
                if kb.vkCode == self._vk:
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN) and not self._key_down:
                        self._key_down = True
                        log(f"⬇ Hotkey press (vk=0x{kb.vkCode:02X})")
                        if self._on_press:
                            threading.Thread(target=self._on_press,
                                             daemon=True, name="OnPress").start()
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP) and self._key_down:
                        self._key_down = False
                        log(f"⬆ Hotkey release (vk=0x{kb.vkCode:02X})")
                        if self._on_release:
                            threading.Thread(target=self._on_release,
                                             daemon=True, name="OnRelease").start()

            # ALWAYS pass through — never suppress anything
            return ctypes.windll.user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

        self._hook_proc = HOOKPROC(_proc)
        self._hook = ctypes.windll.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._hook_proc, None, 0)

        if not self._hook:
            log(f"❌ SetWindowsHookExW failed: {ctypes.GetLastError()}")
            return

        log("✅ Hook installed — message pump running")
        msg = ctypes.wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

        ctypes.windll.user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        log("🔌 Hook thread exiting cleanly")


_MODIFIER_KEYS = {
    "left ctrl", "right ctrl",
    "left shift", "right shift",
    "left alt", "right alt",
    "left win", "right win",
}

_GENERIC_MODIFIERS = {
    "ctrl": {"left ctrl", "right ctrl"},
    "alt": {"left alt", "right alt"},
    "shift": {"left shift", "right shift"},
    "win": {"left win", "right win"},
}

_MODIFIER_ORDER = ["ctrl", "alt", "shift", "win"]
_ALLOWED_SINGLE_MODIFIERS = {"right alt"}
_BANNED_HOTKEYS = _MODIFIER_KEYS - _ALLOWED_SINGLE_MODIFIERS

def _normalize_hotkey_string(hotkey):
    if not hotkey:
        return ""
    parts = [part.strip().lower() for part in hotkey.split("+") if part.strip()]
    return "+".join(parts)

def _display_hotkey(hotkey):
    parts = [part for part in _normalize_hotkey_string(hotkey).split("+") if part]
    return "+".join(part.title() for part in parts) if parts else "Right Alt"

def _is_valid_hotkey_token(token):
    return token in _NAME_TO_VK or token in _GENERIC_MODIFIERS

def _is_modifier_token(token):
    return token in _GENERIC_MODIFIERS or token in _MODIFIER_KEYS

def _modifier_token_pressed(token, pressed_keys):
    if token in _GENERIC_MODIFIERS:
        return any(key in pressed_keys for key in _GENERIC_MODIFIERS[token])
    return token in pressed_keys

def _normalize_token(token):
    token = token.strip().lower()
    if token in _GENERIC_MODIFIERS:
        return token
    for generic, members in _GENERIC_MODIFIERS.items():
        if token in members:
            return generic
    return token

def _normalize_hotkey_parts(tokens):
    tokens = [token.strip().lower() for token in tokens if token and token.strip()]
    if not tokens or any(not _is_valid_hotkey_token(token) for token in tokens):
        return None

    if len(tokens) == 1:
        token = tokens[0]
        if token in _BANNED_HOTKEYS:
            return None
        return {"parts": [token], "modifiers": [], "trigger": token, "normalized": token}

    parts = []
    for token in tokens:
        normalized = _normalize_token(token)
        if normalized not in parts:
            parts.append(normalized)

    if len(parts) < 2:
        return None

    for token in parts[:-1]:
        if not _is_modifier_token(token):
            return None

    trigger = parts[-1]
    modifiers = parts[:-1]
    return {"parts": parts, "modifiers": modifiers, "trigger": trigger, "normalized": "+".join(parts)}

def _parse_hotkey(hotkey):
    normalized = _normalize_hotkey_string(hotkey)
    return _normalize_hotkey_parts(normalized.split("+")) if normalized else None

def _actual_pressed_to_combo(pressed_keys, trigger_key):
    trigger_token = _normalize_token(trigger_key)
    modifiers = []
    for modifier in _MODIFIER_ORDER:
        if any(actual in pressed_keys for actual in _GENERIC_MODIFIERS[modifier]):
            if modifier != trigger_token:
                modifiers.append(modifier)
    return "+".join(modifiers + [trigger_token]) if modifiers else trigger_token

def _pressed_modifiers_to_combo(pressed_keys):
    modifiers = []
    for modifier in _MODIFIER_ORDER:
        if any(actual in pressed_keys for actual in _GENERIC_MODIFIERS[modifier]):
            modifiers.append(modifier)
    return "+".join(modifiers) if len(modifiers) >= 2 else None

class ComboHotkeyManager:
    def __init__(self):
        self._hook = None
        self._hook_proc = None
        self._thread = None
        self._thread_id = None
        self._hotkey_spec = None
        self._on_press = None
        self._on_release = None
        self._combo_active = False
        self._pressed_keys = set()
        self._capture_cb = None
        self._capture_keys = set()

    def register(self, hotkey, on_press, on_release):
        spec = _parse_hotkey(hotkey)
        if spec is None:
            log(f"⚠️  HotkeyManager: invalid hotkey '{hotkey}'")
            return
        log(f"🎹 HotkeyManager.register('{spec['normalized']}')")
        self._capture_cb = None
        self._capture_keys.clear()
        self._pressed_keys.clear()
        self._hotkey_spec = spec
        self._on_press = on_press
        self._on_release = on_release
        self._combo_active = False
        self._restart_thread()

    def start_capture(self, callback):
        log("🎹 HotkeyManager: capture mode ON — waiting for combo")
        self._capture_cb = callback
        self._capture_keys.clear()

    def cancel_capture(self):
        log("🎹 HotkeyManager: capture mode cancelled")
        self._capture_cb = None
        self._capture_keys.clear()

    def unregister(self):
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2)
        self._thread_id = None
        self._thread = None

    def _restart_thread(self):
        self.unregister()
        self._thread = threading.Thread(target=self._hook_thread, daemon=True,
                                        name="HotkeyHookThread")
        self._thread.start()

    def _hook_thread(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        hotkey_name = self._hotkey_spec["normalized"] if self._hotkey_spec else "none"
        log(f"🔗 Hook thread started (tid={self._thread_id}, hotkey='{hotkey_name}')")

        def _proc(nCode, wParam, lParam):
            if nCode >= 0:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                key_name = _VK_TO_NAME.get(kb.vkCode)

                # Ignore keys injected by SendInput (e.g. our own Ctrl+V paste).
                # LLKHF_INJECTED (bit 4) is set on every SendInput keystroke.
                LLKHF_INJECTED = 0x10
                if kb.flags & LLKHF_INJECTED:
                    return _call_next_hook_ex(self._hook, nCode, wParam, lParam)

                if self._capture_cb and key_name:
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        # Skip key-repeat events (key already tracked as held).
                        if key_name in self._capture_keys:
                            return _call_next_hook_ex(self._hook, nCode, wParam, lParam)
                        self._capture_keys.add(key_name)
                        log(f"🎹 Capture: vk=0x{kb.vkCode:02X} → '{key_name}'")
                        if key_name not in _MODIFIER_KEYS:
                            combo = _actual_pressed_to_combo(self._capture_keys, key_name)
                            cb = self._capture_cb
                            self._capture_cb = None
                            self._capture_keys.clear()
                            threading.Thread(target=cb, args=(combo,),
                                             daemon=True, name="CaptureCallback").start()
                        else:
                            combo = _pressed_modifiers_to_combo(self._capture_keys)
                            if combo:
                                cb = self._capture_cb
                                self._capture_cb = None
                                self._capture_keys.clear()
                                threading.Thread(target=cb, args=(combo,),
                                                 daemon=True, name="CaptureCallback").start()
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        if key_name in self._capture_keys:
                            if key_name in _ALLOWED_SINGLE_MODIFIERS and self._capture_keys == {key_name}:
                                cb = self._capture_cb
                                self._capture_cb = None
                                self._capture_keys.clear()
                                threading.Thread(target=cb, args=(key_name,),
                                                 daemon=True, name="CaptureCallback").start()
                            elif key_name in _BANNED_HOTKEYS and self._capture_keys == {key_name}:
                                log(f"  ⛔ '{key_name}' needs another key — waiting for combo")
                                threading.Thread(
                                    target=lambda: self._capture_cb and
                                        signals.capture_banned_key.emit(key_name)
                                    if hasattr(signals, 'capture_banned_key') else None,
                                    daemon=True).start()
                            self._capture_keys.discard(key_name)
                    return _call_next_hook_ex(self._hook, nCode, wParam, lParam)

                if self._hotkey_spec and key_name:
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._pressed_keys.add(key_name)
                        if not self._combo_active and self._combo_matches():
                            self._combo_active = True
                            log(f"⬇ Hotkey press ({self._hotkey_spec['normalized']})")
                            if self._on_press:
                                threading.Thread(target=self._on_press,
                                                 daemon=True, name="OnPress").start()
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        releasing_combo = self._combo_active and self._key_affects_combo(key_name)
                        self._pressed_keys.discard(key_name)
                        if releasing_combo:
                            self._combo_active = False
                            log(f"⬆ Hotkey release ({self._hotkey_spec['normalized']})")
                            if self._on_release:
                                threading.Thread(target=self._on_release,
                                                 daemon=True, name="OnRelease").start()

            return _call_next_hook_ex(self._hook, nCode, wParam, lParam)

        self._hook_proc = HOOKPROC(_proc)
        self._hook = ctypes.windll.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._hook_proc, None, 0)

        if not self._hook:
            log(f"❌ SetWindowsHookExW failed: {ctypes.GetLastError()}")
            return

        log("✅ Hook installed — message pump running")
        msg = ctypes.wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

        ctypes.windll.user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        log("🔌 Hook thread exiting cleanly")

    def _combo_matches(self):
        if not self._hotkey_spec:
            return False
        if not _modifier_token_pressed(self._hotkey_spec["trigger"], self._pressed_keys):
            return False
        return all(_modifier_token_pressed(modifier, self._pressed_keys)
                   for modifier in self._hotkey_spec["modifiers"])

    def _key_affects_combo(self, key_name):
        if not self._hotkey_spec:
            return False
        if key_name == self._hotkey_spec["trigger"]:
            return True
        return any(
            key_name == modifier or key_name in _GENERIC_MODIFIERS.get(modifier, set())
            for modifier in self._hotkey_spec["modifiers"]
        )

HotkeyManager = ComboHotkeyManager

from PyQt6.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu,
    QTabWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QCheckBox,
    QListWidget, QListWidgetItem, QFrame, QRadioButton,
)
from PyQt6.QtCore import (Qt, QTimer, QObject, QThread,
                           pyqtSignal, QRect, QEvent)
from PyQt6.QtGui import (QPainter, QColor, QFont, QPen,
                          QBrush, QPainterPath, QIcon, QPixmap, QAction)

# ── CONFIG FILE ───────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(_APP_DIR, "flow_config.json")

DEFAULT_CONFIG = {
    "hotkey":                "right alt",
    "context":               "general",
    "cleanup_enabled":       False,
    "cleanup_engine":        "openai",      # "openai" or "ollama"
    "openai_api_key":        "",
    "openai_model":          "gpt-4o-mini",
    "ollama_model":          "llama3.1:8b",
    "whisper_model_override": "",           # "" = auto-detect
    "launch_at_startup":     False,
    "dictionary":            {},            # {"wrong": "right"}
    "history":               [],            # last 30 transcriptions
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(saved)
            return cfg
        except Exception as e:
            print(f"⚠️  Could not load config ({e}) — using defaults")
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"⚠️  Could not save config: {e}")

cfg = load_config()

# ── HARDWARE DETECTION ────────────────────────────────────────────────────────
def detect_whisper_model():
    """Detect best Whisper model for this machine.
    Called ONLY from the worker thread — never at module load, so torch/CUDA
    initialisation never blocks or crashes the main process."""
    override = cfg.get("whisper_model_override", "")
    if override:
        print(f"🖥️  Using model override: {override}")
        return override, "cpu"   # device resolved properly in _load_model
    try:
        import torch
        if torch.cuda.is_available():
            vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            gpu  = torch.cuda.get_device_name(0)
            if vram >= 10:   model = "large-v3"
            elif vram >= 6:  model = "medium"
            else:            model = "small"
            print(f"🖥️  GPU: {gpu} ({vram:.1f} GB VRAM) → Whisper {model}")
            return model, "cuda"
        else:
            print("🖥️  No CUDA GPU — Whisper small on CPU")
            return "small", "cpu"
    except Exception as e:
        print(f"⚠️  GPU detection failed ({e}) — defaulting to Whisper small on CPU")
        return "small", "cpu"

# Module-level sentinel — actual value resolved in the worker thread at runtime.
WHISPER_MODEL = cfg.get("whisper_model_override", "") or "small"

CONTEXT_LABELS = {
    "general": "General", "email": "Email",
    "slack": "Slack", "code": "Code", "notes": "Notes",
}

CONTEXT_PROMPTS = {
    "general": "Clean up this dictated speech with a very light touch. Only remove filler words (um, uh, like, you know, sort of), fix obvious stutters or repeated words, and add basic punctuation. Do NOT rephrase or rewrite. Keep every word unless it is clearly a filler. Output ONLY the cleaned text.",
    "email":   "Polish this dictated text into a professional email. Fix grammar, remove fillers, add punctuation. Output ONLY the cleaned text.",
    "slack":   "Clean up this Slack message. Remove fillers, fix errors, keep casual tone. Output ONLY the cleaned text.",
    "code":    "Clean up this technical dictation for code comments or docs. Output ONLY the cleaned text.",
    "notes":   "Lightly clean this dictated note. Remove fillers, fix punctuation. Output ONLY the cleaned text.",
}

# ── COLORS ────────────────────────────────────────────────────────────────────
COL_BG           = QColor(12, 12, 14, 245)
COL_BORDER_IDLE  = QColor(255, 255, 255, 28)
COL_BORDER_REC   = QColor(239, 68, 68, 80)
COL_BORDER_PROC  = QColor(139, 92, 246, 80)
COL_BORDER_DONE  = QColor(34, 197, 94, 70)
COL_WAVE_REC     = QColor(255, 255, 255, 220)
COL_TEXT_IDLE    = QColor(255, 255, 255, 160)
COL_TEXT_PROC    = QColor(167, 139, 250, 230)
COL_TEXT_DONE    = QColor(34, 197, 94, 230)
COL_ICON_BG_IDLE = QColor(18, 10, 30, 230)   # dark purple-black, matches .ico bg
COL_ICON_BG_REC  = QColor(40,  8,  8, 230)   # dark red-black for recording
COL_ICON_BG_PROC = QColor(139, 92, 246, 38)
COL_ICON_BG_DONE = QColor(34, 197, 94, 30)
COL_BADGE_BG     = QColor(100, 60, 200,  90)   # more opaque purple fill
COL_BADGE_TEXT   = QColor(230, 220, 255, 255)   # near-white so it reads clearly
COL_BADGE_BORD   = QColor(167, 139, 250, 180)   # bright violet border
COL_TIMER        = QColor(255, 255, 255, 70)

# ── SETTINGS STYLESHEET ───────────────────────────────────────────────────────
QSS = """
QWidget { font-family: 'Segoe UI'; }
QLabel  { color: rgba(255,255,255,0.85); font-size: 13px; }

QTabWidget::pane {
    background: #0c0c0e;
    border: none;
}
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: rgba(255,255,255,0.4);
    padding: 10px 22px;
    font-size: 13px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected  { color: #ffffff; border-bottom: 2px solid #8b5cf6; }
QTabBar::tab:hover:!selected { color: rgba(255,255,255,0.65); }

QLineEdit {
    background: #1a1a1e; border: 1px solid rgba(255,255,255,0.1);
    border-radius: 7px; color: white; padding: 8px 12px; font-size: 13px;
}
QLineEdit:focus { border: 1px solid rgba(139,92,246,0.7); }
QLineEdit::placeholder { color: rgba(255,255,255,0.25); }

QPushButton#Primary {
    background: #8b5cf6; border: none; border-radius: 7px;
    color: white; font-size: 13px; font-weight: 600; padding: 8px 20px;
}
QPushButton#Primary:hover   { background: #7c3aed; }
QPushButton#Primary:pressed { background: #6d28d9; }

QPushButton#Secondary {
    background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 7px; color: rgba(255,255,255,0.8); font-size: 13px; padding: 8px 18px;
}
QPushButton#Secondary:hover { background: rgba(255,255,255,0.11); }

QPushButton#Danger {
    background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.22);
    border-radius: 7px; color: rgba(239,68,68,0.9); font-size: 12px; padding: 7px 14px;
}
QPushButton#Danger:hover { background: rgba(239,68,68,0.22); }

QPushButton#CtxBtn {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 7px; color: rgba(255,255,255,0.55); font-size: 12px; padding: 6px 14px;
}
QPushButton#CtxBtn:checked {
    background: rgba(139,92,246,0.22); border: 1px solid rgba(139,92,246,0.5);
    color: #c4b5fd;
}
QPushButton#CtxBtn:hover:!checked { background: rgba(255,255,255,0.09); color: rgba(255,255,255,0.8); }

QPushButton#HotkeyBtn {
    background: #1a1a1e; border: 1px solid rgba(255,255,255,0.1);
    border-radius: 7px; color: white; font-size: 13px; padding: 8px 20px; min-width: 210px;
}
QPushButton#HotkeyBtn:checked {
    border: 1px solid rgba(139,92,246,0.7); background: rgba(139,92,246,0.15); color: #c4b5fd;
}

QCheckBox { color: rgba(255,255,255,0.85); font-size: 13px; spacing: 9px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid rgba(255,255,255,0.2); background: #1a1a1e;
}
QCheckBox::indicator:checked { background: #8b5cf6; border-color: #8b5cf6; }

QRadioButton { color: rgba(255,255,255,0.8); font-size: 13px; spacing: 9px; }
QRadioButton::indicator {
    width: 17px; height: 17px; border-radius: 9px;
    border: 1.5px solid rgba(255,255,255,0.22); background: #1a1a1e;
}
QRadioButton::indicator:checked { background: #8b5cf6; border-color: #8b5cf6; }

QComboBox {
    background: #1a1a1e; border: 1px solid rgba(255,255,255,0.1);
    border-radius: 7px; color: white; padding: 7px 12px; font-size: 13px; min-width: 140px;
}
QComboBox:focus { border: 1px solid rgba(139,92,246,0.6); }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #1a1a1e; border: 1px solid rgba(255,255,255,0.1);
    color: white; selection-background-color: #8b5cf6; outline: none;
}

QListWidget {
    background: #111113; border: 1px solid rgba(255,255,255,0.07);
    border-radius: 9px; color: rgba(255,255,255,0.8); font-size: 13px;
    padding: 4px; outline: none;
}
QListWidget::item { padding: 9px 12px; border-radius: 6px; }
QListWidget::item:selected { background: rgba(139,92,246,0.22); color: white; }
QListWidget::item:hover:!selected { background: rgba(255,255,255,0.05); }

QScrollBar:vertical { background: transparent; width: 5px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.13); border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""

# ── SIGNALS ───────────────────────────────────────────────────────────────────
class FlowSignals(QObject):
    start_recording    = pyqtSignal()
    stop_recording     = pyqtSignal()
    set_processing     = pyqtSignal()
    set_done           = pyqtSignal(str)
    set_idle           = pyqtSignal()
    error              = pyqtSignal(str)
    open_settings      = pyqtSignal()
    history_updated    = pyqtSignal(list)
    loading_status     = pyqtSignal(str)
    loading_complete   = pyqtSignal()
    hotkey_captured    = pyqtSignal(str)   # emitted by hook thread → main thread
    capture_banned_key = pyqtSignal(str)   # emitted when a banned key is pressed during capture

signals = FlowSignals()


# ── SPLASH SCREEN ─────────────────────────────────────────────────────────────
class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._status    = "Starting up…"
        self._dots      = 0
        self._alpha     = 0.0
        self._fading    = False
        self._bars      = [0.15] * 10
        self._phases    = [random.uniform(0, math.pi * 2) for _ in range(10)]
        self._spin      = 0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(420, 260)
        self._center()

        # Fade-in timer
        self._fade_timer = QTimer()
        self._fade_timer.timeout.connect(self._fade_in_tick)
        self._fade_timer.start(16)

        # Animation timer
        self._anim_timer = QTimer()
        self._anim_timer.timeout.connect(self._anim_tick)
        self._anim_timer.start(16)

        signals.loading_status.connect(self._on_status)
        signals.loading_complete.connect(self._on_complete)
        self.show()

    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2,
                  (screen.height() - self.height()) // 2)

    def _on_status(self, text):
        self._status = text
        self.update()

    def _on_complete(self):
        self._fading  = True
        self._status  = "Ready!"

    def _fade_in_tick(self):
        if not self._fading:
            if self._alpha < 1.0:
                self._alpha = min(1.0, self._alpha + 0.05)
                self.setWindowOpacity(self._alpha)
        else:
            self._alpha = max(0.0, self._alpha - 0.06)
            self.setWindowOpacity(self._alpha)
            if self._alpha <= 0:
                self._fade_timer.stop()
                self._anim_timer.stop()
                self.close()

    def _anim_tick(self):
        self._spin = (self._spin + 4) % 360
        for i in range(10):
            self._phases[i] += 0.07 + i * 0.004
            t = max(0.1, math.sin(self._phases[i]) * 0.5 + 0.5)
            self._bars[i] += (t - self._bars[i]) * 0.12
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # Background card
        path = QPainterPath()
        path.addRoundedRect(2, 2, W - 4, H - 4, 20, 20)
        p.fillPath(path, QBrush(QColor(12, 12, 14, 252)))
        p.setPen(QPen(QColor(139, 92, 246, 60), 1.0))
        p.drawPath(path)

        # Subtle purple glow at top
        glow = QColor(139, 92, 246, 18)
        glow_path = QPainterPath()
        glow_path.addRoundedRect(2, 2, W - 4, 80, 20, 20)
        p.fillPath(glow_path, QBrush(glow))

        # ── Waveform bars (center) ───────────────────────────────────────────
        bars, bar_w, gap = 10, 4, 5
        total_w = bars * bar_w + (bars - 1) * gap
        bx0 = (W - total_w) // 2
        cy  = 110
        max_h = 36
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(bars):
            h   = max(4, self._bars[i] * max_h)
            bx  = bx0 + i * (bar_w + gap)
            col = QColor(167, 139, 250, int(100 + self._bars[i] * 155))
            p.setBrush(QBrush(col))
            p.drawRoundedRect(int(bx), int(cy - h / 2), bar_w, int(h), 2, 2)

        # ── "Flow" title ──────────────────────────────────────────────────────
        p.setPen(QColor(255, 255, 255, 240))
        font = QFont("Segoe UI", 28, QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(QRect(0, 130, W, 44), Qt.AlignmentFlag.AlignHCenter, "Flow")

        # ── Subtitle ──────────────────────────────────────────────────────────
        p.setPen(QColor(139, 92, 246, 180))
        font2 = QFont("Segoe UI", 11)
        p.setFont(font2)
        p.drawText(QRect(0, 170, W, 24), Qt.AlignmentFlag.AlignHCenter,
                   "Voice Dictation")

        # ── Status text ───────────────────────────────────────────────────────
        p.setPen(QColor(255, 255, 255, 100))
        font3 = QFont("Segoe UI", 10)
        p.setFont(font3)
        p.drawText(QRect(0, 210, W, 24), Qt.AlignmentFlag.AlignHCenter,
                   self._status)

        # ── Spinner ring (bottom) ─────────────────────────────────────────────
        r = 10
        cx2, cy2 = W // 2, 238
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(139, 92, 246, 35), 2.0,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawEllipse(cx2 - r, cy2 - r, r * 2, r * 2)
        p.setPen(QPen(QColor(167, 139, 250, 210), 2.0,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(cx2 - r, cy2 - r, r * 2, r * 2, self._spin * 16, 90 * 16)

        p.end()


# ── SETTINGS WINDOW ───────────────────────────────────────────────────────────
class SettingsWindow(QWidget):
    def __init__(self, worker_ref=None):
        super().__init__()
        self.worker_ref         = worker_ref
        self.hotkey_capturing   = False
        self._capture_done_at   = 0.0   # monotonic timestamp of last successful capture
        self._drag_pos          = None
        self._build_ui()
        self._load_into_ui()
        QApplication.instance().applicationStateChanged.connect(self._on_app_state_changed)
        signals.history_updated.connect(self._refresh_history)
        signals.hotkey_captured.connect(self._on_key_captured)
        signals.capture_banned_key.connect(self._on_banned_key)
        # Note: app-wide eventFilter is installed dynamically during hotkey capture only

    def _build_ui(self):
        self.setWindowTitle("Flow Settings")
        self.setFixedSize(500, 660)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Outer card
        self.card = QFrame(self)
        self.card.setStyleSheet("""
            QFrame {
                background: #0c0c0e;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 16px;
            }
        """)
        root.addWidget(self.card)

        card_l = QVBoxLayout(self.card)
        card_l.setContentsMargins(0, 0, 0, 16)
        card_l.setSpacing(0)

        # Title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(56)
        tbl = QHBoxLayout(title_bar)
        tbl.setContentsMargins(22, 0, 16, 0)

        icon = QLabel("🎤")
        icon.setStyleSheet("font-size: 18px; background: transparent; border: none;")
        title = QLabel("Flow Settings")
        title.setStyleSheet("color: white; font-size: 15px; font-weight: 600; background: transparent; border: none;")

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.07); border: none;
                border-radius: 15px; color: rgba(255,255,255,0.45); font-size: 12px;
            }
            QPushButton:hover { background: rgba(239,68,68,0.35); color: white; }
        """)
        close_btn.clicked.connect(self.hide)

        tbl.addWidget(icon)
        tbl.addSpacing(8)
        tbl.addWidget(title)
        tbl.addStretch()
        tbl.addWidget(close_btn)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background: rgba(255,255,255,0.07); border: none;")

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setContentsMargins(0, 0, 0, 0)
        self.tabs.addTab(self._tab_general(),    "  General  ")
        self.tabs.addTab(self._tab_cleanup(),    "  Cleanup  ")
        self.tabs.addTab(self._tab_dictionary(), "  Dictionary  ")
        self.tabs.addTab(self._tab_history(),    "  History  ")

        card_l.addWidget(title_bar)
        card_l.addWidget(div)
        card_l.addWidget(self.tabs)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _section(self, text):
        l = QLabel(text.upper())
        l.setStyleSheet("""
            color: rgba(255,255,255,0.32);
            font-size: 10px;
            letter-spacing: 1.8px;
            font-weight: 700;
            background: transparent;
            border: none;
        """)
        return l

    def _divider(self):
        f = QFrame()
        f.setFixedHeight(1)
        f.setStyleSheet("background: rgba(255,255,255,0.06); border: none;")
        return f

    def _card(self):
        f = QFrame()
        f.setStyleSheet("""
            QFrame {
                background: #111113;
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 10px;
            }
        """)
        return f

    # ── General tab ──────────────────────────────────────────────────────────
    def _tab_general(self):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        l = QVBoxLayout(w)
        l.setContentsMargins(22, 20, 22, 20)
        l.setSpacing(6)

        # Hotkey
        l.addWidget(self._section("Recording Hotkey"))
        l.addSpacing(8)
        hk_row = QHBoxLayout()
        self.hotkey_btn = QPushButton(_display_hotkey(cfg["hotkey"]))
        self.hotkey_btn.setObjectName("HotkeyBtn")
        self.hotkey_btn.setCheckable(True)
        self.hotkey_btn.clicked.connect(self._start_hotkey_capture)
        hk_row.addWidget(self.hotkey_btn)
        hk_row.addSpacing(12)
        hk_row.addStretch()
        l.addLayout(hk_row)
        self.hotkey_hint = QLabel()
        self.hotkey_hint.setWordWrap(True)
        self.hotkey_hint.setStyleSheet("color: rgba(255,255,255,0.3); font-size: 11px; background:transparent; border:none;")
        self._set_hotkey_hint("Click here, then press a combo like Ctrl+Space.")
        l.addWidget(self.hotkey_hint)

        l.addSpacing(20)
        l.addWidget(self._divider())
        l.addSpacing(20)

        # Whisper model
        l.addWidget(self._section("Whisper Model"))
        l.addSpacing(8)
        wm_row = QHBoxLayout()
        self.model_combo = QComboBox()
        for m in ["Auto-detect", "large-v3", "medium", "small", "base", "tiny"]:
            self.model_combo.addItem(m)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        detected = QLabel(f"Auto-detected: {WHISPER_MODEL}")
        detected.setStyleSheet("color: rgba(255,255,255,0.3); font-size: 11px; background:transparent; border:none;")
        wm_row.addWidget(self.model_combo)
        wm_row.addSpacing(12)
        wm_row.addWidget(detected)
        wm_row.addStretch()
        l.addLayout(wm_row)

        l.addSpacing(20)
        l.addWidget(self._divider())
        l.addSpacing(20)

        # Startup
        l.addWidget(self._section("System"))
        l.addSpacing(8)
        self.startup_check = QCheckBox("Launch Flow automatically at Windows startup")
        self.startup_check.stateChanged.connect(self._on_startup_changed)
        l.addWidget(self.startup_check)

        l.addStretch()
        return w

    # ── Cleanup tab ───────────────────────────────────────────────────────────
    def _tab_cleanup(self):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        l = QVBoxLayout(w)
        l.setContentsMargins(22, 20, 22, 20)
        l.setSpacing(6)

        self.cleanup_check = QCheckBox("Enable AI text cleanup")
        self.cleanup_check.setStyleSheet("color: white; font-size: 14px; font-weight: 500; background: transparent; border: none;")
        self.cleanup_check.stateChanged.connect(self._on_cleanup_toggled)
        l.addWidget(self.cleanup_check)
        hint = QLabel("Removes filler words and polishes speech. Off = raw Whisper output (fastest).")
        hint.setStyleSheet("color: rgba(255,255,255,0.32); font-size: 11px; background:transparent; border:none;")
        hint.setWordWrap(True)
        l.addWidget(hint)

        l.addSpacing(18)
        l.addWidget(self._divider())
        l.addSpacing(18)

        l.addWidget(self._section("Cleanup Engine"))
        l.addSpacing(10)
        self.engine_openai = QRadioButton("OpenAI GPT  (cloud, highest quality)")
        self.engine_ollama = QRadioButton("Ollama  (local, free, no internet needed)")
        self.engine_openai.toggled.connect(self._on_engine_changed)
        l.addWidget(self.engine_openai)
        l.addSpacing(6)
        l.addWidget(self.engine_ollama)
        l.addSpacing(14)

        # OpenAI card
        self.openai_card = self._card()
        oc_l = QVBoxLayout(self.openai_card)
        oc_l.setContentsMargins(16, 14, 16, 14)
        oc_l.setSpacing(8)

        key_lbl = QLabel("OpenAI API Key")
        key_lbl.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 11px; background:transparent; border:none;")
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-...")
        self.api_key_input.textChanged.connect(self._on_apikey_changed)

        mdl_lbl = QLabel("Model")
        mdl_lbl.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 11px; background:transparent; border:none;")
        self.gpt_combo = QComboBox()
        self.gpt_combo.addItems(["gpt-4o-mini", "gpt-4o"])
        self.gpt_combo.currentTextChanged.connect(self._on_gpt_model_changed)

        oc_l.addWidget(key_lbl)
        oc_l.addWidget(self.api_key_input)
        oc_l.addWidget(mdl_lbl)
        oc_l.addWidget(self.gpt_combo)
        l.addWidget(self.openai_card)

        l.addSpacing(18)
        l.addWidget(self._divider())
        l.addSpacing(18)

        l.addWidget(self._section("Context Mode"))
        l.addSpacing(10)
        ctx_row = QHBoxLayout()
        ctx_row.setSpacing(6)
        self.ctx_btns = {}
        for key, label in CONTEXT_LABELS.items():
            btn = QPushButton(label)
            btn.setObjectName("CtxBtn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, k=key: self._on_context_changed(k))
            ctx_row.addWidget(btn)
            self.ctx_btns[key] = btn
        l.addLayout(ctx_row)

        l.addStretch()
        return w

    # ── Dictionary tab ────────────────────────────────────────────────────────
    def _tab_dictionary(self):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        l = QVBoxLayout(w)
        l.setContentsMargins(22, 20, 22, 20)
        l.setSpacing(6)

        l.addWidget(self._section("Custom Word Corrections"))
        l.addSpacing(4)
        hint = QLabel("Teach Flow to fix words it gets wrong. E.g. 'pie torch' → 'PyTorch'")
        hint.setStyleSheet("color: rgba(255,255,255,0.32); font-size: 11px; background:transparent; border:none;")
        l.addWidget(hint)
        l.addSpacing(10)

        self.dict_list = QListWidget()
        l.addWidget(self.dict_list)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.dict_wrong = QLineEdit()
        self.dict_wrong.setPlaceholderText("Heard (wrong)")
        arrow = QLabel("→")
        arrow.setStyleSheet("color: rgba(255,255,255,0.3); background:transparent; border:none;")
        self.dict_right = QLineEdit()
        self.dict_right.setPlaceholderText("Replace with")
        add_btn = QPushButton("Add")
        add_btn.setObjectName("Primary")
        add_btn.setFixedWidth(70)
        add_btn.clicked.connect(self._add_dict_entry)
        add_row.addWidget(self.dict_wrong)
        add_row.addWidget(arrow)
        add_row.addWidget(self.dict_right)
        add_row.addWidget(add_btn)
        l.addLayout(add_row)

        del_btn = QPushButton("Remove selected")
        del_btn.setObjectName("Danger")
        del_btn.clicked.connect(self._remove_dict_entry)
        l.addWidget(del_btn)

        return w

    # ── History tab ───────────────────────────────────────────────────────────
    def _tab_history(self):
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        l = QVBoxLayout(w)
        l.setContentsMargins(22, 20, 22, 20)
        l.setSpacing(6)

        l.addWidget(self._section("Recent Transcriptions"))
        l.addSpacing(4)
        hint = QLabel("Click any item to copy it back to clipboard")
        hint.setStyleSheet("color: rgba(255,255,255,0.32); font-size: 11px; background:transparent; border:none;")
        l.addWidget(hint)
        l.addSpacing(10)

        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self._copy_history_item)
        l.addWidget(self.history_list)

        clr_btn = QPushButton("Clear history")
        clr_btn.setObjectName("Danger")
        clr_btn.clicked.connect(self._clear_history)
        l.addWidget(clr_btn)

        return w

    # ── Load UI state from cfg ────────────────────────────────────────────────
    def _load_into_ui(self):
        self.hotkey_btn.setText(_display_hotkey(cfg["hotkey"]))
        self._set_hotkey_hint(f"Current hotkey: {_display_hotkey(cfg['hotkey'])}")
        override = cfg.get("whisper_model_override", "")
        idx = self.model_combo.findText(override if override else "Auto-detect")
        self.model_combo.setCurrentIndex(max(idx, 0))
        self.startup_check.setChecked(cfg.get("launch_at_startup", False))

        self.cleanup_check.setChecked(cfg.get("cleanup_enabled", False))
        engine = cfg.get("cleanup_engine", "openai")
        self.engine_openai.setChecked(engine == "openai")
        self.engine_ollama.setChecked(engine == "ollama")
        self.api_key_input.setText(cfg.get("openai_api_key", ""))
        gm_idx = self.gpt_combo.findText(cfg.get("openai_model", "gpt-4o-mini"))
        self.gpt_combo.setCurrentIndex(max(gm_idx, 0))

        ctx = cfg.get("context", "general")
        for k, btn in self.ctx_btns.items():
            btn.setChecked(k == ctx)

        self._update_cleanup_visibility()
        self._refresh_dict()
        self._refresh_history(cfg.get("history", []))

    def _update_cleanup_visibility(self):
        enabled   = self.cleanup_check.isChecked()
        is_openai = self.engine_openai.isChecked()
        self.engine_openai.setEnabled(enabled)
        self.engine_ollama.setEnabled(enabled)
        self.openai_card.setVisible(enabled and is_openai)

    def _set_hotkey_hint(self, text, warning=False):
        color = "rgba(245,158,11,0.95)" if warning else "rgba(255,255,255,0.3)"
        self.hotkey_hint.setStyleSheet(
            f"color: {color}; font-size: 11px; background:transparent; border:none;"
        )
        self.hotkey_hint.setText(text)

    def _cancel_hotkey_capture(self, restore=True, reason=None):
        if not self.hotkey_capturing:
            return
        if reason:
            log(reason)
        if self.worker_ref:
            self.worker_ref._hotkey_mgr.cancel_capture()
        key = cfg.get("hotkey", "right alt")
        if restore:
            self._finish_hotkey(key)
        else:
            if hasattr(self, '_capture_timer') and self._capture_timer.isActive():
                self._capture_timer.stop()
            self.hotkey_btn.setText(f"  {_display_hotkey(key)}")
            self.hotkey_btn.setChecked(False)
            self.hotkey_capturing = False
            self._set_hotkey_hint("Click here, then press a combo like Ctrl+Space.")

    def _on_app_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            self._cancel_hotkey_capture(
                restore=False,
                reason="🎹 Hotkey capture cancelled because Flow lost app focus",
            )

    # ── Hotkey capture — uses global WH_KEYBOARD_LL hook (works regardless of focus) ──
    def _start_hotkey_capture(self):
        if self.hotkey_capturing:
            return
        # Debounce: ignore re-entry within 600 ms of the last successful capture.
        # This prevents the held key (still pressed after capture) from immediately
        # triggering a second capture cycle via key-repeat or focus events.
        if time.monotonic() - self._capture_done_at < 0.6:
            return
        self.hotkey_capturing = True
        self.hotkey_btn.setText("Press combo…")
        self.hotkey_btn.setChecked(True)
        self._set_hotkey_hint("Hold your modifiers, then press a final key. Example: Ctrl+Space.")
        log("🎹 Hotkey capture started — using global hook (no focus required)")

        if self.worker_ref:
            self.worker_ref._hotkey_mgr.start_capture(
                lambda key: signals.hotkey_captured.emit(key)
            )

        # Safety timeout — cancel after 15s if nothing pressed
        self._capture_timer = QTimer()
        self._capture_timer.setSingleShot(True)
        self._capture_timer.timeout.connect(self._on_capture_timeout)
        self._capture_timer.start(15000)

    def _on_key_captured(self, key_name):
        """Called on Qt main thread when the global hook captures a key."""
        if not self.hotkey_capturing:
            log(f"  ↳ ignoring captured key outside capture mode: '{key_name}'")
            return
        normalized = _normalize_hotkey_string(key_name)
        log(f"🎹 Key captured via global hook: '{normalized}'")
        cfg["hotkey"] = normalized
        save_config(cfg)
        if self.worker_ref:
            self.worker_ref.update_hotkey(normalized)
        self._finish_hotkey(normalized)

    def _on_banned_key(self, key_name):
        """Called when user presses a modifier-only key during capture."""
        if not self.hotkey_capturing:
            return
        self._set_hotkey_hint(
            f"{_display_hotkey(key_name)} alone won't work. Hold it and press another key.",
            warning=True,
        )
        return
        log(f"  ⛔ Modifier-only hotkey pressed during capture: '{key_name}'")
        self.hotkey_btn.setText(f"  ⚠ Add another key with {_display_hotkey(key_name)}")
        # Restart capture so user can try again
        if self.worker_ref:
            self.worker_ref._hotkey_mgr.start_capture(
                lambda key: signals.hotkey_captured.emit(key)
            )

    def _on_capture_timeout(self):
        log("⚠️  Hotkey capture timed out — restoring previous key")
        self._cancel_hotkey_capture(restore=True)

    def _finish_hotkey(self, key):
        if hasattr(self, '_capture_timer') and self._capture_timer.isActive():
            self._capture_timer.stop()
        self.hotkey_btn.setText(f"  {_display_hotkey(key)}")
        self.hotkey_btn.setChecked(False)
        self.hotkey_capturing  = False
        self._capture_done_at  = time.monotonic()   # start 600 ms debounce window
        self._set_hotkey_hint(f"Current hotkey: {_display_hotkey(key)}")
        log(f"✅ Hotkey set to: '{key}'")
        print(f"✅ Hotkey changed to: {key}")

    def _on_model_changed(self, text):
        cfg["whisper_model_override"] = "" if text == "Auto-detect" else text
        save_config(cfg)

    def _on_startup_changed(self, state):
        cfg["launch_at_startup"] = bool(state)
        save_config(cfg)
        self._apply_startup(bool(state))

    def _apply_startup(self, enabled):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            if enabled:
                if getattr(sys, "frozen", False):
                    # Running as a PyInstaller .exe — register the exe directly.
                    cmd = f'"{sys.executable}"'
                else:
                    # Running as a script — launch with pythonw (no console window).
                    script = os.path.abspath(__file__)
                    cmd = f'pythonw "{script}"'
                winreg.SetValueEx(key, "Flow", 0, winreg.REG_SZ, cmd)
                log(f"✅ Launch at startup registered: {cmd}")
            else:
                try:
                    winreg.DeleteValue(key, "Flow")
                    log("✅ Launch at startup removed")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            log(f"⚠️  Startup setting failed: {e}")

    def _on_cleanup_toggled(self, _):
        cfg["cleanup_enabled"] = self.cleanup_check.isChecked()
        save_config(cfg)
        self._update_cleanup_visibility()

    def _on_engine_changed(self):
        cfg["cleanup_engine"] = "openai" if self.engine_openai.isChecked() else "ollama"
        save_config(cfg)
        self._update_cleanup_visibility()

    def _on_apikey_changed(self, text):
        cfg["openai_api_key"] = text
        save_config(cfg)

    def _on_gpt_model_changed(self, text):
        cfg["openai_model"] = text
        save_config(cfg)

    def _on_context_changed(self, key):
        cfg["context"] = key
        save_config(cfg)
        for k, btn in self.ctx_btns.items():
            btn.setChecked(k == key)

    def _add_dict_entry(self):
        wrong = self.dict_wrong.text().strip()
        right = self.dict_right.text().strip()
        if wrong and right:
            cfg["dictionary"][wrong] = right
            save_config(cfg)
            self.dict_wrong.clear()
            self.dict_right.clear()
            self._refresh_dict()

    def _remove_dict_entry(self):
        item = self.dict_list.currentItem()
        if item:
            cfg["dictionary"].pop(item.data(Qt.ItemDataRole.UserRole), None)
            save_config(cfg)
            self._refresh_dict()

    def _refresh_dict(self):
        self.dict_list.clear()
        for wrong, right in cfg.get("dictionary", {}).items():
            item = QListWidgetItem(f"{wrong}  →  {right}")
            item.setData(Qt.ItemDataRole.UserRole, wrong)
            self.dict_list.addItem(item)

    def _copy_history_item(self, item):
        text = item.data(Qt.ItemDataRole.UserRole)
        pyperclip.copy(text)
        orig = item.text()
        item.setText("✓ Copied!")
        QTimer.singleShot(1400, lambda: item.setText(orig) if self.history_list.count() else None)

    def _refresh_history(self, history):
        self.history_list.clear()
        for entry in reversed(history[-30:]):
            item = QListWidgetItem(entry[:90] + ("…" if len(entry) > 90 else ""))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.history_list.addItem(item)

    def _clear_history(self):
        cfg["history"] = []
        save_config(cfg)
        self.history_list.clear()

    # ── Drag to move ──────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def hideEvent(self, e):
        self._cancel_hotkey_capture(
            restore=False,
            reason="🎹 Hotkey capture cancelled because settings was hidden",
        )
        super().hideEvent(e)

    def event(self, e):
        if e.type() == QEvent.Type.WindowDeactivate:
            self._cancel_hotkey_capture(
                restore=False,
                reason="🎹 Hotkey capture cancelled because settings lost focus",
            )
        return super().event(e)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self._cancel_hotkey_capture(
                restore=False,
                reason="🎹 Hotkey capture cancelled because settings lost focus",
            )
        super().changeEvent(e)

    def paintEvent(self, _):
        pass  # Required for WA_TranslucentBackground


# ── PILL OVERLAY ──────────────────────────────────────────────────────────────
class FlowPill(QWidget):
    STATE_IDLE       = "idle"
    STATE_RECORDING  = "recording"
    STATE_PROCESSING = "processing"
    STATE_DONE       = "done"

    def __init__(self):
        super().__init__()
        self.state        = self.STATE_IDLE
        self.context      = cfg.get("context", "general")
        self.timer_secs   = 0
        self.wave_phases  = [random.uniform(0, math.pi * 2) for _ in range(12)]
        self.wave_heights = [0.15] * 12
        self.spin_angle   = 0
        self.done_text    = "Pasted!"
        self.pill_width   = 230
        self._target_w    = 230

        self._setup_window()
        self._setup_font()
        self._setup_timers()
        self._connect_signals()
        self._reposition()
        self.show()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(230, 58)

    def _setup_font(self):
        self.f_status = QFont("Segoe UI", 11)
        self.f_badge  = QFont("Segoe UI", 8, QFont.Weight.Medium)
        self.f_timer  = QFont("Segoe UI", 10)

    def _setup_timers(self):
        self.anim_timer = QTimer()
        self.anim_timer.timeout.connect(self._tick)
        self.anim_timer.start(16)

        self.rec_timer = QTimer()
        self.rec_timer.timeout.connect(lambda: (setattr(self, 'timer_secs', self.timer_secs + 1), self.update()))

        self.done_timer = QTimer()
        self.done_timer.setSingleShot(True)
        self.done_timer.timeout.connect(self._go_idle)

    def _connect_signals(self):
        signals.start_recording.connect(self._on_start)
        signals.stop_recording.connect(self._on_stop)
        signals.set_processing.connect(self._on_processing)
        signals.set_done.connect(self._on_done)
        signals.set_idle.connect(self._go_idle)

    def _reposition(self):
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, screen.height() - 110)

    def _on_start(self):
        self.state = self.STATE_RECORDING
        self.timer_secs = 0
        self.rec_timer.start(1000)
        self._set_w(280)

    def _on_stop(self):
        self.rec_timer.stop()

    def _on_processing(self):
        self.state = self.STATE_PROCESSING
        self._set_w(220)

    def _on_done(self, text):
        self.state     = self.STATE_DONE
        self.done_text = text or "Pasted!"
        self._set_w(190)
        self.done_timer.start(2000)

    def _go_idle(self):
        self.state   = self.STATE_IDLE
        self.context = cfg.get("context", "general")
        self._set_w(230)
        self.update()

    def _set_w(self, w):
        self._target_w = w

    def _tick(self):
        changed = False
        if abs(self.pill_width - self._target_w) > 0.5:
            self.pill_width += (self._target_w - self.pill_width) * 0.18
            self.setFixedWidth(int(self.pill_width))
            self._reposition()
            changed = True

        if self.state == self.STATE_RECORDING:
            for i in range(12):
                self.wave_phases[i] += 0.08 + i * 0.005
                t = max(0.08, math.sin(self.wave_phases[i]) * 0.5 + 0.5)
                self.wave_heights[i] += (t - self.wave_heights[i]) * 0.15
            changed = True
        else:
            for i in range(12):
                self.wave_heights[i] += (0.08 - self.wave_heights[i]) * 0.12
            if any(h > 0.1 for h in self.wave_heights):
                changed = True

        if self.state == self.STATE_PROCESSING:
            self.spin_angle = (self.spin_angle + 6) % 360
            changed = True

        if changed:
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H, R = self.width(), self.height(), self.height() // 2

        border = {
            self.STATE_IDLE:       COL_BORDER_IDLE,
            self.STATE_RECORDING:  COL_BORDER_REC,
            self.STATE_PROCESSING: COL_BORDER_PROC,
            self.STATE_DONE:       COL_BORDER_DONE,
        }.get(self.state, COL_BORDER_IDLE)

        path = QPainterPath()
        path.addRoundedRect(1, 1, W - 2, H - 2, R, R)
        p.fillPath(path, QBrush(COL_BG))
        p.setPen(QPen(border, 1.0))
        p.drawPath(path)

        # Icon circle
        ix, iy = 12, (H - 30) // 2
        icon_bg = {
            self.STATE_IDLE:       COL_ICON_BG_IDLE,
            self.STATE_RECORDING:  COL_ICON_BG_REC,
            self.STATE_PROCESSING: COL_ICON_BG_PROC,
            self.STATE_DONE:       COL_ICON_BG_DONE,
        }.get(self.state, COL_ICON_BG_IDLE)
        # Icon circle — dark bg with a violet ring (matches .ico design)
        _ring = {
            self.STATE_IDLE:       QColor(124,  58, 237, 110),
            self.STATE_RECORDING:  QColor(239,  68,  68, 110),
            self.STATE_PROCESSING: QColor(139,  92, 246, 110),
            self.STATE_DONE:       QColor( 34, 197,  94,  90),
        }.get(self.state, QColor(124, 58, 237, 110))
        p.setPen(QPen(_ring, 1.2))
        p.setBrush(QBrush(icon_bg))
        p.drawEllipse(ix, iy, 30, 30)

        cx, cy = ix + 15, iy + 15
        if self.state == self.STATE_IDLE:
            self._draw_mic(p, cx, cy, QColor(255, 255, 255, 150))
        elif self.state == self.STATE_RECORDING:
            self._draw_mic(p, cx, cy, QColor(239, 68, 68, 220))
        elif self.state == self.STATE_PROCESSING:
            self._draw_spinner(p, cx, cy)
        elif self.state == self.STATE_DONE:
            self._draw_check(p, cx, cy)

        content_x = ix + 38
        content_w  = W - content_x - 12

        if self.state == self.STATE_RECORDING:
            tw = 30
            self._draw_waveform(p, content_x, H // 2, content_w - tw - 8)
            mins, secs = self.timer_secs // 60, self.timer_secs % 60
            p.setFont(self.f_timer)
            p.setPen(COL_TIMER)
            p.drawText(QRect(content_x + content_w - tw, 0, tw, H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"{mins}:{secs:02d}")

        elif self.state == self.STATE_PROCESSING:
            p.setFont(self.f_status)
            p.setPen(COL_TEXT_PROC)
            p.drawText(QRect(content_x, 0, content_w, H), Qt.AlignmentFlag.AlignVCenter, "Transcribing...")

        elif self.state == self.STATE_DONE:
            p.setFont(self.f_status)
            p.setPen(COL_TEXT_DONE)
            p.drawText(QRect(content_x, 0, content_w, H), Qt.AlignmentFlag.AlignVCenter, self.done_text)

        else:
            badge_label = CONTEXT_LABELS.get(self.context, "General").upper()
            p.setFont(self.f_badge)
            badge_w = p.fontMetrics().horizontalAdvance(badge_label) + 16
            text_w  = content_w - badge_w - 8

            p.setFont(self.f_status)
            p.setPen(COL_TEXT_IDLE)
            p.drawText(QRect(content_x, 0, text_w, H), Qt.AlignmentFlag.AlignVCenter, "Hold to speak")

            bx, by = W - badge_w - 10, (H - 18) // 2
            bp = QPainterPath()
            bp.addRoundedRect(bx, by, badge_w, 18, 9, 9)
            p.fillPath(bp, QBrush(COL_BADGE_BG))
            p.setPen(QPen(COL_BADGE_BORD, 1.0))
            p.drawPath(bp)
            p.setFont(self.f_badge)
            p.setPen(COL_BADGE_TEXT)
            p.drawText(QRect(bx, by, badge_w, 18), Qt.AlignmentFlag.AlignCenter, badge_label)

        p.end()

    def _draw_waveform(self, p, x, cy, w):
        bar_w = 2.5
        gap   = (w - 12 * bar_w) / 11
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(12):
            h   = max(3, self.wave_heights[i] * 18)
            bx  = x + i * (bar_w + gap)
            col = QColor(COL_WAVE_REC)
            col.setAlpha(int(80 + self.wave_heights[i] * 140))
            p.setBrush(QBrush(col))
            p.drawRoundedRect(int(bx), int(cy - h / 2), int(bar_w), int(h), 1.5, 1.5)

    def _draw_mic(self, p, cx, cy, col):
        # col carries state: reddish = recording, violet = idle.
        # We use it only to pick the body fill; everything else is fixed.
        is_rec = col.red() > 180 and col.blue() < 120
        body_fill = QColor(239, 68, 68, 230) if is_rec else QColor(124, 58, 237, 255)
        white     = QColor(255, 255, 255, 215)
        slits     = QColor(255, 255, 255, 110)
        dot_col   = QColor(167, 139, 250, 255)

        # ── Mic body: purple/red fill + white stencil outline ─────────────────
        bx, by, bw, bh, br = cx - 3.5, cy - 7.0, 7.0, 10.0, 3.5
        body = QPainterPath()
        body.addRoundedRect(bx, by, bw, bh, br, br)
        p.fillPath(body, QBrush(body_fill))
        p.setPen(QPen(white, 0.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(body)

        # ── Horizontal stencil slit lines across body ─────────────────────────
        p.setPen(QPen(slits, 0.85))
        for frac in (0.35, 0.62):
            ly = by + bh * frac
            p.drawLine(int(bx + 1.5), int(ly), int(bx + bw - 1.5), int(ly))

        # ── Stand arc ─────────────────────────────────────────────────────────
        p.setPen(QPen(white, 1.3, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        arc = QPainterPath()
        arc.moveTo(cx - 5.5, cy + 1)
        arc.arcTo(cx - 5.5, cy - 4, 11, 11, 0, -180)
        p.drawPath(arc)

        # ── Stem ──────────────────────────────────────────────────────────────
        p.drawLine(int(cx), int(cy + 7), int(cx), int(cy + 10))

        # ── Base bar ──────────────────────────────────────────────────────────
        p.drawLine(int(cx - 3), int(cy + 10), int(cx + 3), int(cy + 10))

        # ── Violet accent dot at base (matches .ico) ──────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(dot_col))
        p.drawEllipse(int(cx - 1.5), int(cy + 11), 3, 3)

    def _draw_spinner(self, p, cx, cy):
        r = 7
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(139, 92, 246, 40), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)
        p.setPen(QPen(QColor(167, 139, 250, 220), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(int(cx - r), int(cy - r), r * 2, r * 2, self.spin_angle * 16, 100 * 16)

    def _draw_check(self, p, cx, cy):
        p.setPen(QPen(QColor(34, 197, 94, 230), 1.8, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        check = QPainterPath()
        check.moveTo(cx - 5, cy)
        check.lineTo(cx - 1, cy + 4)
        check.lineTo(cx + 5, cy - 5)
        p.drawPath(check)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and hasattr(self, '_drag_pos'):
            self.move(e.globalPosition().toPoint() - self._drag_pos)


# ── AUDIO + AI WORKER ─────────────────────────────────────────────────────────
class FlowWorker(QThread):
    def __init__(self):
        super().__init__()
        self.recording    = False
        self.audio_frames = []
        self._should_run  = True
        self.whisper      = None
        self.paused       = False
        self._hotkey      = cfg.get("hotkey", "right alt")
        self._hotkey_mgr  = HotkeyManager()
        self._target_hwnd = 0
        self._target_point = None
        self._target_point_hwnd = 0
        self._target_focus_hwnd = 0
        self._target_uia_class = ""

    def run(self):
        log("▶ FlowWorker.run() started")
        self._load_model()
        self._hotkey_mgr.register(self._hotkey, self._on_press, self._on_release)
        log("▶ Worker idle loop")
        while self._should_run:
            time.sleep(0.1)
        self._hotkey_mgr.unregister()
        log("▶ FlowWorker.run() exiting")

    def update_hotkey(self, new_key):
        """Called from any thread — safe, HotkeyManager handles its own thread."""
        log(f"🔄 update_hotkey('{new_key}')")
        self._hotkey = new_key
        self.paused  = False
        self._hotkey_mgr.register(new_key, self._on_press, self._on_release)

    def _load_model(self):
        try:
            # ── Step 1: detect hardware (torch imported HERE, not at module level) ──
            signals.loading_status.emit("Detecting hardware…")
            time.sleep(0.3)
            model_name, device = detect_whisper_model()

            # CPU machines: cap at small — large models are unusably slow on CPU
            if device == "cpu" and model_name in ("large-v3", "medium"):
                log(f"ℹ️  CPU-only machine — capping model at small (was {model_name})")
                model_name = "small"

            if device == "cuda":
                try:
                    import torch
                    gpu  = torch.cuda.get_device_name(0)
                    vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                    signals.loading_status.emit(
                        f"GPU: {gpu.replace('NVIDIA ', '')} ({vram:.0f} GB) → {model_name}")
                    time.sleep(0.5)
                except Exception as e:
                    log(f"⚠️  GPU info unavailable: {e}")
            else:
                signals.loading_status.emit("No GPU — using Whisper small on CPU")
                time.sleep(0.5)

            # ── Step 2: purge corrupt (0-byte) cached model files ─────────────────
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
            if os.path.isdir(cache_dir):
                for fn in os.listdir(cache_dir):
                    fp = os.path.join(cache_dir, fn)
                    if os.path.isfile(fp) and os.path.getsize(fp) == 0:
                        log(f"⚠️  Removing corrupt 0-byte model cache: {fn}")
                        try:
                            os.remove(fp)
                        except Exception:
                            pass

            # ── Step 3: import whisper (may trigger model download on first run) ──
            import whisper as wh

            # ── Step 4: try model, fall back on OOM or any load error ─────────────
            _FALLBACK = {
                "large-v3": ["large-v3", "medium", "small"],
                "medium":   ["medium", "small"],
                "small":    ["small"],
                "base":     ["base", "tiny"],
                "tiny":     ["tiny"],
            }
            candidates = _FALLBACK.get(model_name, [model_name, "small"])
            loaded = None
            for model in candidates:
                try:
                    signals.loading_status.emit(f"Loading Whisper {model}…")
                    print(f"⏳ Loading Whisper {model} on {device.upper()}…")
                    self.whisper = wh.load_model(model, device=device)
                    loaded = model
                    break
                except Exception as e:
                    msg = str(e).lower()
                    is_oom = "out of memory" in msg or "cuda" in msg
                    log(f"⚠️  Whisper {model} failed ({type(e).__name__}): {e}")
                    signals.loading_status.emit(
                        f"⚠️ {model} {'OOM' if is_oom else 'failed'} — trying smaller…")
                    try:
                        import torch; torch.cuda.empty_cache()
                    except Exception:
                        pass
                    # If it's not an OOM/CUDA error on the smallest model, stop retrying
                    if not is_oom and model == candidates[-1]:
                        break

            if loaded:
                print(f"✅ Whisper {loaded} ready on {device.upper()}!")
                signals.loading_status.emit(
                    f"Ready  ·  Whisper {loaded}  ·  {'GPU' if device == 'cuda' else 'CPU'}")
                time.sleep(0.5)
                signals.loading_complete.emit()
            else:
                raise RuntimeError("All Whisper model sizes failed to load")

        except ImportError:
            self.whisper = None
            signals.loading_status.emit("Whisper not found — using OpenAI API")
            time.sleep(1.0)
            signals.loading_complete.emit()
            print("⚠️  openai-whisper not installed — will use OpenAI API for transcription")

        except Exception as e:
            # Catch-all — never leave the UI stuck on the loading screen
            log(f"❌ _load_model failed: {type(e).__name__}: {e}")
            self.whisper = None
            signals.loading_status.emit("Model load failed — see log")
            time.sleep(1.5)
            signals.loading_complete.emit()

    def _has_cuda(self):
        try:
            import torch
            return torch.cuda.is_available()
        except Exception:
            return False

    def _on_press(self):
        log(f"⬇ _on_press() — recording={self.recording}")
        if self.recording:
            log("  ↳ ignored (already recording)")
            return
        self._target_hwnd = _get_foreground_window()
        self._target_focus_hwnd = _get_focused_control(self._target_hwnd)
        self._target_point = _get_cursor_pos()
        self._target_point_hwnd = _window_from_point(self._target_point)
        log(f"  ↳ target window captured: hwnd=0x{int(self._target_hwnd):X}" if self._target_hwnd else "  ↳ target window capture failed")
        if self._target_focus_hwnd:
            focus_class = _get_window_class_name(self._target_focus_hwnd)
            if focus_class:
                log(f"  ↳ focused control captured: hwnd=0x{int(self._target_focus_hwnd):X} class='{focus_class}'")
            else:
                log(f"  ↳ focused control captured: hwnd=0x{int(self._target_focus_hwnd):X}")
        if self._target_point:
            point_class = _get_window_class_name(self._target_point_hwnd)
            _, self._target_uia_class, target_uia_name = _uia_element_from_point(self._target_point)
            if self._target_point_hwnd:
                if point_class:
                    log(f"  ↳ target point captured: {self._target_point} hwnd=0x{int(self._target_point_hwnd):X} class='{point_class}'")
                else:
                    log(f"  ↳ target point captured: {self._target_point} hwnd=0x{int(self._target_point_hwnd):X}")
            else:
                log(f"  ↳ target point captured: {self._target_point}")
            if self._target_uia_class or target_uia_name:
                log(f"  ↳ UIA target at point: class='{self._target_uia_class}' name={repr(target_uia_name)}")
        self.recording    = True
        self.audio_frames = []
        log("🎙 Recording started")
        signals.start_recording.emit()
        threading.Thread(target=self._record_loop, daemon=True).start()

    def _on_release(self):
        log(f"⬆ _on_release() — recording={self.recording}")
        if self.recording:
            self.recording = False
            log("⏹ Recording stopped — spawning _process thread")
            signals.stop_recording.emit()
            threading.Thread(target=self._process, daemon=True).start()
        else:
            log("  ↳ _on_release ignored (was not recording)")

    def _record_loop(self):
        pa  = pyaudio.PyAudio()
        stm = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                      input=True, frames_per_buffer=1024)
        while self.recording:
            self.audio_frames.append(stm.read(1024, exception_on_overflow=False))
        stm.stop_stream(); stm.close(); pa.terminate()

    def _process(self):
        frames = list(self.audio_frames)
        log(f"⚙ _process() — {len(frames)} audio frames")
        if len(frames) < 5:
            log("  ↳ too short, ignoring")
            signals.set_idle.emit()
            return

        signals.set_processing.emit()

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes(b"".join(frames))
        log(f"  ↳ WAV written to {tmp.name}")

        try:
            log("  ↳ transcribing…")
            raw = self._transcribe(tmp.name)
            log(f"  ↳ raw transcript: {repr(raw)}")
            raw = self._apply_dictionary(raw)
            log(f"  ↳ after dictionary: {repr(raw)}")

            if cfg.get("cleanup_enabled", False):
                log("  ↳ cleanup enabled — calling _cleanup()")
                final = self._cleanup(raw)
                log(f"  ↳ after cleanup: {repr(final)}")
            else:
                final = raw

            if final:
                # Save to history
                history = cfg.get("history", [])
                history.append(final)
                cfg["history"] = history[-30:]
                save_config(cfg)
                signals.history_updated.emit(cfg["history"])

                log(f"  ↳ copying to clipboard: {repr(final)}")
                pyperclip.copy(final)
                time.sleep(0.15)

                # Restore focus to the window that was active when the user
                # pressed the hotkey, so SendInput delivers Ctrl+V there.
                if self._target_hwnd:
                    _restore_window(self._target_hwnd)
                    time.sleep(0.05)

                log("  ↳ using generic paste path (clipboard + Ctrl+V)")
                log(f"  ↳ sending Ctrl+V via SendInput — paused={self.paused}, hotkey='{self._hotkey}'")
                _send_paste()
                log("  ↳ Ctrl+V sent ✅")
                self._target_hwnd = 0
                self._target_point = None
                self._target_point_hwnd = 0
                self._target_focus_hwnd = 0
                self._target_uia_class = ""
                signals.set_done.emit("Pasted!")
            else:
                log("  ↳ final text is empty — going idle")
                self._target_hwnd = 0
                self._target_point = None
                self._target_point_hwnd = 0
                self._target_focus_hwnd = 0
                self._target_uia_class = ""
                signals.set_idle.emit()
        except Exception as e:
            self._target_hwnd = 0
            self._target_point = None
            self._target_point_hwnd = 0
            self._target_focus_hwnd = 0
            self._target_uia_class = ""
            log(f"❌ _process error: {e}")
            import traceback; log(traceback.format_exc())
            print(f"❌ Error: {e}")
            signals.error.emit(str(e))
            signals.set_idle.emit()
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def _transcribe(self, wav_path):
        if self.whisper:
            try:
                result = self.whisper.transcribe(wav_path, language="en",
                                                 fp16=self._has_cuda(), temperature=0.0)
                return result["text"].strip()
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    log("⚠️  CUDA OOM during transcription — retrying on CPU")
                    result = self.whisper.transcribe(wav_path, language="en",
                                                     fp16=False, temperature=0.0)
                    return result["text"].strip()
                raise
        else:
            # Whisper not installed locally — fall back to OpenAI cloud API.
            try:
                from openai import OpenAI
            except ImportError:
                raise RuntimeError(
                    "openai-whisper is not installed and the 'openai' package is also "
                    "missing. Install one: pip install openai-whisper  OR  pip install openai"
                )
            api_key = cfg.get("openai_api_key", "") or os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise RuntimeError(
                    "No OpenAI API key found. Open Settings → Cleanup and enter your key, "
                    "or install openai-whisper for local transcription."
                )
            client = OpenAI(api_key=api_key)
            with open(wav_path, "rb") as f:
                result = client.audio.transcriptions.create(model="whisper-1", file=f)
            return result.text.strip()

    def _apply_dictionary(self, text):
        for wrong, right in cfg.get("dictionary", {}).items():
            text = text.replace(wrong, right)
        return text

    def _cleanup(self, text):
        if not text:
            return text
        engine  = cfg.get("cleanup_engine", "openai")
        context = cfg.get("context", "general")
        prompt  = CONTEXT_PROMPTS.get(context, CONTEXT_PROMPTS["general"])

        if engine == "openai":
            api_key = cfg.get("openai_api_key", "") or os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                print("⚠️  No OpenAI API key — returning raw text")
                return text
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                resp = client.chat.completions.create(
                    model=cfg.get("openai_model", "gpt-4o-mini"),
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user",   "content": text},
                    ],
                    temperature=0.1,
                    max_tokens=500,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                print(f"⚠️  OpenAI cleanup error: {e}")
                return text
        else:
            try:
                import requests
                r = requests.post("http://localhost:11434/api/generate", json={
                    "model": cfg.get("ollama_model", "llama3.1:8b"),
                    "prompt": f"{prompt}\n\nText: {text}",
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 500}
                }, timeout=60)
                return r.json().get("response", text).strip()
            except Exception as e:
                print(f"⚠️  Ollama cleanup error: {e}")
                return text


# ── SYSTEM TRAY ───────────────────────────────────────────────────────────────
def _make_tray_pixmap(S=256):
    """Draw the Flow tray icon at size S×S.
    No dark circle background — transparent canvas so it adapts to both
    dark and light taskbars.  Bold proportional strokes stay legible at 16px."""
    px = QPixmap(S, S)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # All geometry uses explicit fractions of S — same proportions as flow_icon.ico
    cx     = S * 0.50
    stroke = max(3, int(S * 0.062))   # ~6 % of S; fat enough to read at 16 px

    # ── Mic body ─────────────────────────────────────────────────────────────
    bw = S * 0.42;  bh = S * 0.42;  br = bw / 2
    bx = cx - bw / 2;  by = S * 0.05

    body = QPainterPath()
    body.addRoundedRect(bx, by, bw, bh, br, br)
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(body, QBrush(QColor(109, 40, 217, 255)))   # violet-700

    ow = max(2, int(S * 0.028))
    p.setPen(QPen(QColor(255, 255, 255, 230), ow))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(body)

    # ── Stencil slit lines ────────────────────────────────────────────────────
    slit_w = max(1, int(S * 0.038))
    p.setPen(QPen(QColor(210, 185, 255, 160), slit_w,
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for frac in (0.38, 0.64):
        ly = by + bh * frac
        p.drawLine(int(bx + bw * 0.18), int(ly),
                   int(bx + bw * 0.82), int(ly))

    # ── Stand arc — bounding box overlaps lower body, U-curves downward ───────
    # arc_y2 is the very bottom of the arc curve (= stem start)
    arc_x1 = S * 0.18;  arc_y1 = S * 0.34
    arc_x2 = S * 0.82;  arc_y2 = S * 0.70
    arc_w  = arc_x2 - arc_x1;  arc_h = arc_y2 - arc_y1

    p.setPen(QPen(QColor(255, 255, 255, 235), stroke,
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Qt arcTo: startAngle=0 (3-o'clock right), sweepAngle=-180 (clockwise→U shape)
    arc_path = QPainterPath()
    arc_path.arcMoveTo(arc_x1, arc_y1, arc_w, arc_h, 0)
    arc_path.arcTo(arc_x1, arc_y1, arc_w, arc_h, 0, -180)
    p.drawPath(arc_path)

    # ── Stem ─────────────────────────────────────────────────────────────────
    stem_bot = S * 0.83
    p.drawLine(int(cx), int(arc_y2), int(cx), int(stem_bot))

    # ── Base bar ─────────────────────────────────────────────────────────────
    base_hw = S * 0.24
    p.drawLine(int(cx - base_hw), int(stem_bot),
               int(cx + base_hw), int(stem_bot))

    p.end()
    return px


def create_tray(app, pill, settings_win):
    # Prefer loading the bundled .ico (has hand-tuned 16 & 32 px frames).
    # Fall back to the programmatic version if the file isn't present.
    _ico_path = os.path.join(
        os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                        else os.path.abspath(__file__)),
        "flow_icon.ico",
    )
    if os.path.exists(_ico_path):
        tray_icon = QIcon(_ico_path)
    else:
        # Build a multi-resolution QIcon so Windows can pick the best size
        tray_icon = QIcon()
        for _sz in (256, 64, 32, 16):
            tray_icon.addPixmap(_make_tray_pixmap(_sz))

    tray = QSystemTrayIcon(tray_icon, app)
    menu = QMenu()
    menu.setStyleSheet("""
        QMenu {
            background: #1a1a1e; border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px; padding: 4px; color: white; font-size: 13px;
        }
        QMenu::item { padding: 7px 18px; border-radius: 5px; }
        QMenu::item:selected { background: rgba(139,92,246,0.3); }
        QMenu::separator { background: rgba(255,255,255,0.08); height: 1px; margin: 4px 8px; }
    """)

    # Settings
    settings_act = QAction("⚙️  Settings", menu)
    settings_act.triggered.connect(lambda: (
        settings_win.show(),
        settings_win.raise_(),
        settings_win.activateWindow()
    ))
    menu.addAction(settings_act)
    menu.addSeparator()

    # Context switcher
    ctx_label = QAction("Context:", menu)
    ctx_label.setEnabled(False)
    menu.addAction(ctx_label)
    for key, label in CONTEXT_LABELS.items():
        act = QAction(f"   {label}", menu)
        act.setCheckable(True)
        act.setChecked(key == cfg.get("context", "general"))
        def _make_setter(k, a):
            def _set():
                cfg["context"] = k
                save_config(cfg)
                pill.context = k
                pill.update()
                for action in menu.actions():
                    if action.isCheckable():
                        action.setChecked(False)
                a.setChecked(True)
            return _set
        act.triggered.connect(_make_setter(key, act))
        menu.addAction(act)

    menu.addSeparator()
    quit_act = QAction("Quit Flow", menu)
    quit_act.triggered.connect(app.quit)
    menu.addAction(quit_act)

    tray.setContextMenu(menu)
    tray.setToolTip("Flow — Voice Dictation")
    tray.activated.connect(lambda reason: (
        settings_win.show(), settings_win.raise_()
    ) if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
    tray.show()
    return tray


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    _init_log()
    log(f"Flow starting — log file: {_LOG_PATH}")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    splash   = SplashScreen()
    pill     = FlowPill()
    worker   = FlowWorker()
    settings = SettingsWindow(worker_ref=worker)

    # Hide pill until loading is done
    pill.hide()
    signals.loading_complete.connect(lambda: (
        QTimer.singleShot(600, pill.show)
    ))

    tray = create_tray(app, pill, settings)
    worker.start()

    print("=" * 50)
    print("  🎤 Flow — Running")
    print(f"  Hold [{cfg.get('hotkey', 'right alt').upper()}] to record")
    print(f"  Right-click tray icon → Settings or context")
    print(f"  Double-click tray icon to open Settings")
    print("=" * 50)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
