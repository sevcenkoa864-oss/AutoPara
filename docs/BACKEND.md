# BACKEND — data model, import pipeline, scheduler, storage

> Read `ARCHITECTURE.md` first. Update this file whenever the data model, the parsing rules, or the
> scheduler behavior changes.

## 1. The source document

The reference file is `Робочий_розклад (2).docx` (a real university schedule, Ukrainian).
Its structure, **verified by parsing the actual file** rather than assumed:

- Body order repeats 6 times: heading paragraph (`І КУРС` … `VІ КУРС`), a small `он-лайн`
  paragraph, then one `<w:tbl>`. Tables are matched to courses by document order.
- Row 0 of each table: `День | Пара | Час | <group> | <group> | …`
- Row 1: `День | Пара | Час | <specialty> | <specialty> | …`
- Rows 2+: one lesson slot each.

### Verified facts (regression fixtures)

| Metric | Value |
|---|---|
| Courses / tables | 6 |
| Total lesson events | **77** |
| Events with a link | 60 (revision-dependent, **not** asserted) |
| Events without a link | 17 (revision-dependent, **not** asserted) |
| Per course (I..VI) | 25, 11, 12, 13, **0**, 16 |
| Distinct hyperlink relationships | 60 elements, 20 unique URLs |
| Providers | 49 Zoom, 11 Google Meet |

> **Link counts are not regression fixtures.** The university fills missing links in over time --
> between two revisions of this document the linked total moved 60 -> 63 while the structure was
> byte-identical. Hard-coding the count produces a test that fails on a *document* change rather
> than a *code* change, so the link tests compare against the document itself instead:
>
> * `test_link_count_matches_the_document` -- linked lessons == the number of `<w:hyperlink>`
>   elements. Catches a link dropped from one lesson (which a URL-set comparison cannot see,
>   because ~20 URLs are shared across ~60 lessons).
> * `test_parser_finds_exactly_the_links_the_document_contains` -- the set of parsed URLs equals
>   the set of relationship targets. Catches mangled or invented URLs.
>
> Both oracles read the `.docx` zip directly and share no code with the importer. The structural
> numbers above (77 lessons, per-course counts) *are* asserted: they describe merge handling and
> hold across every revision seen so far.

Course V (`51 група`) legitimately has **no classes at all** — an empty schedule is a valid state,
not an import failure.

## 2. Parsing rules

These rules exist because the document's real XML differs from what a naive reading suggests. Each
was confirmed against the file; do not "simplify" them away.

**R1 — Logical columns, not cell indices.**
`<w:tc>` count varies per row (4 vs 5 vs 7) because merged cells are a *single* `tc` carrying
`<w:gridSpan w:val="N"/>`. The column identity of a cell is the **running sum of gridSpan** of the
cells before it, never its index in the row.

**R2 — Group ownership is a column *range*.**
Header cells themselves can span: in Table 4 (`ІV КУРС`) the grid has 7 columns but only 2 groups,
because `42 група` has `gridSpan=3`. Each group therefore owns `(col_lo, col_hi)`. A lesson cell
occupying `[c, c+span-1]` belongs to **every group whose range overlaps it**. An overlap with more
than one group means one shared class session with multiple groups — a single event, a single
calendar card, and a single browser open.

The original spec proposed detecting shared classes by finding identical text repeated in adjacent
columns. That is the wrong primary strategy for this document: Word stores the shared class as one
merged cell, so there is no repeated text to find. Duplicate-text detection remains only as a
defensive fallback (`_dedupe_adjacent_duplicates`) for documents produced by other tooling.

**R3 — Links live in two places.**
A URL appears both as a `<w:hyperlink r:id="rIdN">` (resolved through
`word/_rels/document.xml.rels`) **and** as visible run text. Collect both, then dedupe
order-preservingly, or every link is captured twice.

**R4 — The day column is mostly empty.**
`День` uses `<w:vMerge w:val="restart"/>` on the first row of a day and `<w:vMerge/>` (continue) on
the rest, with **no text** in the continuation cells. The parser carries the last seen day forward.

**R5 — Lesson cells use vertical merges too.**
25 cells carry `vMerge`. A `restart` cell **with content** is one lesson block spanning the
following `continue` rows (e.g. `Дисципліни вільного вибору` covers 4–6 consecutive pairs); its end
time extends to the end of the last continued row. A `restart` cell with **no** content is just
merged empty space and is ignored.

**R6 — Pair inference.**
`Пара` is blank on one row. The `Час` -> `Пара` mapping is perfectly consistent and is the source of
truth when the pair is missing:

`8.00 -> 1, 9.30 -> 2, 11.20 -> 3, 13.00 -> 4, 14.40 -> 5, 16.10 -> 6`

Default class duration is **80 minutes** (derived from the grid: 8.00–9.20, 9.30–10.50, …),
configurable via settings.

`TIME_TO_PAIR` also carries slots **7–10** (17.40, 19.10, 20.40, 22.10), continuing the same
80 + 10 minute rhythm. The document never uses them; `ACADEMIC_PAIRS = 6` is the count a *parsed*
lesson is expected to fall inside, and the regression fixtures still assert `1 <= pair <= 6`.

Since the grid became time-proportional (`FRONTEND.md`, "One minute, one pixel") `pair` no longer
decides where anything is drawn. It survives because it is part of `source_key`, which is what
lets a re-imported class keep its row id: two evening classes on the same day need different pair
numbers or they collide.

**R7 — Classes without links.**
17 cells have a subject and teacher but no URL (e.g. `(див. розклад на сайті ХНПУ)`). They are
stored with `needs_link = 1`, are never auto-opened, and render with a "no link" badge. The user can
supply a URL later through Edit mode.

**R8 — Unicode normalization.**
`П`ятниця` in this document uses a **backtick (U+0060)**, not an apostrophe. Course headings mix
Cyrillic `І` (U+0406) with Latin `V`. The filename on disk is **NFD**-normalized
(`и` + combining breve U+0306). Therefore: normalize to NFC and fold `` ` ``, `’`, `ʼ` -> `'` before
matching day names; match courses by **ordinal position**, never by literal heading string.

**R9 — Cell text layout.** Within a lesson cell, lines (split on `<w:br/>` and paragraph
boundaries) are: subject, then `(Teacher Name)` in parentheses, then the URL. The teacher is the
first parenthesized line; the subject is the first non-empty line; anything URL-shaped is stripped
from the display text.

**R10 — Any language in, Ukrainian out.**
The document is not required to be Ukrainian. `normalize._DAY_ALIASES` recognises day names in
Ukrainian, Russian, English, Polish, German, Spanish, French, Italian and Romanian, plus the usual
abbreviations, matched longest-first after NFC + apostrophe folding so a cell like
`Понеділок 02.09` still resolves. Ambiguous two-letter abbreviations shared across languages
(German `so` = Sonntag vs Polish `sob` = sobota) are deliberately absent rather than guessed at.

Everything the parser *emits* is Ukrainian regardless of the input: `DAY_NAMES` is the Ukrainian
list, and a course is always stored as `course_label(ordinal)` — `I курс`, `II курс`, … The
heading text is not used for the name at all, which also disposes of the Cyrillic/Latin numeral
mixing in R8. `is_course_heading` survives only to answer "does this document look like a
timetable"; courses are still matched to tables by document order.

Subject and teacher text is copied verbatim. Translating it would be inventing content: the class
name in the document is the class name.

**R11 — The `Час` cell may carry a range.**
The reference document writes a bare start (`8.00`); timetables from other tooling write
`8.00-9.20`. `parse_time_range` returns both, and an explicit end time beats the assumed class
duration. A start time outside the six standard slots no longer drops the row: `pair_slot` puts it
in the grid row that had already begun (the grid has six rows; a lesson is not obliged to fit one).

## 3. Data model (SQLite, `%APPDATA%\AutoPara\autopara.db`)

```sql
settings(key TEXT PRIMARY KEY, value TEXT)

courses(id INTEGER PK, ordinal INTEGER UNIQUE, name TEXT)

groups(id INTEGER PK, course_id -> courses.id, name TEXT,
       specialty TEXT, col_lo INTEGER, col_hi INTEGER)

lessons(id INTEGER PK, course_id -> courses.id,
        day_index INTEGER,        -- 0=Mon … 6=Sun
        pair INTEGER,             -- 1..6
        start_time TEXT,          -- 'HH:MM'
        end_time TEXT,            -- 'HH:MM'
        subject TEXT, teacher TEXT,
        url TEXT, provider TEXT,  -- zoom | google_meet | unknown
        needs_link INTEGER, is_manual INTEGER,
        source_key TEXT)          -- stable identity for re-import matching

lesson_groups(lesson_id -> lessons.id, group_id -> groups.id)   -- shared classes

occurrences(id INTEGER PK, lesson_id -> lessons.id,
            occur_date TEXT,      -- 'YYYY-MM-DD'
            status TEXT,          -- opened | missed | manual | skipped
            fired_at TEXT,
            UNIQUE(lesson_id, occur_date))
```

`settings` keys:

| Key | Default | Meaning |
|---|---|---|
| `selected_course_id`, `selected_group_id` | — | The chosen timetable. Also what the import dialog reads back to preselect the same course and group when a new document is imported. |
| `lead_minutes` | `1` | How early a class opens. |
| `class_duration_minutes` | `80` | Assumed length when the document gives no end time (R11). |
| `autostart_enabled` | `1` | See ARCHITECTURE.md "Autostart is on out of the box". |
| `catchup_mode` | `notify` | `notify` \| `open` \| `missed` — what to do about a class whose start has passed. |
| `notifications_enabled` | `1` | Tray reminders and open/catch-up notices. |
| `notify_minutes` | `10` | How long before a class the reminder appears. |
| `theme` | `system` | `system` \| `light` \| `dark`. `system` reads the Windows app theme, so a fresh install matches the desktop. |
| `schedule_active_from` | `""` | ISO datetime stamped on every import. See "The schedule starts when it is imported". |
| `schedule_copy_path` | `""` | AutoPara's own copy of the imported `.docx`. See "The imported document is copied". |
| `last_import_path` | `""` | Where the document came from. Kept for reference; the copy is what the dialog reopens. |

### Re-import behavior

Re-importing replaces imported lessons for the affected course but **preserves**:
- lessons the user created manually (`is_manual = 1`),
- user settings.

It **discards the `occurrences` log entirely** (`clear_occurrences`). A new document is a new
week: carrying yesterday's verdicts onto today's classes would show a freshly imported grid
already marked opened and missed, against lessons that may not even be the same ones.

### The imported document is copied

`archive_schedule` copies the `.docx` into `%APPDATA%\AutoPara\schedules\` and records
`schedule_copy_path`. The file the user picks is usually a download or an email attachment that
gets tidied away, and losing it should not cost them the ability to re-import; the import dialog
reopens the copy in preference to the original path.

Exactly one copy is kept — a new import replaces the old document as completely as it replaces the
old records. Because the copy lives with the database, uninstalling clears it along with
everything else, while a reinstall deliberately spares it (see `ARCHITECTURE.md`, "Reinstalling
replaces").

`source_key` (course ordinal + day + pair + subject) lets a re-imported lesson keep its identity, and
therefore its occurrence history, when the document is updated.

## 4. Scheduler

`core/scheduler.py` runs a `QTimer` every **15 s**. Polling rather than one-shot timers means
suspend/resume, clock changes, and settings edits need no re-arming.

Per tick, for each of today's lessons with a URL:

| Condition | Action | Status |
|---|---|---|
| `start - notify <= now < start` | tray reminder (`reminder_due`, notifications on) | — |
| `start - lead <= now < start` | open browser | `opened` |
| `start <= now < end`, not yet fired | in-app banner: "Підключитися зараз" / "Закрити" | `manual` on connect, `missed` on close |
| `now >= end`, not yet fired | record only | `missed` |

The row is **inserted before** the browser call; an `IntegrityError` on
`UNIQUE(lesson_id, occur_date)` means it already fired and the call is skipped. See
`ARCHITECTURE.md` -> "fire exactly once".

### The schedule starts when it is imported

`import_courses` stamps `schedule_active_from` with the current time, and `tick` skips any lesson
whose start on that date is earlier (`predates_schedule`). Skipped means *entirely*: not opened,
not offered, not recorded as missed.

A timetable describes what happens from the moment you set it up. Importing on a Saturday
afternoon to prepare for the week ahead used to stamp that Saturday's classes "missed" on the very
first tick, so a schedule set up at the weekend opened to a grid full of failures it had never had
a chance to act on. The same rule quietly fixes the ordinary mid-week case: importing at 15:00 no
longer retro-marks the morning.

It keys on the **start** time rather than the end, so a class that was already under way when the
import finished is left alone too — catching up on a call you were not yet set up for is not
something to do unasked.

### The cold-start rule

`Scheduler._cold_start` makes the **first** tick after start treat catch-up as `notify` whatever
`catchup_mode` says. Without it, launching the app after a missed morning opened a browser tab per
class that was still running. `open` mode applies from the second tick onward. Do not "simplify"
this into reading the setting directly — `tests/test_scheduler.py::TestColdStartNeverAmbushes` and
`tests/test_end_to_end.py::TestLaunchingIntoAMissedDay` exist to keep it.

### User marks

`storage.mark_occurrence` writes or overwrites an occurrence row directly, bypassing the
claim-before-open protocol. That is correct here and only here: the row records a decision the user
already made from the card menu ("позначити як відкриту" / "як пропущену"), and it is the same row
that makes `evaluate` answer "already fired", so a class marked skipped is never opened.
`clear_occurrence` undoes the mark and makes the class eligible again.

Statuses are per `(lesson, date)`, so a mark belongs to one week and the same class is untouched
on the next one.

### Advance reminders

`reminder_due(lesson, now, notify_minutes, already_fired)` is a second pure function, deliberately
not folded into `evaluate`. Folding it in would mean a reminder and a trigger were both outcomes of
one decision, one keystroke away from a reminder opening a browser. Reminders are also not recorded
in `occurrences` — a message is not an occurrence, and writing one would suppress the real open.

## 5. Autostart

`core/autostart.py` writes `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`,
value name `AutoPara`, data `"<exe path>" --hidden`. When running from source the command is
`"<pythonw>" "<abs path>\autopara_launch.pyw" --hidden`. `--hidden` starts the app to the tray
with no visible window.

It is enabled by default (`autostart_enabled` defaults to `1`) and `app.run()` syncs the registry
to the setting on every launch. Both installers write byte-identical strings; if they ever diverge,
`sync()` silently rewrites the entry on the next launch.

## 6. Theming

`core/theme.py` renders `ui/styles.qss` — a `string.Template` whose colours are `$tokens` — against
one of two palettes. `resolve()` turns the stored `system` setting into `light` or `dark` by
reading `HKCU\...\Themes\Personalize\AppsUseLightTheme`, which is how a fresh install comes up
matching the desktop it was installed on. The toolbar toggle pins the opposite of whatever is
showing.

QSS is not CSS: it has no variables and no cascade worth the name, so a second stylesheet file is
the obvious-looking design and the wrong one — a rule added to one file and forgotten in the other
stays invisible until someone switches theme. One template plus two dicts makes that impossible,
and `tests/test_ui.py::TestTheme::test_both_palettes_resolve_every_token` fails if a token is
missing from either palette.
