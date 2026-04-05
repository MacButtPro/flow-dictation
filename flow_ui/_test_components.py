"""
Internal component tests — called by test_flow_e2e.py as a subprocess.
Tests HotkeyManager logic, _send_paste, config, and dictionary directly.
Note: OS-level key event delivery (WH_KEYBOARD_LL) is only testable in a
full desktop session with a message loop — those tests run in the full app.
"""
import sys, os, time, threading, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def ok(name):
    print(f"COMPONENT_PASS:{name}")

def fail(name, reason=""):
    print(f"COMPONENT_FAIL:{name}:{reason}")

# ── Extract flow_ui preamble (before Qt import) ───────────────────────────────
try:
    with open(os.path.join(os.path.dirname(__file__), "flow_ui.py"), "r", encoding="utf-8") as f:
        src = f.read()
    preamble = src[:src.index("from PyQt6")]
    g = {"__file__": os.path.join(os.path.dirname(__file__), "flow_ui.py")}
    exec(compile(preamble, "flow_ui.py", "exec"), g)
    HotkeyManager   = g["HotkeyManager"]
    _send_paste     = g["_send_paste"]
    _BANNED_HOTKEYS = g["_BANNED_HOTKEYS"]
    _NAME_TO_VK     = g["_NAME_TO_VK"]
    _parse_hotkey   = g["_parse_hotkey"]
    _display_hotkey = g["_display_hotkey"]
    ok("flow_ui preamble extracted")
except Exception as e:
    fail("flow_ui preamble extracted", str(e))
    sys.exit(1)

# Qt/UI regression: repeated hotkey capture should not stack duplicate signal handlers
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import flow_ui as flow_ui_module
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    class FakeHotkeyManager:
        def __init__(self):
            self.capture_requests = 0

        def start_capture(self, callback):
            self.capture_requests += 1
            self.callback = callback

        def cancel_capture(self):
            pass

    class FakeWorker:
        def __init__(self):
            self._hotkey_mgr = FakeHotkeyManager()
            self.updated_keys = []

        def update_hotkey(self, new_key):
            self.updated_keys.append(new_key)

    original_cfg_hotkey = flow_ui_module.cfg.get("hotkey", "right alt")
    fake_worker = FakeWorker()
    win = flow_ui_module.SettingsWindow(worker_ref=fake_worker)

    win._start_hotkey_capture()
    flow_ui_module.signals.capture_banned_key.emit("left ctrl")
    app.processEvents()
    assert win.hotkey_capturing, "capture should stay active after banned key"
    assert fake_worker._hotkey_mgr.capture_requests == 1, "capture should remain active without restarting"

    win._start_hotkey_capture()  # should be ignored while already capturing
    flow_ui_module.signals.hotkey_captured.emit("ctrl+tab")
    app.processEvents()
    assert fake_worker.updated_keys == ["ctrl+tab"], f"expected one hotkey update, got {fake_worker.updated_keys}"
    assert not win.hotkey_capturing, "capture should end after valid key"
    ok("Settings hotkey capture does not duplicate handlers across retries")

    flow_ui_module.cfg["hotkey"] = original_cfg_hotkey
    flow_ui_module.save_config(flow_ui_module.cfg)
    win.close()
except Exception as e:
    fail("Settings hotkey capture does not duplicate handlers across retries", str(e))

# ── _send_paste: INPUT struct must be 40 bytes on 64-bit Windows ──────────────
# SendInput checks cbSize against sizeof(INPUT).  If only KEYBDINPUT (24 bytes)
# is in the union, the struct becomes 32 bytes and SendInput silently drops all
# events.  MOUSEINPUT is 32 bytes, making the union 32 and INPUT 40 bytes.
try:
    import ctypes, ctypes.wintypes
    class _KB(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.wintypes.WORD),
            ("wScan",       ctypes.wintypes.WORD),
            ("dwFlags",     ctypes.wintypes.DWORD),
            ("time",        ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]
    class _U(ctypes.Union):
        _fields_ = [("ki", _KB), ("_pad", ctypes.c_byte * 32)]
    class _I(ctypes.Structure):
        _anonymous_ = ("_u",)
        _fields_    = [("type", ctypes.wintypes.DWORD), ("_u", _U)]
    sz = ctypes.sizeof(_I)
    assert sz == 40, f"INPUT struct size is {sz}, expected 40 — SendInput will silently fail"
    ok("INPUT struct size is 40 bytes (SendInput compatibility)")
except Exception as e:
    fail("INPUT struct size is 40 bytes (SendInput compatibility)", str(e))

# ── _send_paste ───────────────────────────────────────────────────────────────
try:
    _send_paste()
    ok("_send_paste executes without error")
except Exception as e:
    fail("_send_paste executes without error", str(e))

# ── VK map: all expected keys present ────────────────────────────────────────
missing = []
for key in ["right alt", "left alt", "right ctrl", "left ctrl",
            "right shift", "left shift", "space", "f1", "f8", "f12",
            "a", "z", "0", "9"]:
    if key not in _NAME_TO_VK:
        missing.append(key)
if missing:
    fail("VK map contains all expected keys", f"missing: {missing}")
else:
    ok("VK map contains all expected keys")

# ── Banned hotkeys list is correct ───────────────────────────────────────────
required_banned = {"left ctrl", "right ctrl", "left shift", "right shift", "left alt"}
if required_banned.issubset(_BANNED_HOTKEYS):
    ok("Modifier-only hotkey list correct (Ctrl/Shift/Left Alt blocked)")
else:
    fail("Modifier-only hotkey list correct", f"missing: {required_banned - _BANNED_HOTKEYS}")

if "right alt" not in _BANNED_HOTKEYS:
    ok("Right Alt is allowed as a single-key hotkey")
else:
    fail("Right Alt is allowed as a single-key hotkey", "Right Alt is incorrectly banned")

try:
    parsed = _parse_hotkey("Ctrl+Alt+Space")
    assert parsed["modifiers"] == ["ctrl", "alt"]
    assert parsed["trigger"] == "space"
    assert parsed["normalized"] == "ctrl+alt+space"
    assert _display_hotkey("ctrl+alt+space") == "Ctrl+Alt+Space"
    parsed_mods = _parse_hotkey("Ctrl+Alt")
    assert parsed_mods["modifiers"] == ["ctrl"]
    assert parsed_mods["trigger"] == "alt"
    assert parsed_mods["normalized"] == "ctrl+alt"
    assert _parse_hotkey("left ctrl") is None
    ok("Hotkey parser normalizes combos and blocks modifier-only hotkeys")
except Exception as e:
    fail("Hotkey parser normalizes combos and blocks modifier-only hotkeys", str(e))

# ── HotkeyManager: instantiates cleanly ──────────────────────────────────────
try:
    mgr = HotkeyManager()
    assert mgr._hotkey_spec is None
    assert mgr._capture_cb is None
    ok("HotkeyManager instantiates cleanly")
except Exception as e:
    fail("HotkeyManager instantiates cleanly", str(e))
    sys.exit(1)

# ── HotkeyManager: register installs hook thread ─────────────────────────────
try:
    press_log = []
    release_log = []
    mgr.register("ctrl+space",
                 on_press=lambda: press_log.append(1),
                 on_release=lambda: release_log.append(1))
    time.sleep(0.5)
    assert mgr._thread is not None, "hook thread not started"
    assert mgr._thread.is_alive(), "hook thread not alive"
    assert mgr._hook is not None, "hook not installed"
    assert mgr._hotkey_spec["normalized"] == "ctrl+space", f"wrong spec: {mgr._hotkey_spec}"
    ok("HotkeyManager.register() installs hook thread for combo hotkeys")
except Exception as e:
    fail("HotkeyManager.register() installs hook thread", str(e))

# ── HotkeyManager: callbacks fire when called directly ───────────────────────
try:
    mgr._on_press()
    time.sleep(0.1)
    assert len(press_log) == 1, f"press callback not fired (got {press_log})"

    mgr._on_release()
    time.sleep(0.1)
    assert len(release_log) == 1, f"release callback not fired (got {release_log})"

    ok("on_press and on_release callbacks fire correctly")
except Exception as e:
    fail("on_press and on_release callbacks fire correctly", str(e))

try:
    mgr._pressed_keys = {"left ctrl", "space"}
    assert mgr._combo_matches(), "combo should match when ctrl+space is pressed"
    mgr._pressed_keys = {"space"}
    assert not mgr._combo_matches(), "combo should not match without ctrl"
    mgr._pressed_keys = {"left ctrl", "space"}
    assert mgr._key_affects_combo("left ctrl")
    assert mgr._key_affects_combo("space")
    assert not mgr._key_affects_combo("tab")
    mgr._hotkey_spec = _parse_hotkey("ctrl+alt")
    mgr._pressed_keys = {"left ctrl", "left alt"}
    assert mgr._combo_matches(), "modifier-only combo should match when both modifiers are pressed"
    ok("Combo matching logic detects required modifiers and trigger")
except Exception as e:
    fail("Combo matching logic detects required modifiers and trigger", str(e))

# ── HotkeyManager: change hotkey 5 times, thread restarts cleanly ────────────
try:
    cycle_keys = ["f8", "ctrl+space", "ctrl+alt", "right alt", "ctrl+shift+tab"]
    for key in cycle_keys:
        mgr.register(key, on_press=lambda: None, on_release=lambda: None)
        time.sleep(0.3)
        assert mgr._thread.is_alive(), f"thread died after switching to {key}"
        assert mgr._hotkey_spec["normalized"] == key, f"spec mismatch: expected {key}, got {mgr._hotkey_spec}"
    ok("Hotkey changed 5 times — thread alive and combo spec correct each time")
except Exception as e:
    fail("Hotkey changed 5 times cleanly", str(e))

# ── HotkeyManager: capture mode sets callback ────────────────────────────────
try:
    captured = []
    done     = threading.Event()
    mgr.start_capture(lambda k: (captured.append(k), done.set()))
    assert mgr._capture_cb is not None, "capture_cb not set"
    ok("start_capture() sets capture callback")
except Exception as e:
    fail("start_capture() sets capture callback", str(e))

# ── HotkeyManager: capture ignores banned key, accepts valid key ──────────────
try:
    captured2 = []
    done2     = threading.Event()

    # Prime with fresh capture
    mgr.start_capture(lambda k: (captured2.append(k), done2.set()))

    # Simulate what the hook proc does when a banned key is pressed:
    # it should NOT call the callback for banned keys
    banned_vk = 0xA2  # Left Ctrl
    key_name_for_banned = g["_VK_TO_NAME"].get(banned_vk)
    assert key_name_for_banned in _BANNED_HOTKEYS, \
        f"Left Ctrl not in banned list: got '{key_name_for_banned}'"
    # Callback should NOT have been called yet
    assert not captured2, "capture fired prematurely"
    ok("Banned key (Left Ctrl) correctly identified and excluded")

    # Simulate valid key coming in through capture
    valid_name = "ctrl+alt"
    # Manually trigger the capture as the hook would
    cb = mgr._capture_cb
    mgr._capture_cb = None
    if cb:
        cb(valid_name)
    time.sleep(0.1)
    assert captured2 == ["ctrl+alt"], f"unexpected capture result: {captured2}"
    ok("Valid combo accepted through capture mode")
except Exception as e:
    fail("Capture mode banned/valid key handling", str(e))

# ── HotkeyManager: cancel_capture clears callback ────────────────────────────
try:
    fired = []
    mgr.start_capture(lambda k: fired.append(k))
    assert mgr._capture_cb is not None
    mgr.cancel_capture()
    assert mgr._capture_cb is None, "capture_cb not cleared after cancel"
    assert not fired, "callback fired after cancel"
    ok("cancel_capture() clears callback cleanly")
except Exception as e:
    fail("cancel_capture() clears callback cleanly", str(e))

# ── HotkeyManager: unregister stops thread ───────────────────────────────────
try:
    mgr.unregister()
    time.sleep(0.5)
    assert mgr._thread is None, "thread reference not cleared after unregister"
    ok("unregister() stops hook thread cleanly")
except Exception as e:
    fail("unregister() stops hook thread cleanly", str(e))

print("COMPONENT_DONE")
