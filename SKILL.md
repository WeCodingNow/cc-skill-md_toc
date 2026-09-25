---
name: md-toc
description: Keeps a table of contents in every markdown document that has sections — design docs, specs, research notes, plans, READMEs, runbooks, anything under .spec/ or .spec-inbox/ or any other .md with an H1 and several headings. Use this skill whenever you create or edit a markdown file, add, rename or remove a heading, or restructure a document, even if nobody mentions a ToC. It wires hooks that check every .md file you wrote once you finish your turn and tell you what the ToC is missing; the only way a file legitimately has no ToC is that the user said it does not need one.
paths:
  - "**/*.md"
hooks:
  PostToolUse:
    - matcher: "Edit|Write|MultiEdit"
      hooks:
        - type: command
          command: python3 "${HOME}/.claude/skills/md-toc/scripts/check_toc.py" --hook
  Stop:
    - hooks:
        - type: command
          command: python3 "${HOME}/.claude/skills/md-toc/scripts/check_toc.py" --stop-hook

---

# Table of contents in markdown documents

A document with sections carries a table of contents right under its title,
so a reader — human or agent — sees the shape of the document before the
first section and can jump to any of them. The rules below say what that
ToC is, when a file needs one, and how the hooks bundled here hold you to
it.

## What the ToC is

- It sits in the first H1's own section: after the title and any intro
  paragraph, before the first H2.
- It is a nested bullet list, one item per heading below the H1, nested by
  heading level, each item a link to the heading's anchor:

  ```markdown
  # Offsets overflow: action plan

  Short intro, if the document has one.

  - [Decision](#decision)
  - [Steps](#steps)
    - [1. Extract the shared helpers](#1-extract-the-shared-helpers)
    - [2. `AggregateViewStrings`, group keys](#2-aggregateviewstrings-group-keys)
  - [Left as is](#left-as-is)

  ## Decision
  ...
  ```

- Anchors are the GitHub/GitLab slug of the heading text: rendered text
  (backticks and emphasis dropped, link text kept), lowercased, punctuation
  removed, spaces turned into hyphens; a repeated heading gets `-1`, `-2`, …
  Getting slugs right by hand is error-prone for headings with punctuation
  or code, so generate the list rather than typing it:

  ```
  python3 "${CLAUDE_SKILL_DIR}/scripts/check_toc.py" --print path/to/doc.md
  ```

  prints the complete list for the file as it is now; paste it under the
  H1. Rerun it after any heading change and replace the list.
- It has no heading of its own (a `## Contents` heading would be one more
  heading to list). Keep the document's own headings as they are; the ToC
  follows them, not the other way round.

## When a file needs one

A file needs a ToC when it has an H1 and at least three headings below it.
Shorter notes do not, and a file with no H1 (a changelog, a fragment) is
outside this rule. Once a file has a ToC, it has to be complete whatever
its size: every heading below the H1 linked, no link pointing at a heading
that no longer exists.

Adding, renaming, removing or re-levelling a heading changes the ToC; make
the two edits together, or regenerate the list with `--print` right after
the heading edit.

## When the user says no ToC

Only the user decides that a document does not need a ToC. When they say
so, record it in the file so the hook and future readers know it was a
decision:

- `toc: false` in the YAML frontmatter, for a file that has one (specs
  under `.spec/` and `.spec-inbox/` all do);
- `<!-- toc: off -->` anywhere in the file otherwise;
- a line in the project's `.claude/md-toc-blacklist.txt`, for a file the
  project cannot annotate — a `CHANGELOG.md` kept in Keep a Changelog form,
  a generated file, a vendored one. The checker uses the nearest such list
  above the file. Each line is a glob relative to the directory that holds
  `.claude/`, `*` crosses directory separators, a pattern with no `/` also
  matches the file's name alone (`CHANGELOG.md` covers every changelog in
  the tree), and `#` starts a comment.

Do not add any of these on your own judgement; a document you think is too
small either falls under the three-heading threshold or gets a ToC.

## The hooks

Every `Edit`, `Write` or `MultiEdit` of a `.md` file runs
`scripts/check_toc.py --hook`, which only notes the file for the session
and says nothing, so a document restructured over many edits draws no
comment while it is in flux. When you finish your turn, the `Stop` hook
runs `scripts/check_toc.py --stop-hook`, which checks every file noted for
the session. When any of them needs a ToC and its ToC is missing,
incomplete or stale, the hook keeps the turn going with one message
listing, per file, each unlinked heading with its line and anchor and each
dead link; fix every file it names, then finish. A file that passes, opts
out, is listed in the project's blacklist, or needs no ToC is not
mentioned. The hook asks once per turn: when the turn is already the
continuation it asked for, a file that still fails is reported to the user
and the turn ends.

The same script checks files from the command line for CI or a quick
audit:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/check_toc.py" docs/*.md
```

It prints the problems per file and exits non-zero when any file fails.

## Sources of mistakes

- Headings inside fenced code blocks are not headings; the checker skips
  them, so do not list them.
- A heading with inline code or a link, such as `` ## `RetypeStringsExec`, the node ``,
  slugs to `retypestringsexec-the-node`; let `--print` produce it.
- Two headings with the same text get anchors `name` and `name-1`, in
  document order.
- The intro paragraph between the H1 and the ToC is fine; a second list
  under the H1 that is not the ToC (a summary list of points, say) confuses
  readers about which list is the contents — put such lists under a
  heading.
