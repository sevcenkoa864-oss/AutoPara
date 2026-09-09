# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Living documentation — read before coding

`docs/ARCHITECTURE.md`, `docs/BACKEND.md` and `docs/FRONTEND.md` are the canonical design record and
must be **read before starting any coding task** and **updated in the same commit** as any change to
architecture, data model, UI structure or behavior. Stale docs are treated as a bug in this project.
Keep them concise and current rather than appending changelogs.

## Commands

```bash
python -m pytest                       # all 240 tests (~30 s)
python -m pytest tests/test_parser.py  # one file
python -m pytest -k shared             # by keyword
python -m pytest "tests/test_parser.py::TestMergeHandling::test_shared_class_is_one_lesson_with_many_groups"

python -m autopara                     # run from source
python -m autopara --hidden            # start to tray with no window (the autostart path)

.\build.cmd                            # PyInstaller bundle + NSIS installer -> dist\
.\build.cmd -SkipApp                   # installer only, reusing dist\AutoPara\
# build.cmd wraps build.ps1: Windows blocks .ps1 outright under its default execution policy.

```

No linter or formatter is configured; match the surrounding style.

`.github/workflows/installer.yml` runs `build.cmd` on `windows-latest` for every push to `main` and
attaches the installer to a GitHub release — but only when `APP_VERSION` in `installer/AutoPara.nsi`
names a version with no `v<version>` tag yet. **Bump that number in the commit you want released**;
otherwise the build still runs and the .exe is only a workflow artifact. See `docs/ARCHITECTURE.md`.

### Test environment

- Tests need the **real schedule `.docx`, which is not in the repo** (it holds live meeting links).
  `tests/conftest.py` searches the Desktop, Downloads (one level deep, so the messaging app's folder
  counts) and `%APPDATA%\AutoPara\schedules`, or takes `AUTOPARA_TEST_DOCX`. If it is missing,
  100+ tests **skip** and the run still reads green — so pytest's header prints which document was
  used, or `NOT FOUND`. Read that line before trusting a pass.
- **Never assert an exact link count.** The university fills links in over time (60 → 63 between two
  revisions with identical structure). Link tests compare against oracles read from the `.docx`
  itself; see `docs/BACKEND.md` section 1.
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

### Invariant: the interface is Ukrainian

Every user-visible string in `autopara/ui/` and in `installer/AutoPara.nsi` is Ukrainian. There is
no translation layer and no second locale — one locale needs no machinery.
`tests/test_ui.py::test_interface_is_ukrainian` walks the live widget tree and fails on Latin words
other than `AutoPara`, `Zoom`, `Meet`, `docx`; a second walk covers the import dialog. Docstrings,
comments and the design docs stay English.

**Nothing on the left-hand rail is written.** All four buttons are icons, the app mark stands in
for the word "AutoPara", and the course and group live in that mark's tooltip. Each button's
meaning is a Ukrainian tooltip; giving one a label puts a word back on screen that then has to be
translated, and widens a rail whose width is one button plus air.
`TestIconOnlyToolbar` fails if a button gains text or loses its tooltip, and
`test_the_sidebar_carries_no_words_at_all` walks the rail for any text at all.

The importer reads documents in other languages and converts what it finds (days, course labels)
into Ukrainian. Subject and teacher text is copied verbatim — it is data, not chrome.

### Invariant: open each class exactly once

Enforced by the database, not by in-memory bookkeeping. `occurrences` has
`UNIQUE(lesson_id, occur_date)`, and `Scheduler._open` **claims the row before opening the browser** —
an `IntegrityError` means it already fired, so the browser call is skipped. Keying on
`(lesson, date)` is what lets the same weekly class recur while a restart, sleep/wake or clock change
on the same day cannot double-open it. Preserve claim-before-open in any change to this path.

`Scheduler.evaluate()` is a pure function of `(lesson, now, lead, already_fired)` so trigger
boundaries are testable without a clock or event loop. Keep it pure; `tick(now)` must derive
everything from the injected time, including the weekday. `reminder_due()` is a *second* pure
function and must stay separate: a reminder is a message, and folding it into `evaluate` puts it
one keystroke away from opening a browser.

### Invariant: a class that is already running is never opened unasked

`Scheduler._cold_start` makes the first tick after `start()` treat catch-up as "ask", **whatever
`catchup_mode` says**. This fixes a real, reported bug — launching the app after a missed morning
opened a browser tab per still-running class — and it is not redundant with the notify default.
`open` mode applies from the second tick onward. `TestColdStartNeverAmbushes` and
`TestLaunchingIntoAMissedDay` exist to stop this being "simplified" back.

The same incident's other half: `launcher.open_url` calls `ShellExecuteW` and never falls back to
`webbrowser` on Windows, which can launch the browser through a console-subsystem child and flash
an empty black window per link.

### Invariant: the grid rebuild never detaches a widget

`WeekGrid._clear()` hides and deletes; `setParent(None)` on a live widget makes it a **top-level
window** until `deleteLater` runs, and rebuilding a week that way flashed dozens of empty windows
on screen. Opening a link triggers a rebuild, which is why this looked like a browser bug.

### Invariant: installing and refreshing replace, never merge

`Installation.purge_previous`, the NSIS install section and `core.refresh.refresh_installation` all
delete a directory before writing it. A module dropped upstream stays importable otherwise, which
is exactly why "reinstall and check" did not show new behaviour. `%APPDATA%\AutoPara\schedules`
(the imported `.docx`) is the one thing a reinstall spares; an uninstall spares nothing.

`python -m autopara` runs the refresh before starting, so a source run leaves the installed copy
up to date. `--no-rebuild` skips it.

### Invariant: a timetable only applies from the moment it is imported

`import_courses` stamps `schedule_active_from`; `Scheduler.predates_schedule` skips anything that
had already started by then — not opened, not offered, not marked missed. Importing at the weekend
to set up the coming week must not paint that weekend red.

`storage.mark_occurrence` is the one sanctioned way to write an occurrence row without claiming it
first: it records a decision the user made in the UI, and the row it writes is what stops the
scheduler acting on that class.

Polling every 15 s (rather than one-shot timers) is deliberate: it survives suspend/resume and
settings changes with no re-arming logic.

### The .docx parser — rules that look wrong but are not

`docs/BACKEND.md` section 2 has the full list with evidence. The ones most likely to be "simplified"
into bugs by someone who hasn't seen the source document:

- **Shared classes are real `w:gridSpan` merges, not repeated text.** Word stores a session taught to
  several groups as *one* `<w:tc>` spanning columns. Do not switch to comparing adjacent cell text —
  that is only a fallback (`_dedupe_adjacent_duplicates`) for documents from other tooling. This is
  about **columns**. Down the **rows** the opposite holds: a class retyped in the next time slot is
  the same session, and comparing that text is the primary strategy (`_merge_consecutive_slots`, R12)
  — a double class must be one lesson, or the browser opens again mid-meeting. Its adjacency test is
  load-bearing: the same subject can legitimately run twice in one day with a gap.
- **Never index cells positionally.** Rows contain different numbers of `<w:tc>` (4, 5, 7) because of
  merges. A cell's column is the running sum of preceding `gridSpan` values.
- **A group owns a column *range*.** A header cell can itself span (course IV: 7 grid columns, 2
  groups). A lesson belongs to every group whose range it overlaps.
- **Links appear twice** — as a `w:hyperlink` relationship *and* as visible text. Collect both, dedupe.
- **The day column is usually empty**, carried down from a `w:vMerge` restart row.
- Text needs NFC normalization and apostrophe folding: the document writes `П` + **backtick** (U+0060)
  for Friday, and course headings mix Cyrillic `І` (U+0406) with Latin `V`. Match courses by ordinal
  position, never by heading string.

Verified totals used as regression fixtures: **6 courses, 61 lessons (77 table rows, joined into 61
by R5/R12), 53 with links, 8 without, per course 24/10/8/10/0/9**. Course V having no classes is real
data, not a parse failure — empty schedules must stay a valid state throughout the stack.

### Windows integration

- **The app mark reaches Windows through two separate channels, and both have to be set.** The
  executable's icon is compiled in from `build\AutoPara.ico`, which `build.ps1` renders from
  `ui/tray.write_ico` before calling PyInstaller — every shortcut the installer creates inherits
  it, so without that step the desktop shows PyInstaller's stock Python logo. The *taskbar button*
  is separate: Windows attributes it to the host process unless the app calls
  `SetCurrentProcessExplicitAppUserModelID` (`app._claim_taskbar_identity`, before the first
  window), which is why a source run used to sit in the taskbar under Python's icon however
  carefully `setWindowIcon` was called. `tests/test_installer.py::TestApplicationIcon` guards both.

- **Autostart** is `HKCU\...\CurrentVersion\Run`, value `AutoPara`, via stdlib `winreg`. Both
  installers write the *same* value in the *same* format `"<launcher>" --hidden` that
  `autostart.startup_command()` produces. If those ever diverge, `autostart.sync()` silently
  rewrites the entry on next launch — keep them identical.
- **`autostart_enabled` defaults to `1`.** It used to default to `0` while the installer wrote the
  Run key anyway, so `sync(False)` deleted the installer's entry on first launch. The default and
  the installers have to agree.
- `startup_command()` differs frozen vs. from source (source uses `pythonw.exe` plus the absolute
  path to `autopara_launch.pyw`, because the Run key executes with an arbitrary working directory).
- **Only http/https URLs are ever opened** (`launcher.is_openable`). Link text comes from a document,
  so `file:` and `javascript:` values must never reach the shell.
- Closing the window hides to tray; only the tray's Quit exits. A `QLocalServer` single-instance
  guard makes a second launch surface the existing window.
- The NSIS installer is per-user (`%LOCALAPPDATA%\Programs\AutoPara`, no admin/UAC). Both of its
  prompts are guarded with `IfSilent`, or `/S` install and uninstall hang on an invisible message
  box. Uninstall keeps `%APPDATA%\AutoPara` so a reinstall does not lose the imported timetable.
- **One installer, on purpose.** `installer/AutoPara.nsi` ships the frozen PyInstaller bundle, so
  the target PC needs no Python, no PySide6 and no network. An install-from-source variant used to
  live beside it (`installer.exe` + `installer/install_app.py`); it was removed because for an end
  user it traded a single double-click for "find or install Python, then download ~100 MB of
  wheels", and a prebuilt 12 MB `installer.exe` committed to git went stale the moment the source
  changed. Contributors run from source with `pip install -r requirements.txt`.
  `tests/test_installer.py` parses the `.nsi` and fails if it drifts from the app: the autostart
  string, the window title `FindWindow` looks for, the `IfSilent` guards and the HKCU-only rule.