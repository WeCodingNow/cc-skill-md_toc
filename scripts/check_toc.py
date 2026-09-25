#!/usr/bin/env python3
"""
Check that a markdown file's table of contents lists every heading.

A file needs a ToC when it has an H1 and at least MIN_HEADINGS headings
below it. The ToC is the list of `[text](#anchor)` links between the first
H1 and the next heading. Every heading after the first H1 must be linked
there, and every link there must point at a heading. Anchors are GitHub and
GitLab slugs of the heading text.

A file opts out with `toc: false` in its YAML frontmatter or an
`<!-- toc: off -->` comment anywhere in it. A project opts files out
without touching them through `.claude/md-toc-blacklist.txt`: the checker
looks for that file in the checked file's directory and its ancestors, and
the nearest one it finds lists glob patterns, one per line, relative to the
directory holding `.claude/`; a pattern without a `/` also matches the
file's name alone. Blank lines and lines starting with `#` are ignored.

The two hook modes split the work between a Claude Code session's tool
calls and the end of its turn, so the agent hears about a file once, after
it has finished editing, and not after each edit along the way. `--hook`
runs on PostToolUse and only notes which .md file the call wrote, in a
per-session file under the temp directory. `--stop-hook` runs on Stop,
checks every file noted for the session, and answers with one `block`
decision listing the problems of every file that fails. When the turn is
already the continuation a Stop hook asked for, the check does not block
again: it reports what is still wrong to the user and lets the turn end.

Usage:
  check_toc.py FILE...        report on each file; exit 1 if any fails
  check_toc.py --print FILE   print the ToC list FILE should carry
  check_toc.py --hook         PostToolUse hook: read the tool call as JSON
                              on stdin and note the .md file it wrote
  check_toc.py --stop-hook    Stop hook: check the files noted for the
                              session and answer with a `block` decision
                              that tells the agent what to fix
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

# Headings below the first H1 from which a ToC is required.
MIN_HEADINGS = 3

# The per-project list of files the checker leaves alone, relative to the
# directory that holds it; the nearest one above the checked file applies.
BLACKLIST = Path(".claude") / "md-toc-blacklist.txt"

HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^(```|~~~)")
TOC_LINK = re.compile(r"\[[^\]]*\]\(#([^)\s]+)\)")
LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
OPT_OUT_COMMENT = re.compile(r"<!--\s*toc:\s*(off|false|no|none)\s*-->", re.I)
OPT_OUT_FRONTMATTER = re.compile(r"^toc:\s*(false|off|no|none)\s*$", re.I | re.M)
INLINE_CODE = re.compile(r"`([^`]*)`")
LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
EMPHASIS = re.compile(r"(\*\*|__|\*)")
# An underscore that opens or closes emphasis, as opposed to one inside a
# `snake_case` word, which the anchor keeps.
EMPHASIS_UNDERSCORE = re.compile(r"(?<!\w)_+(?=\S)|(?<=\S)_+(?!\w)")
SLUG_STRIP = re.compile(r"[^\w\- ]", re.U)


@dataclass
class Heading:
    level: int
    text: str
    anchor: str
    line: int


def slug(text: str) -> str:
    """
    The anchor GitHub and GitLab give a heading: rendered text, lowercased,
    punctuation dropped, spaces turned into hyphens.
    """
    text = INLINE_CODE.sub(r"\1", text)
    text = LINK.sub(r"\1", text)
    text = EMPHASIS.sub("", text)
    text = EMPHASIS_UNDERSCORE.sub("", text)
    text = SLUG_STRIP.sub("", text.strip().lower())
    return text.replace(" ", "-")


def frontmatter_end(lines: list[str]) -> int:
    """
    The index of the first line after the YAML frontmatter, or 0 when the
    file has none.
    """
    if not lines or lines[0].strip() != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return index + 1
    return 0


def opted_out(text: str, lines: list[str]) -> bool:
    end = frontmatter_end(lines)
    front = "\n".join(lines[:end])
    return bool(OPT_OUT_FRONTMATTER.search(front) or OPT_OUT_COMMENT.search(text))


def blacklist_patterns(path: Path) -> tuple[Path, list[str]] | None:
    """
    The directory whose `.claude/md-toc-blacklist.txt` is the nearest one
    above `path`, with the patterns that file lists; `None` when no ancestor
    has one.
    """
    for root in path.resolve().parents:
        listing = root / BLACKLIST
        if not listing.is_file():
            continue
        patterns = []
        for line in listing.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
        return root, patterns
    return None


def blacklisted(path: Path) -> bool:
    """
    Whether the nearest `.claude/md-toc-blacklist.txt` above `path` lists
    it. A pattern is matched against the path relative to the directory
    holding `.claude/`, with `*` crossing directory separators; a pattern
    without a `/` is matched against the file's name as well.
    """
    found = blacklist_patterns(path)
    if found is None:
        return False
    root, patterns = found
    relative = path.resolve().relative_to(root).as_posix()
    return any(
        fnmatchcase(relative, pattern)
        or ("/" not in pattern and fnmatchcase(path.name, pattern))
        for pattern in patterns
    )


def headings(lines: list[str], start: int) -> list[Heading]:
    """
    Every ATX heading from `start` on, outside fenced code blocks, with the
    anchor each gets; a repeated anchor takes a `-1`, `-2`, ... suffix as
    GitHub and GitLab assign them.
    """
    found: list[Heading] = []
    seen: dict[str, int] = {}
    in_fence = False
    for number, line in enumerate(lines[start:], start=start + 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING.match(line)
        if not match:
            continue
        text = match.group(2)
        base = slug(text)
        count = seen.get(base, 0)
        seen[base] = count + 1
        anchor = base if count == 0 else f"{base}-{count}"
        found.append(Heading(len(match.group(1)), text, anchor, number))
    return found


def toc_anchors(lines: list[str], first_h1: Heading, next_heading: Heading | None) -> list[str]:
    """
    The anchors the list items between the first H1 and the next heading
    link to, in order.
    """
    stop = (next_heading.line - 1) if next_heading else len(lines)
    anchors: list[str] = []
    for line in lines[first_h1.line : stop]:
        if LIST_ITEM.match(line):
            anchors.extend(TOC_LINK.findall(line))
    return anchors


def render_toc(entries: list[Heading]) -> str:
    """
    The nested bullet list of links for `entries`, indented two spaces per
    level below H2.
    """
    top = min((heading.level for heading in entries), default=2)
    return "\n".join(
        f"{'  ' * (heading.level - top)}- [{heading.text}](#{heading.anchor})"
        for heading in entries
    )


def check(path: Path) -> list[str]:
    """
    The problems with `path`'s ToC, empty when the file is fine or needs no
    ToC.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if opted_out(text, lines) or blacklisted(path):
        return []
    all_headings = headings(lines, frontmatter_end(lines))
    first_h1 = next((heading for heading in all_headings if heading.level == 1), None)
    if first_h1 is None:
        return []
    below = [heading for heading in all_headings if heading.line > first_h1.line]
    next_heading = below[0] if below else None
    linked = toc_anchors(lines, first_h1, next_heading)
    if not linked and len(below) < MIN_HEADINGS:
        return []

    problems: list[str] = []
    wanted = {heading.anchor: heading for heading in below}
    missing = [heading for heading in below if heading.anchor not in linked]
    stale = [anchor for anchor in linked if anchor not in wanted]
    if not linked:
        problems.append(
            f'no table of contents under the H1 "{first_h1.text}" (line {first_h1.line}); '
            f"the file has {len(below)} headings below it"
        )
    for heading in missing:
        problems.append(
            f'heading "{"#" * heading.level} {heading.text}" (line {heading.line}) '
            f"is not linked as `#{heading.anchor}`"
        )
    for anchor in stale:
        problems.append(f"ToC link `#{anchor}` points at no heading")
    return problems


def print_toc(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    all_headings = headings(lines, frontmatter_end(lines))
    first_h1 = next((heading for heading in all_headings if heading.level == 1), None)
    if first_h1 is None:
        print(f"{path}: no H1 heading, so no ToC is required", file=sys.stderr)
        return 1
    below = [heading for heading in all_headings if heading.line > first_h1.line]
    print(render_toc(below))
    return 0


def report(paths: list[Path]) -> int:
    failed = False
    for path in paths:
        problems = check(path)
        if problems:
            failed = True
            print(f"{path}:")
            for problem in problems:
                print(f"  - {problem}")
    return 1 if failed else 0


def read_hook_input() -> dict:
    """The JSON Claude Code passes a hook on stdin; empty when it is not JSON."""
    try:
        call = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    return call if isinstance(call, dict) else {}


def noted_files(call: dict) -> Path:
    """
    The file that lists the markdown files written during the session `call`
    belongs to, one absolute path per line. It lives under the temp
    directory, so a session that ends without a Stop hook leaves nothing
    that outlives a reboot.
    """
    session = re.sub(r"[^\w.-]", "_", str(call.get("session_id") or "default"))
    return Path(tempfile.gettempdir()) / "md-toc" / session


def hook() -> int:
    """
    Note the markdown file the tool call on stdin wrote, for the Stop hook
    to check. Calls that wrote no existing `.md` file leave no trace.
    """
    call = read_hook_input()
    tool_input = call.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path or not file_path.endswith(".md"):
        return 0
    path = Path(file_path)
    if not path.is_file():
        return 0
    noted = noted_files(call)
    noted.parent.mkdir(parents=True, exist_ok=True)
    with noted.open("a", encoding="utf-8") as out:
        out.write(f"{path.resolve()}\n")
    return 0


def stop_hook() -> int:
    """
    Check every markdown file noted for the session and answer with one
    `block` decision listing the problems of each file that fails. A file
    that passes, or is gone, is forgotten. When the turn is already the
    continuation a Stop hook asked for, the agent has had its round of
    fixes: the files that still fail are reported to the user with a
    `systemMessage`, forgotten, and the turn ends.
    """
    call = read_hook_input()
    noted = noted_files(call)
    if not noted.is_file():
        return 0
    lines = noted.read_text(encoding="utf-8").splitlines()
    paths = [Path(line) for line in dict.fromkeys(lines) if line]
    failing = [(path, check(path)) for path in paths if path.is_file()]
    failing = [(path, problems) for path, problems in failing if problems]
    if not failing or call.get("stop_hook_active"):
        noted.unlink()
        if failing:
            names = ", ".join(str(path) for path, _ in failing)
            print(json.dumps({"systemMessage": f"md-toc: table of contents still wrong in {names}"}))
        return 0
    noted.write_text("".join(f"{path}\n" for path, _ in failing), encoding="utf-8")
    script = Path(__file__).resolve()
    reason = "Fix the table of contents of the markdown files you edited before you finish:\n" + "".join(
        f"\n{path}:\n" + "".join(f"- {problem}\n" for problem in problems) for path, problems in failing
    ) + (
        f"\nRun `python3 {script} --print FILE` for the complete list a file should carry and put "
        "it right under the H1, before the first H2. A file the user said needs no ToC gets "
        "`toc: false` in its frontmatter, an `<!-- toc: off -->` comment, or a pattern in the "
        f"project's `{BLACKLIST.as_posix()}` instead."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def main(argv: list[str]) -> int:
    if argv == ["--hook"]:
        return hook()
    if argv == ["--stop-hook"]:
        return stop_hook()
    if len(argv) == 2 and argv[0] == "--print":
        return print_toc(Path(argv[1]))
    if argv and not argv[0].startswith("-"):
        return report([Path(arg) for arg in argv])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
