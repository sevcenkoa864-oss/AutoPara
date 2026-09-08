# AutoPara — автозапуск пар

A Windows tray app that imports a university timetable from a `.docx`, shows the week as a calendar
grid, and opens each class's Zoom / Google Meet link in the default browser a minute before it
starts. **The application's interface is Ukrainian**; this README and the design docs are English,
for whoever maintains it.

![week grid](docs/week-grid.png)

## Install

Download **`AutoPara-Setup.exe`** from the latest release and run it. That is the whole procedure.

The target PC needs **nothing preinstalled** — no Python, no Qt, no VC++ redistributable; they are
all inside the installer. Windows 10/11 64-bit.

It installs per-user to `%LOCALAPPDATA%\Programs\AutoPara`, so there are **no admin rights and no
UAC prompt**. You get Start Menu and (optionally) desktop shortcuts, an entry in Add or Remove
Programs, and an optional "start with Windows" component that launches it hidden in the tray.

Silent install and uninstall are supported with `/S`. Uninstalling keeps your imported timetable in
`%APPDATA%\AutoPara` unless you choose to delete it, so reinstalling does not lose the schedule.

### Building the installer

```
python -m pip install pyinstaller     # once
winget install NSIS.NSIS              # once
.\build.ps1
```

That produces `dist\AutoPara\AutoPara.exe` (the unpacked app, ~118 MB) and
`dist\AutoPara-1.2.0-Setup.exe` (the installer, ~33 MB). `.\build.ps1 -SkipApp` rebuilds only the
installer.

## Run from source

```
python -m pip install -r requirements.txt
python -m autopara
```

On first launch it opens on the import screen: **drag the `.docx` onto it** (or press
`Обрати файл…`), then pick your course and group.

`python -m autopara` also **refreshes the installed copy** from the source it is running out of, so
checking a change is one command rather than a reinstall. Add `--no-rebuild` to skip that.

## Build the standalone (Python-free) bundle

```
.\build.ps1
```

| File | Size | What it is |
|---|---|---|
| `dist\AutoPara-1.1.0-Setup.exe` | ~35 MB | NSIS installer — hand this to someone who does not have the repository. |
| `dist\AutoPara\AutoPara.exe` | ~118 MB folder | The unpacked app, if you'd rather not install. |

That bundle needs **nothing preinstalled** — no Python, no Qt, no VC++ redistributable. Windows
10/11 64-bit. Silent install and uninstall are supported (`/S`), and uninstalling keeps your
imported timetable in `%APPDATA%\AutoPara` unless you choose to delete it. Building it needs NSIS:
`winget install NSIS.NSIS`.

## How it behaves

- **Opens each class once.** The lead time defaults to 1 minute and is configurable. Restarting the
  app, waking from sleep, or changing the clock cannot cause a second open — the guarantee is a
  database constraint, not in-memory state.
- **A missed class is never opened behind your back.** If a class was already running when AutoPara
  started, the window comes forward with a banner naming it and two buttons — *Підключитися зараз*
  and *Закрити*. Nothing opens until you pick one. This holds even when the catch-up setting says
  "open immediately": that setting applies to a class that starts while the app is running.
- **Reminders.** An optional tray notification a configurable number of minutes before each class.
- **Any-language documents.** Day names are recognised in Ukrainian, Russian, English, Polish,
  German and several other languages; the schedule the app builds from them is always Ukrainian.
- **Editable straight away** — no edit mode. Click a class for its actions (open, edit, mark as
  opened or skipped, delete), click an empty slot to create one there, drag a class to move it.
  A class with no link offers to add one instead of opening.
- **A real calendar day**, 08:00 to 18:00 in hourly rows, with each class drawn across the time it
  actually occupies rather than dropped into a slot. Columns are weekdays; the timetable repeats
  every week, so there are no dates and nothing to navigate.
- **Light and dark themes**, following the Windows app theme until you pin one.
- **Shared classes.** One session taught to several groups is a single card tagged with the groups,
  and its link opens once.
- **Re-importing** a new document keeps the course and group you had selected and your manually
  added classes, and clears the old week's records — a new timetable starts on a clean grid. It
  also only applies from the moment you import it, so setting one up at the weekend does not mark
  that weekend as missed.
- **Your timetable is copied into the app**, so deleting the original `.docx` costs you nothing.
  Reinstalling keeps that copy; uninstalling removes it along with everything else.

Closing the window hides it to the tray; use the tray menu to quit.

## Author

Authorised by MaBoRo (Vladyslav Tishyn) — vlad.tishyn@gmail.com

## Third-party

The interface is set in **Google Sans**, bundled in `autopara/ui/fonts` under the SIL Open Font
License 1.1 — the licence ships beside the font files as `OFL.txt`. Nothing else is bundled: every
icon in the app, the app mark included, is drawn in code.

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
or set `AUTOPARA_TEST_DOCX` to its path; the tests skip if it cannot be found — so check the count,
not just the colour.
