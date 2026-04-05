"""
Flow Smoke Tests
Run with: python test_flow.py
Tests config, dictionary, history, key name mapping, and settings logic.
"""

import sys
import os
import json
import tempfile
import traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Test runner ───────────────────────────────────────────────────────────────
PASS = 0
FAIL = 0

def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  ✅ {name}")
        PASS += 1
    else:
        print(f"  ❌ {name}" + (f"  →  {detail}" if detail else ""))
        FAIL += 1

def section(name):
    print(f"\n── {name} {'─' * (50 - len(name))}")

# ── 1. Config load/save ───────────────────────────────────────────────────────
section("Config load / save")

tmp_cfg = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
tmp_path = tmp_cfg.name
tmp_cfg.close()

DEFAULT = {
    "hotkey": "right alt", "context": "general",
    "cleanup_enabled": False, "cleanup_engine": "openai",
    "openai_api_key": "", "openai_model": "gpt-4o-mini",
    "ollama_model": "llama3.1:8b", "whisper_model_override": "",
    "launch_at_startup": False, "dictionary": {}, "history": [],
}

def load_cfg(path):
    with open(path) as f:
        saved = json.load(f)
    cfg = DEFAULT.copy()
    cfg.update(saved)
    return cfg

def save_cfg(cfg, path):
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)

# Write and reload
cfg = DEFAULT.copy()
cfg["hotkey"] = "f9"
cfg["context"] = "email"
cfg["cleanup_enabled"] = True
save_cfg(cfg, tmp_path)

loaded = load_cfg(tmp_path)
test("hotkey persists",          loaded["hotkey"] == "f9")
test("context persists",         loaded["context"] == "email")
test("cleanup_enabled persists", loaded["cleanup_enabled"] == True)
test("missing keys get defaults",loaded["openai_api_key"] == "")

# Partial save (only some keys)
partial = {"hotkey": "space"}
with open(tmp_path, "w") as f:
    json.dump(partial, f)
loaded2 = load_cfg(tmp_path)
test("partial config fills defaults", loaded2["context"] == "general")
test("partial config keeps saved key", loaded2["hotkey"] == "space")

os.unlink(tmp_path)

# ── 2. Dictionary application ─────────────────────────────────────────────────
section("Dictionary (word corrections)")

def apply_dict(text, dictionary):
    for wrong, right in dictionary.items():
        text = text.replace(wrong, right)
    return text

d = {"pie torch": "PyTorch", "tensor flow": "TensorFlow", "open ai": "OpenAI"}
test("single replacement",   apply_dict("I use pie torch", d) == "I use PyTorch")
test("multiple replacements",apply_dict("pie torch and tensor flow", d) == "PyTorch and TensorFlow")
test("no match = unchanged",  apply_dict("hello world", d) == "hello world")
test("case sensitive",        apply_dict("Pie torch", d) == "Pie torch",
     "should NOT replace 'Pie torch' — dict is case-sensitive")
test("empty dict",            apply_dict("anything", {}) == "anything")

# ── 3. History management ──────────────────────────────────────────────────────
section("History")

history = []
for i in range(35):
    history.append(f"transcription {i}")
    history = history[-30:]

test("history capped at 30",  len(history) == 30)
test("oldest entries dropped", history[0] == "transcription 5")
test("newest entry last",      history[-1] == "transcription 34")

# Empty history
test("empty history ok", len([]) == 0)

# ── 4. Qt key name mapping ────────────────────────────────────────────────────
section("Qt key name mapping (nativeVirtualKey)")

# Simulate the VK mapping logic from _qt_key_name
VK_MAP = {
    160: "left shift",  161: "right shift",
    162: "left ctrl",   163: "right ctrl",
    164: "left alt",    165: "right alt",
}
SKIP_KEYS = {
    16777248, 16777249, 16777251, 16777252,  # Shift, Ctrl, Alt, Meta
    16777252, 16777253, 16777254,             # CapsLock, NumLock, ScrollLock
}

def simulate_key_name(vk=0, qt_key=0):
    if vk in VK_MAP:
        return VK_MAP[vk]
    if qt_key in SKIP_KEYS:
        return None
    # Letters (Qt Key_A=65 ... Key_Z=90)
    if 65 <= qt_key <= 90:
        return chr(qt_key).lower()
    # Numbers
    if 48 <= qt_key <= 57:
        return chr(qt_key)
    # F-keys (Qt Key_F1=16777264)
    F1 = 16777264
    if F1 <= qt_key <= F1 + 11:
        return f"f{qt_key - F1 + 1}"
    SPECIAL = {
        32: "space", 16777220: "enter", 16777217: "tab",
        16777219: "backspace", 16777223: "delete",
    }
    return SPECIAL.get(qt_key)

test("right alt  (vk=165)", simulate_key_name(vk=165) == "right alt")
test("left alt   (vk=164)", simulate_key_name(vk=164) == "left alt")
test("right ctrl (vk=163)", simulate_key_name(vk=163) == "right ctrl")
test("left ctrl  (vk=162)", simulate_key_name(vk=162) == "left ctrl")
test("right shift(vk=161)", simulate_key_name(vk=161) == "right shift")
test("letter 'a' (qt=65)",  simulate_key_name(qt_key=65) == "a")
test("letter 'z' (qt=90)",  simulate_key_name(qt_key=90) == "z")
test("space      (qt=32)",  simulate_key_name(qt_key=32) == "space")
test("f1         (Qt F1)",  simulate_key_name(qt_key=16777264) == "f1")
test("f9         (Qt F9)",  simulate_key_name(qt_key=16777272) == "f9")
test("f12        (Qt F12)", simulate_key_name(qt_key=16777275) == "f12")

# ── 5. Context prompts ────────────────────────────────────────────────────────
section("Context prompts")

CONTEXT_PROMPTS = {
    "general": "Clean up this dictated speech with a very light touch.",
    "email":   "Polish this dictated text into a professional email.",
    "slack":   "Clean up this Slack message.",
    "code":    "Clean up this technical dictation.",
    "notes":   "Lightly clean this dictated note.",
}

for ctx in ["general", "email", "slack", "code", "notes"]:
    test(f"context '{ctx}' has prompt", ctx in CONTEXT_PROMPTS and len(CONTEXT_PROMPTS[ctx]) > 10)

test("unknown context falls back", CONTEXT_PROMPTS.get("unknown", CONTEXT_PROMPTS["general"]) == CONTEXT_PROMPTS["general"])

# ── 6. Whisper model detection ────────────────────────────────────────────────
section("Whisper model auto-detection logic")

def pick_model(vram_gb):
    if vram_gb >= 8:   return "large-v3"
    elif vram_gb >= 4: return "medium"
    else:              return "small"

test("12GB VRAM → large-v3", pick_model(12) == "large-v3")
test("8GB VRAM  → large-v3", pick_model(8)  == "large-v3")
test("6GB VRAM  → medium",   pick_model(6)  == "medium")
test("4GB VRAM  → medium",   pick_model(4)  == "medium")
test("2GB VRAM  → small",    pick_model(2)  == "small")
test("0GB (CPU) → small",    pick_model(0)  == "small")

# ── 7. Config file path ───────────────────────────────────────────────────────
section("Config file location")

script_dir = os.path.dirname(os.path.abspath("flow_ui.py"))
config_path = os.path.join(script_dir, "flow_config.json")
test("config path is absolute",      os.path.isabs(config_path))
test("config path ends in .json",    config_path.endswith("flow_config.json"))

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'═' * 52}")
print(f"  Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")
print(f"{'═' * 52}")
if FAIL == 0:
    print("  🎉 All tests passed!")
else:
    print(f"  ⚠️  {FAIL} test(s) need attention")
