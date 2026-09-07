# ARCHITECTURE — Class Auto-Launcher ("AutoPara")

> Read this file, plus `BACKEND.md` and `FRONTEND.md`, before starting any coding task in this
> project. Update the relevant file(s) as part of any change that alters architecture, data model,
> UI structure, or behavior. **Stale docs are a bug.**

## Purpose

A Windows tray application for a university student. It imports a weekly class schedule from a
`.docx` file, renders it as a Google-Calendar-style weekly grid, and opens each class's Zoom /
Google Meet link in the default browser a configurable lead time (default **1 minute**) before the
class starts. It launches with Windows, runs quietly in the tray, and never opens the same class
occurrence twice.

## Tech stack and why

| Concern | Choice | Rationale |
|---|---|---|
| Language / runtime | **Python 3.13** | Already installed on the target machine (3.13.7, 64-bit). |
| GUI | **PySide6** (Qt 6) | Native tray support, real widget grid, QSS styling. Node.js is **not installed** on this machine; Electron would have meant a ~150 MB toolchain install and a ~300 MB bundle for a single-user tray utility. |
| Storage | **SQLite** (stdlib `sqlite3`) | Zero extra dependency. Needs relational integrity for the "fire exactly once" guarantee (see below), which a flat JSON store cannot enforce. |
| docx parsing | **stdlib `zipfile` + `xml.etree`** | A `.docx` is a zip. We must read real cell merges (`w:gridSpan`, `w:vMerge`) and hyperlink relationships, which high-level converters flatten or lose. No third-party parser needed. |
| Autostart | **`HKCU\...\CurrentVersion\Run`** via stdlib `winreg` | User-scope (no admin), toggleable at runtime from the settings screen, and visible in Task Manager -> Startup so the user can disable it the normal way. Task Scheduler was rejected: it can require elevation and is invisible in the familiar Startup UI. |
| Packaging | **PyInstaller** (`--noconsole --onedir`) | Produces a self-contained folder + exe. |

## Process model

AutoPara is a single process. Qt's event loop serves both roles that the original Electron design
split into main/renderer:

- The **scheduler** is a `QTimer` on the main thread (see `core/scheduler.py`).
- The **UI** is an ordinary Qt window that can be closed without exiting the app.

Closing the window hides it to the tray; only "Quit" from the tray menu exits. A **single-instance
guard** (`QLocalServer` named socket) ensures a second launch surfaces the existing window instead
of starting a rival scheduler.

## Data flow

```
Робочий_розклад.docx
        |
        v
importer/docx_reader.py      zip -> word/document.xml + word/_rels/document.xml.rels
        |                    -> Table/Row/Cell model carrying logical column, gridSpan,
        |                       vMerge state, text lines, and hyperlink targets
        v
importer/schedule_parser.py  applies the domain rules (see BACKEND.md "Parsing rules")
        |                    -> Course[] / Group[] / Lesson[]
        v
core/storage.py              SQLite upsert; preserves manual edits + occurrence log
        |
        +--> ui/week_grid.py       renders the selected course+group's week
        |
        +--> core/scheduler.py     15s tick -> due? -> core/launcher.py -> default browser
                                             -> writes occurrences row (fire-once guarantee)
```

## The "fire exactly once" guarantee

This is the core correctness property of the app, and it is enforced by the database, not by
in-memory bookkeeping:

- `occurrences` has `UNIQUE(lesson_id, occur_date)`.
- The scheduler **inserts the row first, then opens the browser.** If the insert raises
  `IntegrityError`, the occurrence already fired and the browser call is skipped.
- Because the key is `(lesson, date)` rather than a subject name, the same weekly class recurring
  every week is a distinct occurrence each week, while an app restart, a sleep/wake cycle, or a
  clock adjustment on the same day cannot cause a second open.

## Scheduling and catch-up

The scheduler polls every **15 seconds** rather than arming one-shot timers, so it degrades
gracefully across suspend/resume and picks up settings changes without re-arming anything.

Each tick, for every lesson scheduled today:

- `now >= start - lead` and `now < start` -> **fire**: open the link, record `opened`.
- `now >= start` and `now < end` -> **catch-up**: the trigger moment was missed (app was closed or
  the machine asleep). Rather than ambushing the user with a browser window on boot, the app shows
  a tray notification naming the class; clicking it opens the link and records `manual`. This is
  the user-selected catch-up policy.
- `now >= end` -> record `missed`; the card is highlighted in the grid but nothing opens.

Lessons with no link (`needs_link`) are never auto-opened; they render with a "no link" badge and
can be given a URL through Edit mode.

## Module map

| Module | Responsibility |
|---|---|
| `autopara/__main__.py` | Entry point. Parses `--hidden` (used by the autostart registry entry). |
| `autopara/app.py` | `QApplication` bootstrap, single-instance guard, wires storage + scheduler + UI + tray. |
| `autopara/importer/docx_reader.py` | Physical layer: zip/XML -> cell grid with merge metadata and link targets. |
| `autopara/importer/schedule_parser.py` | Domain layer: cell grid -> courses/groups/lessons. |
| `autopara/importer/normalize.py` | Text normalization: days, times, pairs, URLs, providers, Unicode. |
| `autopara/core/models.py` | Dataclasses shared across layers. |
| `autopara/core/storage.py` | SQLite schema, migrations, queries, import transaction. |
| `autopara/core/scheduler.py` | The 15s tick loop and due/catch-up decisions. |
| `autopara/core/launcher.py` | Opens a URL in the default browser. |
| `autopara/core/autostart.py` | Registry `Run` key add/remove/query. |
| `autopara/ui/*` | See `FRONTEND.md`. |

## Storage location

`%APPDATA%\AutoPara\autopara.db`. Chosen over a file next to the exe so the app keeps working when
installed into `Program Files`, where a normal user cannot write.

## Entry points

| Path | Used by |
|---|---|
| `python -m autopara` | Development runs. |
| `autopara_launch.pyw` | The autostart registry entry when running from source. A `.pyw` under `pythonw.exe` starts with no console window, and the absolute path makes it independent of the working directory Windows hands it at logon. |
| `dist/AutoPara/AutoPara.exe` | The packaged build. |

All three accept `--hidden`, which starts the app straight to the tray with no window.

## Single instance

`app.py` opens a `QLocalServer` named `AutoPara.SingleInstance`. A second launch connects to it,
asks the running instance to surface its window, and exits. Without this, autostart plus a manual
launch would run two schedulers against the same database — the `UNIQUE` constraint would still
prevent a double browser open, but the duplicate process would be wasted.

## Logging

`%APPDATA%\AutoPara\autopara.log`, at INFO level: opens, refusals and autostart failures. There is
no console handler, because the packaged app is windowed.

## Building

```
.\build.ps1
```

Two stages, both runnable on their own:

1. **`python -m PyInstaller AutoPara.spec --noconfirm`** -> `dist\AutoPara\` (~118 MB).
   `--onedir` is preferred over `--onefile` because it starts noticeably faster, which matters for
   an app that launches at logon; `--noconsole` stops a console window flashing at boot. Unused Qt
   modules (QML, WebEngine, Multimedia, Charts, ...) are excluded in the spec to keep the size down.
   The bundle is self-contained: it carries `python313.dll` and the VC++ runtime, so the target PC
   needs no Python and no redistributable.

2. **`makensis installer\AutoPara.nsi`** -> `dist\AutoPara-1.0.0-Setup.exe` (~35 MB, LZMA solid).
   Requires NSIS (`winget install NSIS.NSIS`).

### Installer design

Per-user, deliberately: it installs to `%LOCALAPPDATA%\Programs\AutoPara`, needs no administrator
rights and raises no UAC prompt. Autostart lives in `HKCU` anyway, so a machine-wide install would
buy nothing while making it harder to try on a borrowed PC.

It creates Start Menu and (optionally) desktop shortcuts, registers an Add/Remove Programs entry,
and offers a "start automatically with Windows" component. That component writes exactly the string
`autostart.startup_command()` produces for a frozen build -- `"<exe>" --hidden` -- so the app's own
Settings screen sees the installer's entry as already enabled and can toggle it off later. If the
two ever diverged, `autostart.sync()` would silently rewrite the entry on the next launch.

Uninstalling removes the program, shortcuts and both registry entries, but **keeps**
`%APPDATA%\AutoPara` (the imported timetable and settings) unless the user opts to delete it, so
reinstalling does not lose the schedule. A silent uninstall always keeps it rather than blocking on
a prompt.

## Testing

```
python -m pytest
```

87 tests, no waiting and no real browser: `pytest.ini` forces Qt's `offscreen` platform, the browser
call is stubbed, and the scheduler's clock is injected so a full teaching day is simulated at
15-second resolution in milliseconds.

Qt permits one application object per process, so every Qt-dependent test shares the single
session-scoped `qapp` fixture in `tests/conftest.py`.

The parser tests run against the real schedule document. It is not committed (it holds live meeting
links); the fixture finds it on the Desktop or via `AUTOPARA_TEST_DOCX`, and skips if absent.
