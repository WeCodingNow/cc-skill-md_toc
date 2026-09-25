# md-toc

A Claude Code skill that keeps a table of contents in markdown documents
that have sections. It ships a checker script and registers it twice: a
`PostToolUse` hook on `Edit`, `Write` and `MultiEdit` notes every `.md`
file the agent writes, and a `Stop` hook checks the noted files when the
agent finishes its turn. When any of them has a ToC that is missing,
incomplete or stale, the `Stop` hook answers with one list of problems for
all of them and the agent fixes the files before it stops. A document
restructured over many edits draws no comment while it is in flux.

## What counts

- A file needs a ToC when it has an H1 and at least three headings below
  it. Files without an H1 (changelogs) and short notes are left alone.
- The ToC is a nested bullet list of `[Heading](#anchor)` links in the H1's
  own section, before the first H2. Anchors are GitHub/GitLab slugs.
- A file that already has a ToC is checked whatever its size: every heading
  below the H1 linked, no dead links.
- The user, and only the user, can exempt a file: `toc: false` in its YAML
  frontmatter, `<!-- toc: off -->` anywhere in it, or a glob for it in the
  project's `.claude/md-toc-blacklist.txt` (one pattern per line, relative
  to the directory holding `.claude/`; a bare file name matches at any
  depth; `#` comments). The nearest list above the file applies.

## Install

The skill lives in this repository and is linked into the skills directory
like the other skills here:

```
ln -s ~/Code/cc/skill-md_toc ~/.claude/skills/md-toc
```

No dependencies beyond Python 3.10+. The hook commands in `SKILL.md` name
the script as `${HOME}/.claude/skills/md-toc/scripts/check_toc.py`, so the
link has to be called `md-toc`.

## When the hooks are active

Claude Code registers a skill's hooks when the skill is invoked — through
`/md-toc` or the Skill tool — and keeps them for the rest of that session.
The `paths: ["**/*.md"]` entry only makes Claude Code announce the skill
after it touches a markdown file; it does not load the skill or register
the hooks, so a session in which the agent never invokes `md-toc` runs no
check. Editing the hook lines in `SKILL.md` changes nothing in a session
that already registered the old ones; invoke the skill again or start a new
session, and use `/hooks` to see what is registered.

The `Stop` hook asks for fixes once per turn. When the turn it is ending is
already the continuation it asked for, it lets the agent stop and shows the
files that still fail as a message in the transcript, so a file the agent
cannot or will not fix does not keep the turn going forever. The list of
files noted for a session lives under the system temp directory, in
`md-toc/<session id>`.

To have the check run on every session from the first tool call, register
the same commands as user- or project-level hooks in `settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/md-toc/scripts/check_toc.py --hook"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/md-toc/scripts/check_toc.py --stop-hook"
          }
        ]
      }
    ]
  }
}
```

## The script on its own

```
python3 scripts/check_toc.py docs/*.md         # report; exit 1 on any failure
python3 scripts/check_toc.py --print doc.md    # the ToC list doc.md should carry
echo '{"session_id": "x", "tool_input": {"file_path": "doc.md"}}' | python3 scripts/check_toc.py --hook
echo '{"session_id": "x"}' | python3 scripts/check_toc.py --stop-hook
```

Tests: `python3 -m pytest tests`.
