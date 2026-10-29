"""GitHub Actions 이벤트 → 실행 모드.

| 이벤트 | 동작 |
|---|---|
| `pull_request` (opened · reopened · ready_for_review · synchronize) | draft 가 아니면 리뷰 |
| `issue_comment` 첫 줄 `/pcr ...` | 권한 확인 후 명령 실행 |
| `pull_request_review_comment` (봇이 아닌 답글) | 답글 모드 |
| `workflow_dispatch` (`pr_number`, `args`) | 명령 실행 |
"""

from __future__ import annotations

import json
import os
import shlex
import sys

from . import context as ctx_module
from . import gh, review
from .sanitize import sanitize
from .target import ArgsError, Options, Target, parse, parse_command

_REVIEW_ACTIONS = {"opened", "reopened", "ready_for_review", "synchronize"}


def run() -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
        payload = json.load(handle)
    owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)

    if event == "pull_request":
        return _on_pull_request(owner, repo, payload)
    if event == "issue_comment":
        return _on_command(owner, repo, payload)
    if event == "pull_request_review_comment":
        return _on_review_comment(owner, repo, payload)
    if event == "workflow_dispatch":
        inputs = payload.get("inputs") or {}
        target = Target(owner, repo, int(inputs["pr_number"]))
        return _execute(parse(shlex.split(inputs.get("args") or ""), default_target=target))
    print(f"처리하지 않는 이벤트입니다: {event}")
    return 0


def _on_pull_request(owner: str, repo: str, payload: dict) -> int:
    pr = payload["pull_request"]
    if payload.get("action") not in _REVIEW_ACTIONS or pr.get("draft"):
        print("draft 이거나 리뷰 대상 이벤트가 아닙니다.")
        return 0
    target = Target(owner, repo, pr["number"])
    return _execute(parse(shlex.split(os.environ.get("PCR_DEFAULT_ARGS", "")), default_target=target))


def _on_command(owner: str, repo: str, payload: dict) -> int:
    issue, comment = payload["issue"], payload["comment"]
    if payload.get("action") != "created" or not issue.get("pull_request"):
        return 0
    target = Target(owner, repo, issue["number"])
    try:
        options = parse_command(comment.get("body", ""), target)
    except ArgsError as error:
        _comment(target, f"명령을 실행하지 못했습니다: {error}\n\n`/pcr --help` 로 사용법을 볼 수 있습니다.")
        return 0
    if options is None:
        return 0
    allowed = {item.strip() for item in os.environ.get("PCR_ALLOWED_ASSOCIATIONS", "OWNER,MEMBER").split(",")}
    if comment.get("author_association") not in allowed:
        print(f"권한이 없는 사용자의 명령은 무시합니다 ({comment.get('author_association')}).")
        return 0
    if options.help:
        from .cli import HELP_PATH

        _comment(target, HELP_PATH.read_text("utf-8"))
        return 0
    return _execute(options)


def _on_review_comment(owner: str, repo: str, payload: dict) -> int:
    comment = payload["comment"]
    if payload.get("action") != "created" or not comment.get("in_reply_to_id"):
        return 0
    if (comment.get("user") or {}).get("login") in ctx_module.bot_logins():
        return 0
    target = Target(owner, repo, payload["pull_request"]["number"])
    return _execute(Options(target=target, reply=True, yes=True))


def _execute(options: Options) -> int:
    from .cli import run

    options.yes = True  # CI 는 대화형이 아니다
    code = run(options)
    if code == review.EXIT_RATE_LIMITED:
        return 0
    return code


def _comment(target: Target, body: str) -> None:
    try:
        gh.send("POST", f"repos/{target.slug}/issues/{target.number}/comments", {"body": sanitize(body)})
    except gh.GhError as error:
        print(f"경고: 안내 코멘트 실패: {error}", file=sys.stderr)
