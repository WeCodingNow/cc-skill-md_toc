"""
Tests for scripts/check_toc.py.
"""

import json
import os
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


def run_hook(mode: str, call, tmp_path: Path) -> str:
    """
    Run the script in hook mode `mode` with `call` on stdin (a dict, or raw
    text) and the session state kept under `tmp_path`; returns stdout.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), mode],
        input=call if isinstance(call, str) else json.dumps(call),
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
    )
    return result.stdout


def edit(path: Path, tmp_path: Path, session: str = "s1") -> str:
    return run_hook(
        "--hook",
        {"session_id": session, "tool_name": "Edit", "tool_input": {"file_path": str(path)}},
        tmp_path,
    )


def stop(tmp_path: Path, session: str = "s1", active: bool = False) -> str:
    call = {"session_id": session, "hook_event_name": "Stop", "stop_hook_active": active}
    return run_hook("--stop-hook", call, tmp_path)


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


NEEDS_TOC = "# T\n\n## A\n\n## B\n\n## C\n"


def test_blacklist_exempts_the_files_it_lists(tmp_path: Path) -> None:
    listing = tmp_path / ".claude" / "md-toc-blacklist.txt"
    listing.parent.mkdir()
    listing.write_text(
        "# files kept without a table of contents\n\nCHANGELOG.md\ngenerated/*.md\n",
        encoding="utf-8",
    )
    (tmp_path / "generated" / "deep").mkdir(parents=True)
    (tmp_path / "sub").mkdir()

    exempt = [
        write(tmp_path, NEEDS_TOC, "CHANGELOG.md"),
        write(tmp_path / "sub", NEEDS_TOC, "CHANGELOG.md"),
        write(tmp_path / "generated", NEEDS_TOC, "api.md"),
        write(tmp_path / "generated" / "deep", NEEDS_TOC, "api.md"),
    ]
    for path in exempt:
        assert check_toc.check(path) == [], path

    checked = write(tmp_path / "sub", NEEDS_TOC, "notes.md")
    assert any("no table of contents" in problem for problem in check_toc.check(checked))


def test_nearest_blacklist_wins(tmp_path: Path) -> None:
    outer = tmp_path / ".claude"
    outer.mkdir()
    (outer / "md-toc-blacklist.txt").write_text("*.md\n", encoding="utf-8")
    inner = tmp_path / "project" / ".claude"
    inner.mkdir(parents=True)
    (inner / "md-toc-blacklist.txt").write_text("README.md\n", encoding="utf-8")

    assert check_toc.check(write(tmp_path / "project", NEEDS_TOC, "README.md")) == []
    checked = write(tmp_path / "project", NEEDS_TOC, "doc.md")
    assert check_toc.check(checked) != []


def test_hooks_are_silent_for_a_blacklisted_file(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "md-toc-blacklist.txt").write_text("CHANGELOG.md\n", encoding="utf-8")
    path = write(tmp_path, NEEDS_TOC, "CHANGELOG.md")
    assert edit(path, tmp_path) == ""
    assert stop(tmp_path) == ""


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


def test_edits_are_silent_and_stop_blocks_once_per_file(tmp_path: Path) -> None:
    bad = write(tmp_path, NEEDS_TOC, "bad.md")
    other = write(tmp_path, "# T\n\n- [A](#a)\n\n## A\n\n## B\n", "other.md")
    good = write(tmp_path, COMPLETE, "good.md")
    for path in (bad, bad, other, good, bad):
        assert edit(path, tmp_path) == ""

    answer = json.loads(stop(tmp_path))
    assert answer["decision"] == "block"
    reason = answer["reason"]
    assert reason.count("bad.md:") == 1
    assert reason.count("other.md:") == 1
    assert "good.md" not in reason
    assert "no table of contents" in reason
    assert '"## B" (line 7)' in reason
    assert "--print" in reason


def test_stop_forgets_files_that_pass_and_keeps_the_rest(tmp_path: Path) -> None:
    bad = write(tmp_path, NEEDS_TOC, "bad.md")
    fixed = write(tmp_path, NEEDS_TOC, "fixed.md")
    edit(bad, tmp_path)
    edit(fixed, tmp_path)
    assert json.loads(stop(tmp_path))["decision"] == "block"

    fixed.write_text(COMPLETE, encoding="utf-8")
    answer = json.loads(stop(tmp_path))
    assert answer["decision"] == "block"
    assert "bad.md:" in answer["reason"]
    assert "fixed.md" not in answer["reason"]

    bad.write_text(COMPLETE, encoding="utf-8")
    assert stop(tmp_path) == ""
    assert stop(tmp_path) == ""


def test_stop_reports_to_the_user_instead_of_blocking_again(tmp_path: Path) -> None:
    bad = write(tmp_path, NEEDS_TOC, "bad.md")
    edit(bad, tmp_path)
    assert json.loads(stop(tmp_path))["decision"] == "block"

    answer = json.loads(stop(tmp_path, active=True))
    assert "decision" not in answer
    assert "bad.md" in answer["systemMessage"]
    assert stop(tmp_path) == ""


def test_sessions_keep_separate_notes(tmp_path: Path) -> None:
    bad = write(tmp_path, NEEDS_TOC, "bad.md")
    edit(bad, tmp_path, session="a")
    assert stop(tmp_path, session="b") == ""
    assert json.loads(stop(tmp_path, session="a"))["decision"] == "block"


def test_stop_forgets_a_deleted_file(tmp_path: Path) -> None:
    bad = write(tmp_path, NEEDS_TOC, "bad.md")
    edit(bad, tmp_path)
    bad.unlink()
    assert stop(tmp_path) == ""


@pytest.mark.parametrize(
    "call",
    [
        {"session_id": "s1", "tool_name": "Write", "tool_input": {"file_path": "/tmp/x.py"}},
        {"session_id": "s1", "tool_name": "Write", "tool_input": {"file_path": "/nonexistent/doc.md"}},
        {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "ls"}},
    ],
)
def test_hook_notes_nothing_for_other_calls(call: dict, tmp_path: Path) -> None:
    assert run_hook("--hook", call, tmp_path) == ""
    assert not (tmp_path / "md-toc").exists()


def test_hooks_are_silent_for_a_passing_file(tmp_path: Path) -> None:
    path = write(tmp_path, COMPLETE)
    assert edit(path, tmp_path) == ""
    assert stop(tmp_path) == ""


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


@pytest.mark.parametrize("mode", ["--hook", "--stop-hook"])
def test_hooks_ignore_garbage_stdin(mode: str, tmp_path: Path) -> None:
    assert run_hook(mode, "not json", tmp_path) == ""
