"""
fix_keyboard.py - Run this to unstick any frozen keyboard keys.
Sends key-UP events for every modifier key so Windows releases them.
"""
import ctypes
import ctypes.wintypes
import time

INPUT_KEYBOARD  = 1
KEYEVENTF_KEYUP = 0x0002

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.wintypes.WORD),
        ("wScan",       ctypes.wintypes.WORD),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]

class INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_    = [("type", ctypes.wintypes.DWORD), ("_input", _INPUT_UNION)]

def release_key(vk):
    inp = INPUT(type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(wVk=vk, dwFlags=KEYEVENTF_KEYUP))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

# All modifier VK codes
MODIFIERS = {
    "Left Ctrl":    0xA2,
    "Right Ctrl":   0xA3,
    "Left Alt":     0xA4,
    "Right Alt":    0xA5,
    "Left Shift":   0xA0,
    "Right Shift":  0xA1,
    "Left Win":     0x5B,
    "Right Win":    0x5C,
    "Ctrl":         0x11,
    "Alt":          0x12,
    "Shift":        0x10,
}

print("Releasing all stuck modifier keys...")
for name, vk in MODIFIERS.items():
    release_key(vk)
    print(f"  Released: {name} (VK 0x{vk:02X})")
    time.sleep(0.02)

print("\nDone! Your keyboard should be back to normal.")
print("If keys are still stuck, try pressing and releasing Ctrl, Alt, and Shift manually once.")
