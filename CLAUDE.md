# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Living documentation — read before coding

`docs/ARCHITECTURE.md`, `docs/BACKEND.md` and `docs/FRONTEND.md` are the canonical design record and
must be **read before starting any coding task** and **updated in the same commit** as any change to
architecture, data model, UI structure or behavior. Stale docs are treated as a bug in this project.
Keep them concise and current rather than appending changelogs.

## Commands

```bash
python -m pytest                       # all 87 tests (~11 s)
python -m pytest tests/test_parser.py  # one file
python -m pytest -k shared             # by keyword
python -m pytest "tests/test_parser.py::TestMergeHandling::test_shared_class_is_one_lesson_with_many_groups"

python -m autopara                     # run from source
python -m autopara --hidden            # start to tray with no window (the autostart path)

.\build.ps1                            # PyInstaller bundle + NSIS installer -> dist\
.\build.ps1 -SkipApp                   # installer only, reusing dist\AutoPara\
```

No linter or formatter is configured; match the surrounding style.

### Test environment

- Tests need the **real schedule `.docx`, which is not in the repo** (it holds live meeting links).
  `tests/conftest.py` finds it on the Desktop or via `AUTOPARA_TEST_DOCX`, and **skips** if absent —
  so a "passing" run that skipped everything is not a passing run. Check the count.
- The browser is always stubbed and the scheduler's clock is injected; tests never open a URL and
  never wait on real time.
- Qt allows **one application object per process**, so every Qt-dependent test must use the shared
  session-scoped `qapp` fixture. Creating a second one crashes the whole run at teardown (exit 9).
- `conftest.py` selects Qt's `offscreen` platform before any Qt import; don't add a second mechanism.

## Architecture

Single-process PySide6 app. Qt's event loop serves both roles an Electron design would split:
the scheduler is a `QTimer` on the main thread, and the UI is an ordinary window that can be closed
without exiting. Chosen because Node.js is not installed on the target machine.

```
.docx -> importer/docx_reader.py     zip + XML -> cell grid with merge metadata + link targets
      -> importer/schedule_parser.py grid -> Course/Group/Lesson (the domain rules)
      -> core/storage.py             SQLite in %APPDATA%\AutoPara\autopara.db
      -> ui/week_grid.py             renders the selected group's week
      -> core/scheduler.py           15 s tick -> core/launcher.py -> default browser
```

**The database is the single source of truth.** The UI caches no lesson state; every mutation is
followed by a reload from storage.

### Invariant: open each class exactly once

Enforced by the database, not by in-memory bookkeeping. `occurrences` has
`UNIQUE(lesson_id, occur_date)`, and `Scheduler._open` **claims the row before opening the browser** —
an `IntegrityError` means it already fired, so the browser call is skipped. Keying on
`(lesson, date)` is what lets the same weekly class recur while a restart, sleep/wake or clock change
on the same day cannot double-open it. Preserve claim-before-open in any change to this path.

`Scheduler.evaluate()` is a pure function of `(lesson, now, lead, already_fired)` so trigger
boundaries are testable without a clock or event loop. Keep it pure; `tick(now)` must derive
everything from the injected time, including the weekday.

Polling every 15 s (rather than one-shot timers) is deliberate: it survives suspend/resume and
settings changes with no re-arming logic.

### The .docx parser — rules that look wrong but are not

`docs/BACKEND.md` section 2 has the full list with evidence. The ones most likely to be "simplified"
into bugs by someone who hasn't seen the source document:

- **Shared classes are real `w:gridSpan` merges, not repeated text.** Word stores a session taught to
  several groups as *one* `<w:tc>` spanning columns. Do not switch to comparing adjacent cell text —
  that is only a fallback (`_dedupe_adjacent_duplicates`) for documents from other tooling.
- **Never index cells positionally.** Rows contain different numbers of `<w:tc>` (4, 5, 7) because of
  merges. A cell's column is the running sum of preceding `gridSpan` values.
- **A group owns a column *range*.** A header cell can itself span (course IV: 7 grid columns, 2
  groups). A lesson belongs to every group whose range it overlaps.
- **Links appear twice** — as a `w:hyperlink` relationship *and* as visible text. Collect both, dedupe.
- **The day column is usually empty**, carried down from a `w:vMerge` restart row.
- Text needs NFC normalization and apostrophe folding: the document writes `П` + **backtick** (U+0060)
  for Friday, and course headings mix Cyrillic `І` (U+0406) with Latin `V`. Match courses by ordinal
  position, never by heading string.

Verified totals used as regression fixtures: **6 courses, 77 lessons, 60 with links, 17 without,
per course 25/11/12/13/0/16**. Course V having no classes is real data, not a parse failure — empty
schedules must stay a valid state throughout the stack.

### Windows integration

- **Autostart** is `HKCU\...\CurrentVersion\Run`, value `AutoPara`, via stdlib `winreg`. The NSIS
  installer writes the *same* value in the *same* format `"<exe>" --hidden` that
  `autostart.startup_command()` produces for a frozen build. If those ever diverge, `autostart.sync()`
  silently rewrites the entry on next launch — keep them identical.
- `startup_command()` differs frozen vs. from source (source uses `pythonw.exe` plus the absolute
  path to `autopara_launch.pyw`, because the Run key executes with an arbitrary working directory).
- **Only http/https URLs are ever opened** (`launcher.is_openable`). Link text comes from a document,
  so `file:` and `javascript:` values must never reach the shell.
- Closing the window hides to tray; only the tray's Quit exits. A `QLocalServer` single-instance
  guard makes a second launch surface the existing window.
- The installer is per-user (`%LOCALAPPDATA%\Programs\AutoPara`, no admin/UAC). Both of its prompts
  are guarded with `IfSilent`, or `/S` install and uninstall hang on an invisible message box.
  Uninstall keeps `%APPDATA%\AutoPara` so a reinstall does not lose the imported timetable.
