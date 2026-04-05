"""
User-flow regression tests for Flow.
Exercises settings interactions, worker processing, cleanup/transcription fallbacks,
and overlay state transitions without requiring manual desktop input.
"""

import os
import sys
import tempfile
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import flow_ui as flow_ui_module
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


def ok(name):
    print(f"USER_PASS:{name}")


def fail(name, reason=""):
    print(f"USER_FAIL:{name}:{reason}")


class SignalSpy:
    def __init__(self, signal):
        self.events = []
        self._signal = signal
        self._signal.connect(self._handler)

    def _handler(self, *args):
        self.events.append(args)

    def close(self):
        try:
            self._signal.disconnect(self._handler)
        except Exception:
            pass


class FakeHotkeyManager:
    def __init__(self):
        self.capture_requests = 0
        self.cancel_requests = 0

    def start_capture(self, callback):
        self.capture_requests += 1
        self.callback = callback

    def cancel_capture(self):
        self.cancel_requests += 1


class FakeWorkerRef:
    def __init__(self):
        self._hotkey_mgr = FakeHotkeyManager()
        self.updated_keys = []

    def update_hotkey(self, key):
        self.updated_keys.append(key)


class TestSettingsWindow(flow_ui_module.SettingsWindow):
    def __init__(self, *args, **kwargs):
        self.startup_calls = []
        super().__init__(*args, **kwargs)

    def _apply_startup(self, enabled):
        self.startup_calls.append(enabled)


original_cfg = dict(flow_ui_module.cfg)
original_save_config = flow_ui_module.save_config
original_clip_copy = flow_ui_module.pyperclip.copy
original_send_paste = flow_ui_module._send_paste
original_get_foreground_window = flow_ui_module._get_foreground_window
original_restore_window = flow_ui_module._restore_window
original_get_cursor_pos = flow_ui_module._get_cursor_pos
original_window_from_point = flow_ui_module._window_from_point
original_click_point = flow_ui_module._click_point
original_send_paste_message = flow_ui_module._send_paste_message
original_get_window_class_name = flow_ui_module._get_window_class_name
original_send_text_unicode = flow_ui_module._send_text_unicode
original_uia_element_from_point = flow_ui_module._uia_element_from_point
original_uia_focus_point = flow_ui_module._uia_focus_point
original_uia_set_value_at_point = flow_ui_module._uia_set_value_at_point
original_openai_module = sys.modules.get("openai")
original_requests_module = sys.modules.get("requests")


def restore_cfg():
    flow_ui_module.cfg.clear()
    flow_ui_module.cfg.update(original_cfg)


def cleanup_modules():
    if original_openai_module is None:
        sys.modules.pop("openai", None)
    else:
        sys.modules["openai"] = original_openai_module

    if original_requests_module is None:
        sys.modules.pop("requests", None)
    else:
        sys.modules["requests"] = original_requests_module


try:
    flow_ui_module.save_config = lambda cfg: None

    # Settings window flows
    try:
        restore_cfg()
        copied = []
        flow_ui_module.pyperclip.copy = lambda text: copied.append(text)

        worker_ref = FakeWorkerRef()
        win = TestSettingsWindow(worker_ref=worker_ref)
        win.show()
        app.processEvents()

        win.cleanup_check.setChecked(True)
        app.processEvents()
        assert flow_ui_module.cfg["cleanup_enabled"] is True
        assert win.engine_openai.isEnabled() and win.engine_ollama.isEnabled()
        assert not win.openai_card.isHidden()
        assert "Current hotkey" in win.hotkey_hint.text()

        win.engine_ollama.setChecked(True)
        app.processEvents()
        assert flow_ui_module.cfg["cleanup_engine"] == "ollama"
        assert win.openai_card.isHidden()

        win._on_context_changed("code")
        assert flow_ui_module.cfg["context"] == "code"
        assert win.ctx_btns["code"].isChecked()

        win.startup_check.setChecked(True)
        app.processEvents()
        assert win.startup_calls and win.startup_calls[-1] is True
        assert flow_ui_module.cfg["launch_at_startup"] is True

        win.dict_wrong.setText("pie torch")
        win.dict_right.setText("PyTorch")
        win._add_dict_entry()
        assert flow_ui_module.cfg["dictionary"]["pie torch"] == "PyTorch"
        assert win.dict_list.count() == 1

        win.dict_list.setCurrentRow(0)
        win._remove_dict_entry()
        assert "pie torch" not in flow_ui_module.cfg["dictionary"]
        assert win.dict_list.count() == 0

        flow_ui_module.cfg["history"] = [
            "first history entry",
            "second history entry that is long enough to verify the copy path still uses the full stored value",
        ]
        win._refresh_history(flow_ui_module.cfg["history"])
        assert win.history_list.count() == 2
        win._copy_history_item(win.history_list.item(0))
        app.processEvents()
        assert copied[-1] == flow_ui_module.cfg["history"][-1]

        win._clear_history()
        assert flow_ui_module.cfg["history"] == []
        assert win.history_list.count() == 0

        win._start_hotkey_capture()
        app.processEvents()
        assert "Hold your modifiers" in win.hotkey_hint.text()
        win._on_banned_key("left ctrl")
        assert "won't work" in win.hotkey_hint.text()
        win._on_app_state_changed(flow_ui_module.Qt.ApplicationState.ApplicationInactive)
        app.processEvents()
        assert not win.hotkey_capturing
        assert worker_ref._hotkey_mgr.cancel_requests >= 1

        win.close()
        ok("Settings flows update config, history, dictionary, and startup state")
    except Exception as e:
        fail("Settings flows update config, history, dictionary, and startup state", str(e))

    # Worker processing success path
    try:
        restore_cfg()
        copied = []
        paste_calls = []
        flow_ui_module.pyperclip.copy = lambda text: copied.append(text)
        flow_ui_module._send_paste = lambda: paste_calls.append("paste")

        flow_ui_module.cfg["dictionary"] = {"pie torch": "PyTorch"}
        flow_ui_module.cfg["history"] = [f"old {i}" for i in range(30)]
        flow_ui_module.cfg["cleanup_enabled"] = False

        worker = flow_ui_module.FlowWorker()
        worker._transcribe = lambda path: "pie torch is great"
        processing_spy = SignalSpy(flow_ui_module.signals.set_processing)
        done_spy = SignalSpy(flow_ui_module.signals.set_done)
        idle_spy = SignalSpy(flow_ui_module.signals.set_idle)
        history_spy = SignalSpy(flow_ui_module.signals.history_updated)

        worker.audio_frames = [b"\x00\x00"] * 6
        worker._process()
        app.processEvents()

        assert copied == ["PyTorch is great"]
        assert paste_calls == ["paste"]
        assert worker._target_hwnd == 0
        assert worker._target_point is None
        assert worker._target_point_hwnd == 0
        assert flow_ui_module.cfg["history"][-1] == "PyTorch is great"
        assert len(flow_ui_module.cfg["history"]) == 30
        assert processing_spy.events
        assert done_spy.events and done_spy.events[-1][0] == "Pasted!"
        assert not idle_spy.events
        assert history_spy.events and history_spy.events[-1][0][-1] == "PyTorch is great"

        processing_spy.close()
        done_spy.close()
        idle_spy.close()
        history_spy.close()
        ok("Worker processing saves history, updates clipboard, and emits success signals")
    except Exception as e:
        fail("Worker processing saves history, updates clipboard, and emits success signals", str(e))

    # Worker captures active target window on press
    try:
        restore_cfg()
        flow_ui_module._get_foreground_window = lambda: 0x4321
        flow_ui_module._get_cursor_pos = lambda: (111, 222)
        flow_ui_module._window_from_point = lambda point: 0x5678 if point == (111, 222) else 0
        flow_ui_module._uia_element_from_point = lambda point: ("element", "ProseMirror ProseMirror-focused", "")
        worker = flow_ui_module.FlowWorker()
        worker._record_loop = lambda: None
        worker._on_press()
        app.processEvents()
        assert worker._target_hwnd == 0x4321
        assert worker._target_point == (111, 222)
        assert worker._target_point_hwnd == 0x5678
        assert worker._target_uia_class == "ProseMirror ProseMirror-focused"
        assert worker.recording is True
        worker.recording = False
        ok("Worker captures active target window when recording starts")
    except Exception as e:
        fail("Worker captures active target window when recording starts", str(e))

    # Worker short audio path
    try:
        restore_cfg()
        flow_ui_module._send_paste = lambda: (_ for _ in ()).throw(RuntimeError("paste should not happen"))
        flow_ui_module.pyperclip.copy = lambda text: (_ for _ in ()).throw(RuntimeError("copy should not happen"))
        worker = flow_ui_module.FlowWorker()
        idle_spy = SignalSpy(flow_ui_module.signals.set_idle)
        worker.audio_frames = [b"\x00\x00"] * 4
        worker._process()
        app.processEvents()
        assert idle_spy.events, "idle signal was not emitted"
        idle_spy.close()
        ok("Worker ignores too-short recordings without pasting")
    except Exception as e:
        fail("Worker ignores too-short recordings without pasting", str(e))

    # Cleanup/transcribe fallback behavior
    try:
        restore_cfg()
        captured_api_keys = []

        class FakeOpenAI:
            def __init__(self, api_key):
                captured_api_keys.append(api_key)
                self.audio = types.SimpleNamespace(
                    transcriptions=types.SimpleNamespace(
                        create=lambda **kwargs: types.SimpleNamespace(text="from api")
                    )
                )
                self.chat = types.SimpleNamespace(
                    completions=types.SimpleNamespace(
                        create=lambda **kwargs: types.SimpleNamespace(
                            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="cleaned text"))]
                        )
                    )
                )

        sys.modules["openai"] = types.SimpleNamespace(OpenAI=FakeOpenAI)
        os.environ.pop("OPENAI_API_KEY", None)
        flow_ui_module.cfg["openai_api_key"] = "cfg-key"

        worker = flow_ui_module.FlowWorker()
        worker.whisper = None

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"fake wav")
            tmp_path = tmp.name

        try:
            transcribed = worker._transcribe(tmp_path)
        finally:
            os.unlink(tmp_path)

        flow_ui_module.cfg["cleanup_engine"] = "openai"
        flow_ui_module.cfg["context"] = "general"
        cleaned = worker._cleanup("raw text")
        flow_ui_module.cfg["openai_api_key"] = ""
        raw_no_key = worker._cleanup("leave me alone")

        class FailingRequests:
            @staticmethod
            def post(*args, **kwargs):
                raise RuntimeError("network down")

        sys.modules["requests"] = FailingRequests
        flow_ui_module.cfg["cleanup_engine"] = "ollama"
        ollama_fallback = worker._cleanup("keep this")

        assert transcribed == "from api"
        assert captured_api_keys[:2] == ["cfg-key", "cfg-key"]
        assert cleaned == "cleaned text"
        assert raw_no_key == "leave me alone"
        assert ollama_fallback == "keep this"
        ok("Cleanup and transcription fallbacks honor settings and recover from missing services")
    except Exception as e:
        fail("Cleanup and transcription fallbacks honor settings and recover from missing services", str(e))
    finally:
        cleanup_modules()

    # Flow pill state transitions
    try:
        restore_cfg()
        pill = flow_ui_module.FlowPill()
        pill.hide()

        flow_ui_module.signals.start_recording.emit()
        app.processEvents()
        assert pill.state == pill.STATE_RECORDING

        flow_ui_module.signals.set_processing.emit()
        app.processEvents()
        assert pill.state == pill.STATE_PROCESSING

        flow_ui_module.signals.set_done.emit("Done!")
        app.processEvents()
        assert pill.state == pill.STATE_DONE
        assert pill.done_text == "Done!"

        pill._go_idle()
        app.processEvents()
        assert pill.state == pill.STATE_IDLE
        pill.close()
        ok("Overlay pill responds to recording, processing, done, and idle states")
    except Exception as e:
        fail("Overlay pill responds to recording, processing, done, and idle states", str(e))

finally:
    restore_cfg()
    flow_ui_module.save_config = original_save_config
    flow_ui_module.pyperclip.copy = original_clip_copy
    flow_ui_module._send_paste = original_send_paste
    flow_ui_module._get_foreground_window = original_get_foreground_window
    flow_ui_module._restore_window = original_restore_window
    flow_ui_module._get_cursor_pos = original_get_cursor_pos
    flow_ui_module._window_from_point = original_window_from_point
    flow_ui_module._click_point = original_click_point
    flow_ui_module._send_paste_message = original_send_paste_message
    flow_ui_module._get_window_class_name = original_get_window_class_name
    flow_ui_module._send_text_unicode = original_send_text_unicode
    flow_ui_module._uia_element_from_point = original_uia_element_from_point
    flow_ui_module._uia_focus_point = original_uia_focus_point
    flow_ui_module._uia_set_value_at_point = original_uia_set_value_at_point
    cleanup_modules()

print("USER_DONE")
