# Deferred items — Phase 12 (backup cadence)

## Out-of-scope stale doc (not fixed)

- **File:** `src/notes_os/backup_models.py` (line ~63)
- **Item:** The `BackupConfig.auto_backup_on_write` field docstring still reads
  "fires a backup before every write operation (``move_note``, ``ensure_folder``)".
- **Why deferred:** `backup_models.py` is NOT in this plan's `files_modified`
  set, and the `auto_backup_on_write` flag's on/off semantics are genuinely
  unchanged (it remains the master switch). Only the cadence (per-write →
  per-session) changed. Rewording this docstring is a pure-doc follow-up that
  touches a file outside the plan's declared scope.
- **Suggested follow-up wording:** "When ``True`` (the default), the
  ``BackingUpNotesRepository`` decorator captures a restore point before the
  first write of each triage session. Set to ``False`` to disable auto-backup."
