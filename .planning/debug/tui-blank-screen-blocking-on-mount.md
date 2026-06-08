---
status: fixing
trigger: "TUI shows blank screen — HomeScreen.on_mount and SortScreen.on_mount call get_inbox_notes() synchronously, blocking the Textual event loop before first paint"
created: 2026-06-08T00:00:00Z
updated: 2026-06-08T00:00:00Z
---

## Current Focus

hypothesis: "HomeScreen.on_mount and SortScreen.on_mount both call app.repo.get_inbox_notes() (blocking osascript subprocess) synchronously on the Textual event-loop thread, freezing the event loop before first paint → blank screen"
test: "Code review confirms — no async/thread delegation in either on_mount"
expecting: "Moving I/O to @work(thread=True) workers with call_from_thread UI updates will let the screen paint immediately"
next_action: "Apply fix to home.py and sort.py, update tests to await workers, verify all gates"

reasoning_checkpoint:
  hypothesis: "on_mount calls get_inbox_notes() and backup_manager.list() synchronously on the Textual event-loop thread; these call osascript (a blocking subprocess) which stalls the event loop before Textual's first paint cycle completes"
  confirming_evidence:
    - "home.py line 136: notes = app.repo.get_inbox_notes() — synchronous, no await, no thread"
    - "sort.py line 183: self._notes = app.repo.get_inbox_notes() — synchronous, no await, no thread"
    - "home.py line 145: backups = app.backup_manager.list() — synchronous, no await, no thread"
    - "Textual event loop is single-threaded; any blocking call in on_mount stalls it before first render"
    - "macOS Automation permission prompt blocks osascript indefinitely on first launch"
  falsification_test: "If moving these calls to thread workers does NOT fix the blank screen, then the blocking call is elsewhere (not in these on_mount methods)"
  fix_rationale: "Thread workers run off the event loop; call_from_thread marshals UI updates back safely; the screen paints immediately with placeholder text while the worker runs"
  blind_spots: "Per-move operations also block (~1s each) but are acceptable for M1; not changing them"

## Symptoms

expected: "TUI paints immediately on launch showing the home screen with status indicators"
actual: "Blank screen indefinitely — screen never paints"
errors: "No error — the event loop is simply blocked before first paint"
reproduction: "Run pixi run notes (or .pixi/envs/default/bin/python -m notes_os) on first launch or with real Notes access"
started: "Always broken when used with real AppleScript backend; MockNotesRepository returns instantly so tests never caught it"

## Eliminated

- hypothesis: "Bug in Textual version / setup"
  evidence: "Tests pass with MockNotesRepository; the freeze is specific to blocking I/O in on_mount"
  timestamp: 2026-06-08T00:00:00Z

## Evidence

- timestamp: 2026-06-08T00:00:00Z
  checked: "home.py on_mount (lines 124-158)"
  found: "Directly calls app.repo.get_inbox_notes() and app.backup_manager.list() synchronously"
  implication: "Any blocking implementation of these (like AppleScript subprocess) will stall event loop"

- timestamp: 2026-06-08T00:00:00Z
  checked: "sort.py on_mount (lines 168-193)"
  found: "Directly calls app.repo.get_inbox_notes() synchronously before any render"
  implication: "SortScreen also blocks on load"

- timestamp: 2026-06-08T00:00:00Z
  checked: "Textual @work(thread=True) decorator and call_from_thread"
  found: "Available in textual 8.2.7; app.workers.wait_for_complete() available for test synchronization"
  implication: "Can offload blocking I/O to threads and marshal UI updates back"

## Resolution

root_cause: "HomeScreen.on_mount and SortScreen.on_mount call blocking I/O (get_inbox_notes() via osascript subprocess, backup_manager.list()) synchronously on Textual's event-loop thread, preventing first paint"
fix: "Move I/O calls to @work(thread=True, exclusive=True) methods; set placeholder text in on_mount; marshal UI updates via self.app.call_from_thread(); guard on_key with _loading flag in SortScreen"
verification: ""
files_changed: [src/notes_os/screens/home.py, src/notes_os/screens/sort.py, tests/screens/test_home_screen.py, tests/screens/test_sort_screen.py, tests/screens/test_navigation.py, tests/screens/test_end_to_end.py]
