"""👀(시작) / 🎉(완료) 반응. 상태 신호일 뿐이라 실패해도 실행을 멈추지 않는다."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import gh
from .target import Target


def load_state(directory: Path) -> dict:
    path = directory / "state.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def save_state(directory: Path, state: dict) -> None:
    (directory / "state.json").write_text(json.dumps(state, indent=2), "utf-8")


def start_issue(target: Target) -> int | None:
    return _add(f"repos/{target.slug}/issues/{target.number}/reactions", "eyes")


def finish_issue(target: Target, reaction_id: int | None) -> None:
    if reaction_id is None:
        return
    _remove(f"repos/{target.slug}/issues/{target.number}/reactions/{reaction_id}")
    _add(f"repos/{target.slug}/issues/{target.number}/reactions", "hooray")


def start_comment(target: Target, comment_id: int) -> int | None:
    return _add(f"repos/{target.slug}/pulls/comments/{comment_id}/reactions", "eyes")


def finish_comment(target: Target, comment_id: int, reaction_id: int | None, *, celebrate: bool) -> None:
    if reaction_id is not None:
        _remove(f"repos/{target.slug}/pulls/comments/{comment_id}/reactions/{reaction_id}")
    if celebrate:
        _add(f"repos/{target.slug}/pulls/comments/{comment_id}/reactions", "hooray")


def _add(path: str, content: str) -> int | None:
    try:
        return gh.send("POST", path, {"content": content})["id"]
    except (gh.GhError, KeyError, TypeError) as error:
        print(f"경고: 반응({content}) 추가 실패: {error}", file=sys.stderr)
        return None


def _remove(path: str) -> None:
    try:
        gh.send("DELETE", path)
    except gh.GhError as error:
        print(f"경고: 반응 제거 실패: {error}", file=sys.stderr)
