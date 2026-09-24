"""
Tests for scripts/check_toc.py.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_toc.py"
sys.path.insert(0, str(SCRIPT.parent))

import check_toc  # noqa: E402


def write(tmp_path: Path, text: str, name: str = "doc.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


COMPLETE = """\
---
description: A spec.
---

# Title

Intro paragraph.

- [Decision](#decision)
- [Steps](#steps)
  - [1. `Extract` the helpers](#1-extract-the-helpers)
- [Left as is](#left-as-is)

## Decision

## Steps

### 1. `Extract` the helpers

## Left as is
"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Decision", "decision"),
        ("1. `Extract` the helpers", "1-extract-the-helpers"),
        ("`RetypeStringsExec`, the node", "retypestringsexec-the-node"),
        ("Where `LargeUtf8` columns would reach", "where-largeutf8-columns-would-reach"),
        ("**Bold** and _snake_case_", "bold-and-snake_case"),
        ("A [link](http://x) here", "a-link-here"),
        ("Partial/Final pair", "partialfinal-pair"),
    ],
)
def test_slug(text: str, expected: str) -> None:
    assert check_toc.slug(text) == expected


def test_complete_toc_passes(tmp_path: Path) -> None:
    assert check_toc.check(write(tmp_path, COMPLETE)) == []


def test_missing_toc_is_reported(tmp_path: Path) -> None:
    text = "# Title\n\n## A\n\n## B\n\n## C\n"
    problems = check_toc.check(write(tmp_path, text))
    assert any("no table of contents" in problem for problem in problems)
    assert sum("is not linked" in problem for problem in problems) == 3


def test_unlinked_heading_and_dead_link_are_reported(tmp_path: Path) -> None:
    text = COMPLETE.replace("- [Left as is](#left-as-is)", "- [Gone](#gone)")
    problems = check_toc.check(write(tmp_path, text))
    assert problems == [
        'heading "## Left as is" (line 20) is not linked as `#left-as-is`',
        "ToC link `#gone` points at no heading",
    ]


def test_short_file_needs_no_toc(tmp_path: Path) -> None:
    assert check_toc.check(write(tmp_path, "# Title\n\n## A\n\n## B\n")) == []


def test_short_file_with_a_toc_is_still_checked(tmp_path: Path) -> None:
    text = "# Title\n\n- [A](#a)\n\n## A\n\n## B\n"
    problems = check_toc.check(write(tmp_path, text))
    assert problems == ['heading "## B" (line 7) is not linked as `#b`']


def test_file_without_h1_needs_no_toc(tmp_path: Path) -> None:
    text = "## Unreleased\n\n### Added\n\n### Fixed\n\n## 1.0\n"
    assert check_toc.check(write(tmp_path, text)) == []


@pytest.mark.parametrize(
    "text",
    [
        "---\ndescription: x\ntoc: false\n---\n\n# T\n\n## A\n\n## B\n\n## C\n",
        "# T\n\n<!-- toc: off -->\n\n## A\n\n## B\n\n## C\n",
    ],
)
def test_opt_out(tmp_path: Path, text: str) -> None:
    assert check_toc.check(write(tmp_path, text)) == []


def test_headings_in_code_fences_are_ignored(tmp_path: Path) -> None:
    text = (
        "# T\n\n- [A](#a)\n- [B](#b)\n- [C](#c)\n\n## A\n\n```\n## not a heading\n```\n\n"
        "## B\n\n## C\n"
    )
    assert check_toc.check(write(tmp_path, text)) == []


def test_repeated_headings_get_numbered_anchors(tmp_path: Path) -> None:
    text = "# T\n\n- [A](#a)\n- [A](#a-1)\n- [B](#b)\n\n## A\n\n## A\n\n## B\n"
    assert check_toc.check(write(tmp_path, text)) == []


def test_print_renders_nested_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, "# T\n\n## A\n\n### A.1\n\n## B\n")
    assert check_toc.print_toc(path) == 0
    assert capsys.readouterr().out == "- [A](#a)\n  - [A.1](#a1)\n- [B](#b)\n"


def test_hook_blocks_with_the_problems(tmp_path: Path) -> None:
    path = write(tmp_path, "# T\n\n## A\n\n## B\n\n## C\n")
    call = {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--hook"],
        input=json.dumps(call),
        capture_output=True,
        text=True,
        check=True,
    )
    answer = json.loads(result.stdout)
    assert answer["decision"] == "block"
    assert "no table of contents" in answer["reason"]
    assert "--print" in answer["reason"]


@pytest.mark.parametrize(
    "call",
    [
        {"tool_name": "Write", "tool_input": {"file_path": "/tmp/x.py"}},
        {"tool_name": "Write", "tool_input": {"file_path": "/nonexistent/doc.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    ],
)
def test_hook_is_silent_for_other_calls(call: dict) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--hook"],
        input=json.dumps(call),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""


def test_hook_is_silent_for_a_passing_file(tmp_path: Path) -> None:
    path = write(tmp_path, COMPLETE)
    call = {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--hook"],
        input=json.dumps(call),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""


def test_cli_report_exits_nonzero(tmp_path: Path) -> None:
    bad = write(tmp_path, "# T\n\n## A\n\n## B\n\n## C\n", "bad.md")
    good = write(tmp_path, COMPLETE, "good.md")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(good), str(bad)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "bad.md:" in result.stdout
    assert "good.md" not in result.stdout


def test_hook_ignores_garbage_stdin() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--hook"],
        input="not json",
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""
