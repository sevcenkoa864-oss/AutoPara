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

**The interface is entirely Ukrainian.** The source document may be in any language the importer
recognises (see `BACKEND.md` R10); everything the app generates from it -- day names, course
labels, every string on screen -- is Ukrainian. An English label added to a dialog is a bug, not a
detail.

## Tech stack and why

| Concern | Choice | Rationale |
|---|---|---|
| Language / runtime | **Python 3.13** | Already installed on the target machine (3.13.7, 64-bit). |
| GUI | **PySide6** (Qt 6) | Native tray support, real widget grid, QSS styling. Node.js is **not installed** on this machine; Electron would have meant a ~150 MB toolchain install and a ~300 MB bundle for a single-user tray utility. |
| Storage | **SQLite** (stdlib `sqlite3`) | Zero extra dependency. Needs relational integrity for the "fire exactly once" guarantee (see below), which a flat JSON store cannot enforce. |
| docx parsing | **stdlib `zipfile` + `xml.etree`** | A `.docx` is a zip. We must read real cell merges (`w:gridSpan`, `w:vMerge`) and hyperlink relationships, which high-level converters flatten or lose. No third-party parser needed. The reader stops at the merge metadata; deciding that a class retyped in the next slot is the *same* class is a domain rule, resolved in `schedule_parser` (`BACKEND.md` R12). |
| Autostart | **`HKCU\...\CurrentVersion\Run`** via stdlib `winreg` | User-scope (no admin), toggleable at runtime from the settings screen, and visible in Task Manager -> Startup so the user can disable it the normal way. Task Scheduler was rejected: it can require elevation and is invisible in the familiar Startup UI. |
| Theming | **One QSS template + two palettes** (`core/theme.py`) | A single stylesheet whose colours are `$tokens`, substituted per theme. Two hand-written `.qss` files would drift: a rule added to one and forgotten in the other is invisible until someone switches theme. |
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

- `now >= start - notify` -> **remind** (when notifications are on): a tray notification, never a
  browser. The window is configurable. A reminder is a message, not a trigger, so it lives in its
  own pure function, `reminder_due`, and cannot be confused with a decision to open something.
- `now >= start - lead` and `now < start` -> **fire**: open the link, record `opened`.
- `now >= start` and `now < end` -> **catch-up**: the trigger moment was missed (app was closed or
  the machine asleep). The window comes forward with an in-app banner naming the class and two
  buttons, **Підключитися зараз** and **Закрити**. Nothing opens until one of them is pressed.
- `now >= end` -> record `missed`; the card is highlighted in the grid but nothing opens.

Lessons that had already started before the timetable was imported are skipped entirely — see
`BACKEND.md`, "The schedule starts when it is imported".

Lessons with no link (`needs_link`) are never auto-opened; they render with a "no link" badge, and
clicking one offers to add a URL or delete the class.

The user can also settle a class by hand from its card menu -- "opened" or "skipped". Both write an
`occurrences` row, which is exactly what makes `evaluate` return "already fired", so a class marked
skipped is never opened.

### Catch-up never ambushes on a cold start

The first tick after `Scheduler.start()` treats catch-up as "ask", **whatever `catchup_mode` says**
(`Scheduler._cold_start`). This is not belt-and-braces. Opening the app after a morning away used
to hand the shell one URL per class that had been running; they arrived as a burst of browser
windows the user then had to close, leaving calls on the way out. A class whose start has already
passed is never worth acting on without a person in the loop. `open` mode still applies from the
second tick onward -- that is, to a class that starts while the app is running.

That incident had a second cause worth keeping in mind: `webbrowser.open` on Windows can launch the
browser through a console-subsystem child process, which flashes an empty black window per link.
`launcher.open_url` hands the URL straight to `ShellExecuteW` and does not fall back to
`webbrowser` on Windows at all — falling back to the thing that causes the flashing would defeat
the point. It also drops a repeat of the same URL within three seconds, so two paths to "open"
racing each other cannot produce two browser windows.

The flashing had a third cause, on the Qt side rather than the shell side: see `FRONTEND.md`,
"Rebuilding the grid". Detaching widgets during a rebuild made them momentary top-level windows,
and opening a link triggers a rebuild.

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
| `autopara/core/theme.py` | Light/dark palettes, the Windows "app theme" probe, QSS templating. |
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

## Autostart is on out of the box

`autostart_enabled` defaults to `1`, and `app.run()` calls `autostart.sync()` on every launch. Both
installers write the identical `"<launcher>" --hidden` string that `autostart.startup_command()`
produces, so the app sees an installer's entry as already enabled instead of fighting it.

This matters more than it looks. The setting used to default to `0` while the NSIS installer wrote
the Run key anyway, so `sync(False)` **deleted the installer's entry on first launch** and the app
quietly stopped starting with Windows. The default and the installers have to agree.

## Single instance

`app.py` opens a `QLocalServer` named `AutoPara.SingleInstance`. A second launch connects to it,
asks the running instance to surface its window, and exits. Without this, autostart plus a manual
launch would run two schedulers against the same database — the `UNIQUE` constraint would still
prevent a double browser open, but the duplicate process would be wasted.

The `QApplication` is constructed **before** the check. `QLocalSocket` needs Qt's event dispatcher
to complete a connection; with no application object the probe quietly reports "nothing running"
and the guard does nothing at all.

## Logging

`%APPDATA%\AutoPara\autopara.log`, at INFO level: opens, refusals and autostart failures. There is
no console handler, because the packaged app is windowed.

## Building

```
.\build.cmd
```

Two stages, both runnable on their own:

1. **`python -m PyInstaller AutoPara.spec --noconfirm`** -> `dist\AutoPara\` (~118 MB).
   `--onedir` is preferred over `--onefile` because it starts noticeably faster, which matters for
   an app that launches at logon; `--noconsole` stops a console window flashing at boot. Unused Qt
   modules (QML, WebEngine, Multimedia, Charts, ...) are excluded in the spec to keep the size down.
   The bundle is self-contained: it carries `python313.dll` and the VC++ runtime, so the target PC
   needs no Python and no redistributable.

2. **`makensis installer\AutoPara.nsi`** -> `dist\AutoPara-1.1.0-Setup.exe` (~35 MB, LZMA solid).
   Requires NSIS (`winget install NSIS.NSIS`).

### The installer that people download is built by CI

`.github/workflows/installer.yml` runs those same two stages on a clean `windows-latest` runner on
every push to `main`, and attaches `AutoPara-<version>-Setup.exe` to a GitHub release. It calls
`build.cmd`, not a copy of its steps, so CI cannot pass along a path a local build does not take.

**The version in `installer/AutoPara.nsi` decides whether a release is cut.** The job reads
`APP_VERSION`, and creates the release only when no `v<version>` tag exists yet; a push that leaves
the number alone still builds and still uploads the `.exe` as a workflow artifact, it just does not
try to publish a second release under a tag that is taken. Releasing a change therefore means
bumping `APP_VERSION` in the commit that makes it. That number is already the single source of the
version -- it names the `OutFile`, the Add/Remove Programs entry and `VIProductVersion` -- and
anything in the workflow that tracked a version of its own would drift from the file the build
actually reads.

The suite runs before the build, and a failure stops the release. What it can check there is
limited: the real timetable is not in the repository, so the 100+ document-backed parser tests
**skip** on the runner exactly as they do on a machine that has lost the file. CI guards the rest --
imports, the scheduler, the widgets, `tests/test_installer.py`'s agreement between the `.nsi` and
the app -- not the parser.

## Reinstalling replaces; uninstalling removes everything

Both installers **delete before they write**. Copying a new version over an old one leaves behind
modules that were renamed or deleted upstream, plus the `__pycache__` that goes with them, and
Python imports them quite happily — which is why reinstalling appeared not to apply changes at
all. `Installation.purge_previous` removes the install directory outright, and the NSIS script
does the same to `$INSTDIR\_internal`.

The same purge clears `%APPDATA%\AutoPara`, **except `schedules/`** — the copy of the imported
timetable, which the user should not have to hunt down again. Uninstalling makes no exception: it
removes the install directory, the shortcuts, all three registry keys and the whole data
directory, archived document included.

## `python -m autopara` rebuilds first

Checking a change used to mean running the installer again. A source run now refreshes the
installed copy from the tree it is running out of (`core/refresh.py`) before it starts, so the code
on screen and the code the Start-menu shortcut launches are the same code. `--no-rebuild` opts out;
a frozen build skips it, since the frozen build *is* the installation.

The refresh is a replace, per directory, for the same reason the installer's is: `runtime/` (the
virtual environment, minutes to rebuild) and `%APPDATA%\AutoPara` are the only things it leaves
alone. It finds the installation through `HKCU\Software\AutoPara\InstallDir`, which the
installer writes.

## One installer, on purpose

`installer/AutoPara.nsi` is the only installer. It ships the frozen PyInstaller bundle, so the
target machine needs nothing at all: no Python, no PySide6, no network, no administrator rights.

An install-from-source variant used to sit beside it — `installer.exe` in the repository root,
built from `installer/install_app.py`, with `installer.cmd` as its no-binary fallback. It was
removed. For the person the app is written for it turned a single double-click into "find or
install Python, then wait while ~100 MB of wheels download", with every one of those steps able to
fail on a locked-down or offline machine; and shipping a prebuilt 12 MB `installer.exe` inside the
repository put an unreviewable binary in version control that went stale as soon as the source
changed.

Nothing was lost by removing it. Running from the repository is still one command —
`pip install -r requirements.txt` then `python -m autopara` — which is what a contributor wants
anyway, and is documented in the README.

Because the script and the application have to agree about several strings, `tests/test_installer.py`
parses the `.nsi` and fails when they drift: the autostart command, the window title `FindWindow`
looks for, the `IfSilent` guards on both prompts, and the rule that a per-user install never writes
to `HKLM`. That test exists because the title had already drifted once, when the interface was
translated into Ukrainian and the installer was left looking for the old English one.

### NSIS installer design

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

191 tests, no waiting and no real browser: `pytest.ini` forces Qt's `offscreen` platform, the
browser call is stubbed, and the scheduler's clock is injected so a full teaching day is simulated
at 15-second resolution in milliseconds.

Qt permits one application object per process, so every Qt-dependent test shares the single
session-scoped `qapp` fixture in `tests/conftest.py`.

The parser tests run against the real schedule document. It is not committed (it holds live meeting
links); the fixture finds it on the Desktop or via `AUTOPARA_TEST_DOCX`, and skips if absent.
