# AutoPara — Class Auto-Launcher

A Windows tray app that imports a university timetable from a `.docx`, shows the week as a
calendar grid, and opens each class's Zoom / Google Meet link in the default browser one minute
before it starts.

![week grid](docs/week-grid.png)

## Install and run

```
python -m pip install -r requirements.txt
python -m autopara
```

On first launch it asks for the `.docx`, then your course and group, then offers to start with
Windows.

## Build an installer

```
.\build.ps1
```

Produces:

| File | Size | What it is |
|---|---|---|
| `dist\AutoPara-1.0.0-Setup.exe` | ~35 MB | **The installer** - copy this to another PC. |
| `dist\AutoPara\AutoPara.exe` | ~118 MB folder | The unpacked app, if you'd rather not install. |

The installer is per-user: it installs to `%LOCALAPPDATA%\Programs\AutoPara`, needs **no admin
rights and shows no UAC prompt**, and adds Start Menu / desktop shortcuts, an Add/Remove Programs
entry, and an optional "start with Windows" component.

The target PC needs **nothing preinstalled** - no Python, no Qt, no VC++ redistributable; they are
all inside the bundle. Windows 10/11 64-bit.

Silent install and uninstall are supported (`/S`), and uninstalling keeps your imported timetable in
`%APPDATA%\AutoPara` unless you choose to delete it.

Building the installer yourself needs NSIS: `winget install NSIS.NSIS`.

## How it behaves

- **Opens each class once.** The lead time defaults to 1 minute and is configurable in Settings.
  Restarting the app, waking from sleep, or changing the clock cannot cause a second open — the
  guarantee is a database constraint, not in-memory state.
- **Catch-up.** If the PC was asleep and the moment was missed while the class is still running,
  a tray notification offers to open it. It never opens a browser window unprompted. Two other
  policies (open immediately / mark missed) are available in Settings.
- **Shared classes.** When one session is taught to several groups at once, it appears as a single
  card tagged with the groups, and its link opens once.
- **Classes with no link** are shown with a dashed border and never auto-open; click one to add a
  URL.
- **Editing.** The Edit toggle unlocks add / edit / delete. Manually added classes survive
  re-importing the document.

Closing the window hides it to the tray; use the tray menu to quit.

## Documentation

Read these before changing anything:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — stack, process model, data flow, scheduling, build.
- [docs/BACKEND.md](docs/BACKEND.md) — the `.docx` parsing rules, data model, scheduler.
- [docs/FRONTEND.md](docs/FRONTEND.md) — screens, widgets, styling.

## Tests

```
python -m pytest
```

Parser tests run against the real schedule document, which is not committed. Put it on the Desktop
or set `AUTOPARA_TEST_DOCX` to its path; the tests skip if it cannot be found.
