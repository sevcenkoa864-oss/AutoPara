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
| Events with a link | **60** |
| Events without a link | **17** |
| Per course (I..VI) | 25, 11, 12, 13, **0**, 16 |
| Distinct hyperlink relationships | 60 (20 unique URLs) |
| Providers | 49 Zoom, 11 Google Meet |

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

`settings` keys: `selected_course_id`, `selected_group_id`, `lead_minutes` (default `1`),
`class_duration_minutes` (`80`), `autostart_enabled`, `catchup_mode` (`notify` | `open` | `missed`),
`last_import_path`.

### Re-import behavior

Re-importing replaces imported lessons for the affected course but **preserves**:
- lessons the user created manually (`is_manual = 1`),
- the `occurrences` log (so today's already-opened classes stay opened),
- user settings.

`source_key` (course ordinal + day + pair + subject) lets a re-imported lesson keep its identity, and
therefore its occurrence history, when the document is updated.

## 4. Scheduler

`core/scheduler.py` runs a `QTimer` every **15 s**. Polling rather than one-shot timers means
suspend/resume, clock changes, and settings edits need no re-arming.

Per tick, for each of today's lessons with a URL:

| Condition | Action | Status |
|---|---|---|
| `start - lead <= now < start` | open browser | `opened` |
| `start <= now < end`, not yet fired | tray notification, click to open | `manual` on click |
| `now >= end`, not yet fired | record only | `missed` |

The row is **inserted before** the browser call; an `IntegrityError` on
`UNIQUE(lesson_id, occur_date)` means it already fired and the call is skipped. See
`ARCHITECTURE.md` -> "fire exactly once".

## 5. Autostart

`core/autostart.py` writes `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`,
value name `AutoPara`, data `"<exe path>" --hidden`. When running from source the command is
`"<python>" -m autopara --hidden`. `--hidden` starts the app to the tray with no visible window.
