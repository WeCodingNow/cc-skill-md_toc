# md-toc

A Claude Code skill that keeps a table of contents in markdown documents
that have sections. It ships a checker script and registers it as a
`PostToolUse` hook on `Edit`, `Write` and `MultiEdit`: whenever the agent
writes a `.md` file whose ToC is missing, incomplete or stale, the hook
answers with the list of problems and the agent fixes the file before it
moves on.

## What counts

- A file needs a ToC when it has an H1 and at least three headings below
  it. Files without an H1 (changelogs) and short notes are left alone.
- The ToC is a nested bullet list of `[Heading](#anchor)` links in the H1's
  own section, before the first H2. Anchors are GitHub/GitLab slugs.
- A file that already has a ToC is checked whatever its size: every heading
  below the H1 linked, no dead links.
- The user, and only the user, can exempt a file: `toc: false` in its YAML
  frontmatter or `<!-- toc: off -->` anywhere in it.

## Install

The skill lives in this repository and is linked into the skills directory
like the other skills here:

```
ln -s ~/Code/cc/skill-md-toc ~/.claude/skills/md-toc
```

No dependencies beyond Python 3.10+. The hook path in `SKILL.md` uses
`${CLAUDE_SKILL_DIR}`, so the link name does not matter.

## When the hook is active

Claude Code registers a skill's hooks when the skill loads and keeps them
for the rest of the session. The skill declares `paths: ["**/*.md"]`, so it
loads on its own once the agent works on a markdown file, and it can be
invoked as `/md-toc`. To have the check run in every session from the first
tool call, register the same command as a user- or project-level hook in
`settings.json`:

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
    ]
  }
}
```

## The script on its own

```
python3 scripts/check_toc.py docs/*.md         # report; exit 1 on any failure
python3 scripts/check_toc.py --print doc.md    # the ToC list doc.md should carry
echo '{"tool_input": {"file_path": "doc.md"}}' | python3 scripts/check_toc.py --hook
```

Tests: `python3 -m pytest tests`.
