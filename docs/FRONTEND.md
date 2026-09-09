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
| Main window | `ui/main_window.py` | Icon rail, catch-up banner, week grid. |
| Week grid | `ui/week_grid.py` | The calendar surface: day columns x pair rows, plus the drop target. |
| Class card | `ui/class_card.py` | One lesson inside a grid cell; also the drag source. |
| Catch-up banner | `ui/catchup_banner.py` | The in-app "пара вже почалася" prompt. |
| Import landing | `ui/import_landing.py` | The first-run screen and its `.docx` drop well. |
| Setup / import | `ui/setup_dialog.py` | Pick `.docx` -> pick course -> pick group. |
| Add / edit class | `ui/edit_dialog.py` | Create or modify a lesson; also used to add a missing link. |
| Settings | `ui/settings_dialog.py` | Lead time, class length, theme, notifications, catch-up policy, autostart. |
| Tray | `ui/tray.py` | The app mark, context menu, notifications. |
| Glyphs | `ui/icons.py` | Every interface icon, painted with `QPainter` rather than shipped. |

## Sidebar

The window's chrome is a **72 px rail down the left**, not a strip across the top. The week grid is
wide and short: a top bar spent the height the calendar is always short of and left the width it
does not need, and it cost a day column outright once the window was anything but maximised.

Top to bottom: the app mark, a stretch, the circular add button, then a tight cluster of three icon
buttons. **Nothing on it is written.** Its width is the width of one button plus air, which is what
it can be once no label has to fit — `test_the_sidebar_carries_no_words_at_all` walks the rail and
fails on any label or button that has text.

**The mark replaces the word "AutoPara".** An app does not need to say its own name inside its own
window; the tray, the taskbar and the title bar all carry it already. `ui/tray.icon_pixmap()` draws
it at whatever size is asked for, so the 30 px rail badge and the 16 px tray glyph are one drawing.

**The course and group are the mark's tooltip.** They were four lines printed down the rail, and
they do not change from one week to the next — permanent cost, occasional value. `_set_subtitle`
now writes them into `brand.setToolTip`, where they appear when someone actually asks.

**Every button is an icon.** That is what this design language uses for the actions of a window, and
it happens to serve the Ukrainian rule too: a word that is not on screen cannot be in the wrong
language. Each one's meaning lives in a tooltip, which is where an icon button's meaning is
*supposed* to live — `TestIconOnlyToolbar` fails if any of the four loses its tooltip or gains a
label.

`Додати пару` is a 40 px accent **circle**, not a pill: a pill with nothing written on it is only a
circle that has been stretched. It is still the one prominent control on the screen, and the only
filled one.

The import glyph is `square.and.arrow.up` — the arrow points **up**. Pointing it down made the
button read as "download", which is what a schedule arriving from a website looks like from the
outside; the button does the opposite, handing a file the user already has to AutoPara.

The icon buttons are 36x36 rather than the 44pt the HIG asks for: 44pt is a touch-target rule, and
this is a mouse-driven desktop window where a 44px button reads as oversized chrome.

Glyphs come from `ui/icons.py`, which paints them with `QPainter` in whatever colour it is handed.
Same reasoning as `tray.icon_pixmap` and `theme.checkmark_icon`: the repository has no asset
pipeline, and adding a `.qrc`, an image directory and two build-script entries for seven small
shapes costs more than it saves. Because the colour is a parameter, `MainWindow._refresh_icons`
repaints every glyph after a theme change — a shipped PNG would need two of each.

## There is no status bar

The strip along the bottom counted today's classes and named the next one. It is gone with the top
bar: the grid already shows today tinted, the next class outlined, and every class's state on its
own card, so the line restated in words what the calendar was saying in place — and it did so in the
one row of height a short grid could least afford.

## There is no edit mode

The grid is editable from the moment it opens. The old **Edit** toggle is gone: it guarded against
a stray click on a read-only calendar, but every interesting action — open, edit, mark, delete —
now lives behind the right-click menu, so nothing destructive happens without a second, named
choice, while the one harmless action — joining the class — stays on the left button. A mode that must be switched on before the app can be used is a mode nobody
wants.

## Week grid

- **Columns** = weekday names, with **no dates and no week switching**. The timetable repeats
  every week, so a date on the header answers a question nobody asked and immediately raises one
  that matters ("which week am I looking at?"). The grid is always the current week; `date_of()`
  turns a lesson into the date its marks belong to.
- Mon–Sat are shown because the source document never uses Sunday; Sunday is fully supported
  (`day_index = 6`) and its column appears automatically if a lesson lands there.
- **Rows** = hours, 08:00 through 18:00. The teaching day ends well before that — the latest
  class in the source document finishes at 17:30 — and every hour past it was a band of empty grid
  the week had to scroll through to reach nothing. One spare row is an affordance; five are a
  waste of the screen. A class outside the window is not lost: `span_for` clamps it to the last
  row, and the edit dialog accepts any time at all.
- **A class is placed by its real time, not by a slot.** 09:30–10:50 covers the bottom half of the
  09:00 row and most of the 10:00 one. Slot-shaped placement was what made the times down the side
  look arbitrary — a 09:30 class sitting flush inside a cell labelled 09:00 says the label is a
  decoration.
- "Today" is tinted; the current hour is marked.
- A lesson spanning several hours (`BACKEND.md` R5, R12) is one card, spanning them. A double class
  is one card for the same reason it is one browser tab: it never stopped.

### One minute, a fixed number of pixels

Every row is exactly `HOUR_HEIGHT` px, so a card's offset inside its span is just its start
minute, scaled: `WeekGrid.span_for()` returns `(first_row, row_span, top_min, bottom_min)` where
the margins are the **minutes** the class does not use at either end, and `minutes_to_pixels()`
converts them at the single place that draws. Keeping `span_for` in minutes is what lets it stay a
pure function of the timetable, testable without a window. No fractional layout, no sub-rows, no
custom paint.

`HOUR_HEIGHT` is **66**, not the tidier 60 that would make a minute a pixel. At 60 the standard
80-minute pair got 80 px and needed 87 to show its subject, teacher and time, so every card in the
week clipped a line. Eleven rows at 66 still fit the default window without scrolling, which is
what shortening the day to 18:00 bought.

Three things this depends on, all easy to undo by accident:

- Rows must not stretch. Spare height goes to the trailing row instead.
- **A card's container must be a fixed height** — `span * HOUR_HEIGHT`. An `Ignored` vertical size
  policy is not enough on its own, and believing it was cost this grid its honesty for a long
  time: `QGridLayout` still honours a *spanning* item's `minimumSizeHint`, so a card whose text
  wanted more room than its class lasted pushed the rows it covered apart. Hours quietly became
  74, 82, even 106 px tall, every card below them sat at the wrong time, and the labels down the
  side described a scale the grid was no longer using.
- Text that does not fit is **clipped**, exactly as in any calendar. The card's tooltip carries the
  whole subject, the full teacher name, the time and the groups, so nothing is only half-knowable.

### Empty slots

Clicking an empty hour raises a small menu — `➕ Створити пару · Четвер, 13:00` — which opens the
edit dialog with that day and hour already filled in. Google Calendar's gesture, and the reason
the grid does not need an "add" mode: the empty space *is* the affordance. The rail's
**add** button stays for keyboard-first users and for an empty schedule.

### Drag and drop

A card is a drag source (`ClassCard.mouseMoveEvent`, mime type `application/x-autopara-lesson`
carrying only the lesson id). Dropping it on an hour moves the class to that day and hour, keeping
its length: `MainWindow._lesson_dropped` -> `storage.move_lesson`.

The drop is handled by `GridCanvas`, not by the individual cells. A card that spans several pairs
sits *on top of* the cells it covers and would swallow the event; the canvas maps the drop point
onto a cell rectangle instead. The payload is an id rather than the lesson itself so a stale card
can never carry stale data across.

A press only counts as a click when the pointer never travelled far enough to start a drag —
otherwise every drag would also join the class on release. The menu is raised from
`contextMenuEvent` rather than from a right-button release, so the keyboard's Menu key works too
and the event never falls through to the grid underneath.

### Rebuilding the grid

`WeekGrid._clear()` **hides and deletes**; it must never `setParent(None)`. Detaching a live widget
makes it a top-level window for the moment between the rebuild and the event loop running
`deleteLater`, and rebuilding a whole week that way threw dozens of stray top-levels at the window
manager — small empty windows flashing across the screen on every reload, most visibly right after
left-clicking a class, because opening its link triggers one. For the same reason, an action that opens
a link does *not* reload: `Scheduler.lesson_opened` already does, and a second full rebuild landing
while the browser starts is exactly the churn to avoid.

## Class card

A badge row — provider, state, and a group chip for a shared session — then the subject, the
teacher, and the time range.

### The card is told how tall it will be

`WeekGrid` passes `height=` to `ClassCard`, because a card is exactly as tall as its class is long
and a long subject simply will not fit. Knowing the height, the card picks the richest of its
`LAYOUTS` that does: two lines of subject, then the teacher, and last the time — which the card's
own position on the grid already says and the tooltip repeats. Each label is then capped to a whole
number of lines, so a card that runs out of room loses a line rather than being cut through the
middle of one, which reads as a rendering fault rather than a calendar.

The group chip rides on the badge row rather than beside the time for exactly this reason: a card
too short for a time row must still be able to say that the class is shared.

Nothing is only half-knowable — the tooltip carries the whole subject, the full teacher name, the
exact times, every group and the link.

| State | Treatment |
|---|---|
| upcoming | normal card, subject-coloured left border |
| next up (soonest today) | accent outline |
| opened | `✓ відкрито`, muted |
| missed | `не відкрито`, warning stripe |
| skipped | `пропущено`, dashed and muted |
| no link | dashed border + `без посилання` |

### Clicking a card

**Left click joins the class** — it opens the link straight away, with no menu in between. That is
the one thing the app exists to do, so it costs one click. If the lesson has no link there is
nothing to open, and the click raises the menu below instead, whose first item is exactly the
remedy.

**Right click opens the actions menu**, built from what the lesson actually is:

- **With a link** — Відкрити посилання · Редагувати… · Позначити як відкриту · Позначити як
  пропущену · (Зняти позначку) · Видалити пару.
- **Without a link** — the first item becomes **Додати посилання…**, since opening is not on offer
  and adding the URL is the thing the user came to do.

"Зняти позначку" appears only when the class already has an occurrence for this week's date.
Marks are per `(lesson, date)`, so this week's verdict does not follow the class into the next.

## Catch-up banner

A strip above the grid, hidden unless a class is waiting for an answer. It names
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

## Import landing

The screen a fresh install opens on. It replaced a centred grey `QLabel` and, above it, a modal
import dialog that `app.py` fired on the first tick — so the first thing the app ever showed was a
form, over a window the user had not seen yet. Now `app.py` opens nothing; the landing *is* the
first-run experience and its own button opens the dialog.

A hero plate with the app glyph, a title, one line of explanation, a **drop well**, and
`Обрати файл…`.

### Dropping a file

`DropWell` accepts the drop, not the window, because the same widget is reused inside the import
dialog — the gesture has to work identically in both places. `ImportLanding` and `SetupDialog` both
`setAcceptDrops(True)` and forward their drag events to their well, so the target is the whole
screen while the highlight stays on the thing that explains what will happen.

- Only `.docx` is accepted, and the check happens in `dragEnterEvent`: refusing the drag there is
  what makes the cursor say "no" *before* the user lets go.
- Several files at once take the first `.docx` among them. A drop is a gesture, not a form
  submission; answering it with an error dialog would be answering the wrong question.
- The well shows the chosen file's **name**, never its path. The path is not what anyone checks.

`empty_label` still exists as a `MainWindow` attribute — it is the landing's explanation line,
re-exported — so the rest of the window, and the tests that predate this screen, never learn that
it moved.

## Import dialog

The file step is the same `DropWell` as the landing screen, so a `.docx` can be dropped straight
onto the dialog. The old read-only path field survives, hidden, because the import still needs the
source path — but it is no longer something the user is asked to read.

Picking a `.docx` preselects the **previously chosen course and group**, matched by course ordinal
and group name — read from storage before the import overwrites it. Re-importing an updated
timetable is then two clicks rather than a re-run of first-time setup.

The dialog reopens **AutoPara's own copy** of the last document rather than the path the user
originally picked: the original is usually a download that has since been tidied away. See
`BACKEND.md`, "The imported document is copied".

## Theme

Light and dark, toggled from the rail. The stored setting is `system` | `light` | `dark`,
defaulting to `system`, which reads the Windows app theme — so a fresh install matches the desktop
it was installed on. The toggle pins the opposite of what is currently showing.

Styling lives in `ui/styles.qss`, a template whose colours are `$tokens` substituted by
`core/theme.py`. **Never hard-code a colour in the QSS**: a literal looks right in one theme and
wrong in the other. Subject colours have a second palette lifted for dark backgrounds
(`class_card.SUBJECT_COLORS_DARK`), chosen by the same hash so a subject keeps its identity in both.

Each theme is **given four colours** and derives the rest of its ~45 tokens from them:

| | Light | Dark | |
|---|---|---|---|
| `bg` | `#ffffff` | `#0f1319` | the window |
| `card_bg` | `#f5f9fa` | `#131920` | the shape a class sits on — and the rail, and every recessed group |
| `accent` | `#6067e5` | `#6067e5` | the one tint, the same in both themes |
| `text` | `#434958` | `#b3bdd3` | text and icons |

Everything else — the muted and faint inks, the three weights of hairline, the tinted state fills —
is a step off one of those four, and every pair that carries text is checked against WCAG AA.
Values are opaque hex rather than translucent: Qt's stylesheet parser is inconsistent about alpha,
and one translucent grey would composite differently on a card, on a tinted grid cell and on the
rail.

The accent is split into three tokens, because one colour cannot do all three of its jobs at AA:

| Token | Job | Why not just `accent` |
|---|---|---|
| `accent` | Borders, indicators, focus rings, the dashed drop outline | UI components need 3:1, which `#6067e5` clears in both themes |
| `accent_fill` | The prominent button's fill | White on `#6067e5` is 4.6:1 — enough, and the token exists so a future accent cannot quietly stop being |
| `accent_ink` | The accent used **as text** | `#6067e5` on the dark background is 4.05:1, under AA, so the dark theme reads with a lighter `#8f95f0` |

The dark window colour is `#0f1319`, not black: a desktop-sized window in pure black reads as a
hole punched in the screen.

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

- 8 px spacing unit, 4 px for tight gaps. Radii are **concentric**: a control nested inside a
  container gets a smaller radius than the container, or the two curves fight. Cards and wells 12–14
  px, controls and menu items 7–8 px, standalone action buttons fully rounded (a 34 px pill with a
  17 px radius).
- Three button tiers, and only ever one prominent button on a screen: `#Primary` (accent pill),
  the default `QPushButton` (soft `sunken` fill, no outline), and `#Plain` (accent text, no fill).
  Footers put the plain action left of the prominent one — Qt's `QDialogButtonBox` puts it the other
  way round on Windows, which is why the dialogs lay their footers out by hand.
- Subject colour: deterministic hash of the subject name into a fixed palette, so the same subject
  keeps its colour across sessions and re-imports. Neither blue nor indigo is in that palette — a
  subject wearing the interface's own blue-violet reads as selected rather than as itself.
- Font: **Google Sans**, bundled in `ui/fonts` (Regular / Medium / SemiBold / Bold) under the SIL
  Open Font License — Google publishes it on Google Fonts, so it redistributes like any other open
  font. It covers Cyrillic, which the interface needs, and it has a real SemiBold, so `font-weight:
  600` resolves to 600 rather than jumping to Bold. 10 pt body, 9 pt secondary, 600 for anything
  that leads. The Segoe entries after it in `FONT_STACK` exist only for the case where the bundled
  files fail to load.
- One subtle shadow level for cards, applied with `QGraphicsDropShadowEffect` because QSS has no
  `box-shadow`. Wide and faint, not tight and dark: a card should look lifted, not outlined twice.
- Never encode meaning in colour alone — every coloured state also carries an icon or text label.

### Three things QSS will not do, and where they went instead

`box-shadow` -> `QGraphicsDropShadowEffect` (`class_card.py`). `letter-spacing` -> nowhere; the
hierarchy is carried by size and weight. `transition` -> nowhere; state changes are instant.
There is no backdrop blur either, so the sidebar is opaque rather than a poor imitation of glass.

### The font family is chosen in Python, not in the QSS

Qt honours only the **first** family named in a stylesheet `font-family`, so the usual CSS fallback
list is a trap: with the family missing, `"Google Sans", "Segoe UI", sans-serif` does not fall
through to Segoe UI — it falls through to a default with no glyphs, and the entire interface renders
as empty boxes. `theme.interface_font()` therefore walks `FONT_STACK` for a family Qt actually has
and substitutes the single winner as `$font_family`. `app._load_fonts()` registers the bundled faces
before the stylesheet is applied, and only logs if it cannot.

### A styled QWidget background reaches every label

`QWidget { background: $bg; }` gives *labels* an opaque background too, so each one paints a
rectangle of the window colour over whatever it sits on. Invisible while the two colours happen to
agree — which is why it survived so long in the light theme — and a grey block across every card in
the dark one. `QLabel { background: transparent; }` puts it back; badges and chips override it with
their own ID rules.

### Sub-controls need their arrows supplied

The same rule as the checkbox indicator: style any part of a sub-control and Qt stops drawing the
native one. Styling `QComboBox::drop-down` left the combo boxes as empty rounded fields with nothing
to say they open, and the spin boxes with no arrows at all. `theme.chevron_icon()` paints an up and
a down chevron per theme beside the database, exactly as `checkmark_icon` does, and the stylesheet
points `$chevron_up` / `$chevron_down` at them.
