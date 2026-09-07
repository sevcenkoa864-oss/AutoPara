# FRONTEND — screens, widgets, state, styling

> Read `ARCHITECTURE.md` and `BACKEND.md` first. Update this file whenever a screen, widget, or
> styling convention changes.

## Screen map

| Screen | Module | Role |
|---|---|---|
| Main window | `ui/main_window.py` | Hosts the week grid, the toolbar (Edit toggle, Import, Settings), and the status line. |
| Week grid | `ui/week_grid.py` | The calendar surface: day columns x pair rows. |
| Class card | `ui/class_card.py` | One lesson inside a grid cell. |
| Setup / import | `ui/setup_dialog.py` | Pick `.docx` -> pick course -> pick group. Shown on first run and from "Import". |
| Add / edit class | `ui/edit_dialog.py` | Create or modify a lesson; also used to add a missing link. |
| Settings | `ui/settings_dialog.py` | Lead time, class duration, catch-up mode, autostart toggle. |
| Tray | `ui/tray.py` | Icon, context menu (Show / Settings / Quit), catch-up notifications. |

## Week grid

- **Columns** = days. Mon–Sat are shown because the source document never uses Sunday; Sunday is
  fully supported in the data model (`day_index = 6`) and its column appears automatically if any
  lesson lands on it.
- **Rows** = pairs 1–6, labelled with the pair number and its time range (`1 · 8:00–9:20`).
- A lesson spanning several pairs (rule R5) renders as one card spanning those rows.
- Empty cells are visually quiet — no borders competing with real content, just the grid ruling.
- "Today" column is subtly tinted; the current pair row is marked.

## Class card

Shows, in order: provider badge, subject, teacher, time range, and state.

States and their visual treatment:

| State | Treatment |
|---|---|
| upcoming | normal card, subject-colored left border |
| next up (soonest today) | accent outline |
| opened | check mark, muted/faded |
| missed | warning stripe |
| no link | dashed border + "no link" badge; clicking offers to add one |

Clicking a card opens it manually (recorded as `manual`, which also suppresses the automatic open
for that occurrence). In **Edit mode** a click instead reveals Edit / Delete actions.

The provider badge distinguishes `zoom` / `google_meet` / `unknown`, matching the `provider` column
described in `BACKEND.md`.

## Edit mode

Read-only by default so the grid cannot be disturbed by a stray click. The toolbar's **Edit** toggle
unlocks: add a class (via an empty cell or the "+" button), edit a class, delete a class. Changes
persist immediately through `core/storage.py`. Manually created lessons are flagged `is_manual` and
survive re-import.

## State management

There is no separate state container. The **SQLite database is the single source of truth**; the UI
reads through `core/storage.py` and re-renders on change. Widgets never cache lesson data across
operations — after any mutation the affected view reloads from storage. Cross-component updates use
Qt signals:

- `Storage.changed` -> grid reloads.
- `Scheduler.lesson_opened(lesson_id)` -> the card flips to the `opened` state.
- `Scheduler.catchup_available(lesson_id)` -> tray notification.

## Styling conventions

`ui/styles.qss`, loaded once in `app.py`. Light, modern, calendar-like — inspired by Google Calendar
without cloning it.

- Background `#ffffff`, grid ruling `#e8eaed`, primary text `#202124`, secondary `#5f6368`,
  accent `#1a73e8`.
- 8 px base spacing unit; 8 px card radius; one subtle shadow level for cards.
- Subject color: deterministic hash of the subject name into a fixed pastel palette, so the same
  subject keeps its color across sessions and re-imports.
- Font: Segoe UI (Windows default), 9–10 pt body, 600 weight for subjects.
- Never encode meaning in color alone — every colored state also carries an icon or text label.
