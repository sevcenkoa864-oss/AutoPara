---
name: release-version
description: Settle AutoPara's release version before a commit lands — decide whether the change warrants a release and bump APP_VERSION in installer/AutoPara.nsi when it does. Use this whenever you are about to commit or push in this repo, and whenever the user mentions releasing, shipping, publishing, cutting a version, a new installer or .exe, or asks why a release did not show up on GitHub. The version number is what decides whether CI publishes a release at all, so it has to be right in the commit itself — noticing afterwards costs an extra commit and a confusing release history.
---

# Releasing AutoPara

## How a release actually happens here

`.github/workflows/installer.yml` runs `build.cmd` on **every** push to `main`. What it does with
the result depends on one number:

- It reads `APP_VERSION` from `installer/AutoPara.nsi` with the regex
  `^!define\s+APP_VERSION\s+"([^"]+)"`.
- It probes `gh release view v<version>`. If that release **already exists**, the job stops after
  the build and the `.exe` is only a workflow artifact.
- If the release does not exist, it creates `v<version>` and attaches
  `AutoPara-<version>-Setup.exe`.

So the number is the whole switch. Leave it alone and the push builds but publishes nothing; move it
and the push publishes. Two consequences worth holding onto:

- **A version whose release exists is spent.** You cannot re-cut `v1.4.0` — you can only go forward.
  That is why the number gets confirmed with the user before it is written.
- **The bump belongs in the commit being released**, which is what `CLAUDE.md`, `README.md` and
  `docs/ARCHITECTURE.md` all say. If the change is already pushed, a follow-up bump commit still
  cuts the release (CI reads the head of `main`, not the commit that touched the file) — it just
  reads worse in the log.

`installer/AutoPara.nsi` is the *single source* of the version: it names the `OutFile`,
`VIProductVersion`, and the Add/Remove Programs `DisplayVersion`. Nothing should track a version of
its own — anything that did would drift from the file the build reads.

## Step 1 — Does this change warrant a release?

Not every commit should publish an installer. Judge the change, then say your judgement out loud
before doing anything, so the user can overrule it in one word.

**Release it** when a user running the installed app would notice a difference: importer or parser
rules, scheduler behaviour, the window or tray, the installer or autostart, a bug fix in any of
those.

**Don't release** doc-only edits, test-only changes, workflow/CI edits, or refactors with no
behavioural change. Those still get committed and pushed; they just leave the number alone and CI
builds an artifact nobody has to download.

If the working tree already holds an **unpushed** bump, that number covers this change too. Don't
bump twice for one push — the intermediate version would never exist as a release and the history
implies a build that was never published.

## Step 2 — Read the current state

```bash
python .claude/skills/release-version/scripts/bump_version.py --show
```

This prints the current `APP_VERSION`, whether `v<version>` is already tagged **and** already
released, the three candidate next numbers with the same check applied to each, and every other line
in the repo that still names the current version. Read that last list — it is how you find the
derived mentions without keeping a stale checklist in this file.

## Step 3 — Propose the number, then wait

Say which part you are moving and why, in one line, and wait for a yes. This is the one step that is
awkward to undo, so it is worth the round trip.

For this project — a single-user desktop app — semver reads as:

- **patch** (`1.4.0` → `1.4.1`): a fix. Behaviour the user already expected now works.
- **minor** (`1.4.0` → `1.5.0`): new or changed behaviour the user will notice. Most releases here.
- **major** (`1.4.0` → `2.0.0`): something that invalidates the user's existing database or forces
  them to re-import or reinstall by hand. Rare — don't reach for it just because a change felt big.

## Step 4 — Apply it

```bash
python .claude/skills/release-version/scripts/bump_version.py --set 1.5.0
```

The script rewrites the define and then re-reads the file with the workflow's own regex, so a
rewrite that CI could not parse fails here instead of late in the build. It then lists every line
still naming the old version and leaves those to you, because they need judgement:

- Rewrite the ones that **describe the artifact being shipped now** — the README's build-output
  table names `dist\AutoPara-<version>-Setup.exe`, the file the build actually writes.
- Leave anything that is a **record of a past release**. A note about what 1.3.0 changed is still
  about 1.3.0.

## Step 5 — Verify

```bash
python -m pytest tests/test_installer.py
```

`tests/test_installer.py` parses the `.nsi` and checks it has not drifted from the app — the
autostart string, the window title, the `IfSilent` guards, the HKCU-only rule. It is fast and it is
the cheapest proof the file is still well-formed.

## Step 6 — Commit

Fold the bump into the commit carrying the change wherever that is still possible. When the change
is already pushed, make it its own commit and say plainly in the message that it exists to cut the
release, and for what.

After pushing, the release is not instant — the job builds the whole PyInstaller bundle first.
Confirm rather than assume:

```bash
gh run list --limit 3
```

If a release did not appear, the near-certain cause is that `v<version>` was already released. Run
`--show` again; it reports exactly that.
