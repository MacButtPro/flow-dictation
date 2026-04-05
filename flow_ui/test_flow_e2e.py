"""
Flow E2E Test Suite
Double-click TEST_FLOW.bat to run, or: python test_flow_e2e.py

Tests:
  1.  Syntax check
  2.  Config write/read
  3.  Config merges with defaults
  4.  Component tests for HotkeyManager + SendInput
  5.  User-flow regression tests for settings, worker, cleanup, overlay
  6.  Full app: starts up, hook installs, and stays running
  7.  Full app: no errors/tracebacks in log

Results saved to: test_flow_e2e_results.txt
"""

import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(SCRIPT_DIR, "flow_log.txt")
RESULTS_PATH = os.path.join(SCRIPT_DIR, "test_flow_e2e_results.txt")

passed = []
failed = []

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def ok(name):
    passed.append(name)
    print(f"  ✅ {name}")


def fail(name, reason=""):
    failed.append((name, reason))
    print(f"  ❌ {name}" + (f"\n     → {reason}" if reason else ""))


def section(title):
    print(f"\n── {title} {'─' * max(0, 50 - len(title))}")


def log_size():
    try:
        return os.path.getsize(LOG_PATH)
    except Exception:
        return 0


def wait_for_log(text, timeout=30, after_pos=0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as handle:
                handle.seek(after_pos)
                if text in handle.read():
                    return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def run_subprocess_suite(script_name, done_marker, pass_prefix, fail_prefix, title, timeout=90):
    section(title)
    try:
        result = subprocess.run(
            [sys.executable, script_name],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if done_marker not in output:
            fail(f"{title} subprocess completed", f"Did not finish — output:\n{output[:700]}")
            return

        for line in output.splitlines():
            if line.startswith(pass_prefix):
                ok(line[len(pass_prefix):])
            elif line.startswith(fail_prefix):
                parts = line[len(fail_prefix):].split(":", 1)
                fail(parts[0], parts[1] if len(parts) > 1 else "")
    except subprocess.TimeoutExpired:
        fail(f"{title} subprocess completed", f"timed out after {timeout}s")
    except Exception as exc:
        fail(f"{title} subprocess completed", str(exc))


section("1. Syntax check")
try:
    import py_compile

    py_compile.compile(os.path.join(SCRIPT_DIR, "flow_ui.py"), doraise=True)
    ok("flow_ui.py compiles without syntax errors")
except py_compile.PyCompileError as exc:
    fail("flow_ui.py compiles without syntax errors", str(exc))


section("2–3. Config")
try:
    cfg_path = os.path.join(SCRIPT_DIR, "_test_cfg.json")
    test_cfg = {"hotkey": "right alt", "history": [], "dictionary": {}}
    with open(cfg_path, "w", encoding="utf-8") as handle:
        json.dump(test_cfg, handle)
    with open(cfg_path, "r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    assert loaded["hotkey"] == "right alt"
    os.unlink(cfg_path)
    ok("Config write/read roundtrip")

    defaults = {"hotkey": "right alt", "cleanup_enabled": False, "context": "general"}
    merged = {**defaults, **loaded}
    assert merged["cleanup_enabled"] is False
    ok("Config merges with defaults correctly")
except Exception as exc:
    fail("Config tests", str(exc))


run_subprocess_suite(
    "_test_components.py",
    "COMPONENT_DONE",
    "COMPONENT_PASS:",
    "COMPONENT_FAIL:",
    "4. Component tests (HotkeyManager + SendInput)",
    timeout=60,
)

run_subprocess_suite(
    "_test_user_flows.py",
    "USER_DONE",
    "USER_PASS:",
    "USER_FAIL:",
    "5. User-flow regression tests",
    timeout=90,
)


section("6–7. Full app launch + startup log")
print("  Starting Flow — waiting for Whisper to load (up to 60s)…")

start_pos = log_size()
proc = None

try:
    proc = subprocess.Popen(
        [sys.executable, "flow_ui.py"],
        cwd=SCRIPT_DIR,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    print(f"  Flow PID: {proc.pid}")

    if wait_for_log("Worker idle loop", timeout=60, after_pos=start_pos):
        ok("App starts up and hook installs successfully")
    else:
        fail("App starts up and hook installs successfully", "timed out waiting for worker idle loop")
        raise RuntimeError("startup failed")

    time.sleep(1.5)

    if wait_for_log("Hook thread started", timeout=5, after_pos=start_pos):
        ok("Hook thread started and is running")
    else:
        fail("Hook thread started and is running", "not seen in log")

    time.sleep(1)
    if proc.poll() is None:
        ok("App remains running after full startup (no crash)")
    else:
        fail("App remains running after full startup", f"exited with code {proc.returncode}")

    with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as handle:
        handle.seek(start_pos)
        session_log = handle.read()

    if "❌" in session_log or "Traceback" in session_log:
        err_lines = [
            line for line in session_log.splitlines()
            if "❌" in line or "Traceback" in line or "Error" in line
        ]
        fail("No errors or tracebacks in log during startup", "\n".join(err_lines[:5]))
    else:
        ok("No errors or tracebacks in log during startup")
except RuntimeError:
    pass
except Exception as exc:
    fail("Full app test", str(exc))
finally:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        print("  Flow terminated.")


total = len(passed) + len(failed)
print(f"\n{'═' * 52}")
print(f"  Results: {len(passed)} passed, {len(failed)} failed out of {total}")
print(f"{'═' * 52}")
if failed:
    print("\nFailed:")
    for name, reason in failed:
        print(f"  ❌ {name}")
        if reason:
            print(f"     {reason}")
else:
    print("\n  🎉 All tests passed!")

with open(RESULTS_PATH, "w", encoding="utf-8") as handle:
    handle.write(f"Flow E2E Test Results\n{'=' * 52}\n")
    handle.write(f"Passed: {len(passed)} / Failed: {len(failed)} / Total: {total}\n\n")
    handle.write("PASSED:\n")
    for name in passed:
        handle.write(f"  ✅ {name}\n")
    if failed:
        handle.write("\nFAILED:\n")
        for name, reason in failed:
            handle.write(f"  ❌ {name}\n")
            if reason:
                handle.write(f"     Reason: {reason}\n")
    handle.write("\nSee flow_log.txt for full app logs.\n")

print(f"\nResults saved to: test_flow_e2e_results.txt")
try:
    input("\nPress Enter to close…")
except EOFError:
    pass
