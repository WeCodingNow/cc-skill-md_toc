#!/usr/bin/env python3
"""
Check that a markdown file's table of contents lists every heading.

A file needs a ToC when it has an H1 and at least MIN_HEADINGS headings
below it. The ToC is the list of `[text](#anchor)` links between the first
H1 and the next heading. Every heading after the first H1 must be linked
there, and every link there must point at a heading. Anchors are GitHub and
GitLab slugs of the heading text.

A file opts out with `toc: false` in its YAML frontmatter or an
`<!-- toc: off -->` comment anywhere in it.

Usage:
  check_toc.py FILE...        report on each file; exit 1 if any fails
  check_toc.py --print FILE   print the ToC list FILE should carry
  check_toc.py --hook         Claude Code PostToolUse hook: read the tool
                              call as JSON on stdin, check the edited .md
                              file, and answer with a `block` decision that
                              tells the agent what to fix
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Headings below the first H1 from which a ToC is required.
MIN_HEADINGS = 3

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
    if opted_out(text, lines):
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


def hook() -> int:
    """
    Read a Claude Code tool call from stdin and check the markdown file it
    wrote. A file that fails comes back as a `block` decision whose reason
    lists what to fix; anything else is silent.
    """
    try:
        call = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool_input = call.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path or not file_path.endswith(".md"):
        return 0
    path = Path(file_path)
    if not path.is_file():
        return 0
    problems = check(path)
    if not problems:
        return 0
    script = Path(__file__).resolve()
    reason = (
        f"{path} needs its table of contents fixed:\n"
        + "\n".join(f"- {problem}" for problem in problems)
        + "\n\nThe ToC is the nested bullet list of `[Heading](#anchor)` links right under "
        f"the first H1, before the first H2, listing every heading below the H1. Run "
        f"`python3 {script} --print {path}` to get the complete list and put it there. "
        "If the user said this file needs no ToC, add `toc: false` to its frontmatter "
        "or an `<!-- toc: off -->` comment instead."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def main(argv: list[str]) -> int:
    if argv == ["--hook"]:
        return hook()
    if len(argv) == 2 and argv[0] == "--print":
        return print_toc(Path(argv[1]))
    if argv and not argv[0].startswith("-"):
        return report([Path(arg) for arg in argv])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
