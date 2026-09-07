# FRONTEND — screens, widgets, state, styling

> Read `ARCHITECTURE.md` and `BACKEND.md` first. Update this file whenever a screen, widget, or
> styling convention changes.

## Language

**Every string the user can see is Ukrainian.** Not a preference — a requirement of the product.
The importer accepts documents in other languages (`BACKEND.md` R10) and converts what it reads
into Ukrainian labels; the interface itself has no other language and no translation layer, because
one locale needs no machinery. `tests/test_ui.py::test_interface_is_ukrainian` walks the live widget
tree and fails on Latin words other than the product and provider names.

Subject and teacher text is the exception, and only because it is data: it is reproduced exactly as
the document wrote it.

## Screen map

| Screen | Module | Role |
|---|---|---|
| Main window | `ui/main_window.py` | Toolbar, catch-up banner, week grid, status line. |
| Week grid | `ui/week_grid.py` | The calendar surface: day columns x pair rows, plus the drop target. |
| Class card | `ui/class_card.py` | One lesson inside a grid cell; also the drag source. |
| Catch-up banner | `ui/catchup_banner.py` | The in-app "пара вже почалася" prompt. |
| Setup / import | `ui/setup_dialog.py` | Pick `.docx` -> pick course -> pick group. |
| Add / edit class | `ui/edit_dialog.py` | Create or modify a lesson; also used to add a missing link. |
| Settings | `ui/settings_dialog.py` | Lead time, class length, theme, notifications, catch-up policy, autostart. |
| Tray | `ui/tray.py` | Icon, context menu, notifications. |

## There is no edit mode

The grid is editable from the moment it opens. The old **Edit** toggle is gone: it guarded against
a stray click on a read-only calendar, but every interesting action — open, edit, mark, delete —
now lives behind a menu that the click itself raises, so nothing destructive happens without a
second, named choice. A mode that must be switched on before the app can be used is a mode nobody
wants.

## Week grid

- **Columns** = weekday names, with **no dates and no week switching**. The timetable repeats
  every week, so a date on the header answers a question nobody asked and immediately raises one
  that matters ("which week am I looking at?"). The grid is always the current week; `date_of()`
  turns a lesson into the date its marks belong to.
- Mon–Sat are shown because the source document never uses Sunday; Sunday is fully supported
  (`day_index = 6`) and its column appears automatically if a lesson lands there.
- **Rows** = hours, 08:00 through 23:00, so a class can be created at any point in the day. The
  evening rows are usually empty, which is the point: an empty row is where you click to create
  something.
- **A class is placed by its real time, not by a slot.** 09:30–10:50 covers the bottom half of the
  09:00 row and most of the 10:00 one. Slot-shaped placement was what made the times down the side
  look arbitrary — a 09:30 class sitting flush inside a cell labelled 09:00 says the label is a
  decoration.
- "Today" is tinted; the current hour is marked.
- A lesson spanning several hours (`BACKEND.md` R5) is one card, spanning them.

### One minute, one pixel

`HOUR_HEIGHT` is 60 and every row is pinned to it (`setRowMinimumHeight` plus a stretch row below
the last hour), so a card's offset inside its span is simply its start minute:
`WeekGrid.span_for()` returns `(first_row, row_span, top_px, bottom_px)` and the margins are the
minutes the class does not use at either end. No fractional layout, no sub-rows, no custom paint.

Two things this depends on, both easy to undo by accident:

- Rows must not stretch. Spare height goes to the trailing row instead.
- A card must not argue with the clock. Its container is `QSizePolicy.Ignored` vertically, or a
  long subject name inflates the hour it sits in and the whole column drifts out of true.

### Empty slots

Clicking an empty hour raises a small menu — `➕ Створити пару · Четвер, 13:00` — which opens the
edit dialog with that day and hour already filled in. Google Calendar's gesture, and the reason
the grid does not need an "add" mode: the empty space *is* the affordance. The toolbar's
**Додати пару** stays for keyboard-first users and for an empty schedule.

### Drag and drop

A card is a drag source (`ClassCard.mouseMoveEvent`, mime type `application/x-autopara-lesson`
carrying only the lesson id). Dropping it on an hour moves the class to that day and hour, keeping
its length: `MainWindow._lesson_dropped` -> `storage.move_lesson`.

The drop is handled by `GridCanvas`, not by the individual cells. A card that spans several pairs
sits *on top of* the cells it covers and would swallow the event; the canvas maps the drop point
onto a cell rectangle instead. The payload is an id rather than the lesson itself so a stale card
can never carry stale data across.

A press only counts as a click when the pointer never travelled far enough to start a drag —
otherwise every drag would also open the actions menu on release.

### Rebuilding the grid

`WeekGrid._clear()` **hides and deletes**; it must never `setParent(None)`. Detaching a live widget
makes it a top-level window for the moment between the rebuild and the event loop running
`deleteLater`, and rebuilding a whole week that way threw dozens of stray top-levels at the window
manager — small empty windows flashing across the screen on every reload, most visibly right after
clicking a class, because opening its link triggers one. For the same reason, an action that opens
a link does *not* reload: `Scheduler.lesson_opened` already does, and a second full rebuild landing
while the browser starts is exactly the churn to avoid.

## Class card

Shows, in order: provider badge, state badge, subject, teacher, time range, and a group chip for
shared sessions.

| State | Treatment |
|---|---|
| upcoming | normal card, subject-coloured left border |
| next up (soonest today) | accent outline |
| opened | `✓ відкрито`, muted |
| missed | `не відкрито`, warning stripe |
| skipped | `пропущено`, dashed and muted |
| no link | dashed border + `без посилання` |

### Clicking a card

One menu, built from what the lesson actually is:

- **With a link** — Відкрити посилання · Редагувати… · Позначити як відкриту · Позначити як
  пропущену · (Зняти позначку) · Видалити пару.
- **Without a link** — the first item becomes **Додати посилання…**, since opening is not on offer
  and adding the URL is the thing the user came to do.

"Зняти позначку" appears only when the class already has an occurrence for this week's date.
Marks are per `(lesson, date)`, so this week's verdict does not follow the class into the next.

## Catch-up banner

A strip between the toolbar and the grid, hidden unless a class is waiting for an answer. It names
the class and offers **Підключитися зараз** and **Закрити**; nothing opens until one is pressed,
and `app.py` brings the window forward when one arrives.

This replaces opening the meeting automatically. A class the user has already missed the start of
is not something to act on unasked: the tabs arrive after the fact, sometimes several at once, and
the user is left closing windows and leaving calls. `Закрити` marks the class missed, so it does
not ask again.

Several missed classes queue and are shown one at a time, with `ще N у черзі` on the current one.

## Edit dialog

Start and end times are **entered directly** (two `QTimeEdit`s) rather than picked as a pair
number, and the dialog echoes back the resulting length. The end time follows the start
automatically until the user moves it themselves. `pair` is still stored — it is part of a lesson's
`source_key` — but it no longer decides anything about where the class is drawn.

## Settings

Lead time · class length · theme · notifications (on/off and how many minutes ahead) · what to do
about a missed class (notify and open on confirmation / open immediately / mark missed) · autostart.

The catch-up section states plainly that a class already running when AutoPara starts is never
opened unquestioned, even in "open immediately" mode — otherwise that option reads as a promise the
app deliberately does not keep (`ARCHITECTURE.md`, "Catch-up never ambushes on a cold start").

## Import dialog

Picking a `.docx` preselects the **previously chosen course and group**, matched by course ordinal
and group name — read from storage before the import overwrites it. Re-importing an updated
timetable is then two clicks rather than a re-run of first-time setup.

The dialog reopens **AutoPara's own copy** of the last document rather than the path the user
originally picked: the original is usually a download that has since been tidied away. See
`BACKEND.md`, "The imported document is copied".

## Theme

Light and dark, toggled from the toolbar (`☀` / `🌙`). The stored setting is `system` | `light` |
`dark`, defaulting to `system`, which reads the Windows app theme — so a fresh install matches the
desktop it was installed on. The toggle pins the opposite of what is currently showing.

Styling lives in `ui/styles.qss`, a template whose colours are `$tokens` substituted by
`core/theme.py`. **Never hard-code a colour in the QSS**: a literal looks right in one theme and
wrong in the other. Subject colours have a second palette lifted for dark backgrounds
(`class_card.SUBJECT_COLORS_DARK`), chosen by the same hash so a subject keeps its identity in both.

## State management

There is no separate state container. The **SQLite database is the single source of truth**; the UI
reads through `core/storage.py` and re-renders on change. Widgets never cache lesson data across
operations — after any mutation the affected view reloads from storage. Cross-component updates use
Qt signals:

- `Scheduler.lesson_opened(lesson_id)` -> the card flips to `opened`, the banner drops that class.
- `Scheduler.lesson_missed(lesson_id)` -> grid reloads.
- `Scheduler.catchup_available(lesson_id)` -> banner + window surfaced.
- `Scheduler.reminder_due(lesson_id)` -> tray notification.

The window holds no view state at all: there is no week to remember, so `reload()` is a pure
function of the database and today's date.

### Indicators must be styled for every state

As soon as *any* stylesheet rule applies to a `QCheckBox` or `QRadioButton`, Qt stops drawing the
native indicator and paints only what the stylesheet asks for. Styling nothing but `spacing` left
the **checked** radio button with no indicator at all — the selected option looked like plain text
with a gap in front of it. `styles.qss` therefore defines `::indicator` for unchecked, checked,
hover and disabled, and the indicator box is the same size in every state so checking an option
cannot shift the row it sits in.

The radio's dot is a radial gradient. The checkbox's tick cannot be: QSS has no way to draw a
shape, and `image:` wants a file. So `theme.checkmark_icon()` paints a tick once per theme into a
small PNG beside the database and the stylesheet points `$check_icon` at it. Filling the box with
the accent colour was the alternative, and a solid coloured square does not read as "ticked".

## Styling conventions

- 8 px base spacing unit; 8 px card radius; one subtle shadow level for cards (darker in the dark
  theme).
- Subject colour: deterministic hash of the subject name into a fixed palette, so the same subject
  keeps its colour across sessions and re-imports.
- Font: Segoe UI (Windows default), 9–10 pt body, 600 weight for subjects.
- Never encode meaning in colour alone — every coloured state also carries an icon or text label.
