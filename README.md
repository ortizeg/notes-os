# NotesOS — PARA Notes Sorter

Keyboard-driven PARA notes sorter for Apple Notes (M1).

> Active milestone: M1 — PARA Notes Sorter

NotesOS triages your Apple Notes inbox into a PARA folder structure
(**P**rojects / **A**reas / **R**esources / **A**rchive) using single keystrokes.
Notes are **moved, never deleted**, and the Notes database is backed up
automatically before every write. It runs entirely on macOS via an AppleScript
bridge and has no network dependencies in M1.

## Requirements

- **macOS** with the **Apple Notes** app installed and at least one account
  configured (local "On My Mac" is fine).
- **Python 3.11 or 3.12**.
- [`pixi`](https://pixi.sh) for environment and task management (the repo ships a
  `pixi.toml`).

## macOS permissions (required on first run)

NotesOS drives Apple Notes through AppleScript and copies the Notes database for
its pre-write backup. macOS gates both behind **TCC (Transparency, Consent &
Control)** prompts. Your **terminal app** (Terminal, iTerm2, etc.) — not Python —
is the application that must be granted access, so the grants follow whichever
terminal you launch `notes` from.

Two **separate** grants are needed:

1. **Automation → Notes** — lets the terminal send AppleScript commands to the
   Notes app (read the inbox, move notes, create folders). macOS shows an
   *"… wants to control Notes"* prompt the first time NotesOS talks to Notes;
   click **OK**. To grant it manually:
   **System Settings → Privacy & Security → Automation → _your terminal_ →
   enable _Notes_.**

2. **Full Disk Access** — lets the terminal read and copy `NoteStore.sqlite`
   (under `~/Library/Group Containers/group.com.apple.notes/`) so a backup can be
   taken **before** any move. macOS does **not** prompt for this automatically —
   you must add it manually:
   **System Settings → Privacy & Security → Full Disk Access → add _your
   terminal_ →** enable it, then **fully quit and reopen the terminal** for the
   grant to take effect.

> **Why both?** NotesOS will not move a note unless it can first back up the
> Notes database. Without **Full Disk Access** every move aborts on a backup
> `PermissionError` — this is by design: **no backup ⇒ no write.**

### Verify your grants

```bash
# Automation → Notes (should print a note count, not a permission error):
osascript -e 'tell application "Notes" to count notes'

# Full Disk Access (should list the file, not "Operation not permitted"):
ls -l ~/Library/Group\ Containers/group.com.apple.notes/NoteStore.sqlite
```

If the first command raises *"Not authorized to send Apple events to Notes"* or
the second raises *"Operation not permitted"*, revisit the matching grant above
(and remember to relaunch the terminal after changing Full Disk Access).

## Usage

```bash
pixi run notes     # launch the TUI
```

## Development

```bash
pixi run notes     # run the app
pixi run ruff      # lint (ruff check + format --check)
pixi run format    # auto-format (ruff format + ruff check --fix)
pixi run mypy      # type-check (strict)
pixi run pytest    # run tests (integration tests are deselected by default)
```

Integration tests are macOS-only, marked `@pytest.mark.integration`, and operate
on dedicated `_Test…` Notes folders — they never touch your real notes. Run them
explicitly with:

```bash
pixi run pytest -m integration
```
