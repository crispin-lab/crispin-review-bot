"""GitHub Actions 이벤트 → 실행 모드.

| 이벤트 | 동작 |
|---|---|
| `pull_request` (opened · reopened · ready_for_review · synchronize) | draft 가 아니면 리뷰 |
| `issue_comment` 첫 줄 `/pcr ...` | 권한 확인 후 명령 실행 |
| `pull_request_review_comment` (권한 있는 사용자의 답글) | 답글 모드 |
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
    if not _is_allowed(comment):
        return 0
    if options.help:
        from .cli import HELP_PATH

        _comment(target, HELP_PATH.read_text("utf-8"))
        return 0
    return _execute(options)


def _on_review_comment(owner: str, repo: str, payload: dict) -> int:
    comment = payload["comment"]
    if payload.get("action") != "created":
        return 0
    if (comment.get("user") or {}).get("login") in ctx_module.bot_logins():
        return 0
    # 답글도 판단 단계(비용)를 부르므로 /pcr 명령과 같은 권한 기준을 적용한다.
    if not _is_allowed(comment):
        return 0
    if not _is_reply(owner, repo, comment):
        print("스레드 답글이 아닌 인라인 코멘트입니다. 건너뜁니다.")
        return 0
    target = Target(owner, repo, payload["pull_request"]["number"])
    return _execute(Options(target=target, reply=True, yes=True))


def _is_reply(owner: str, repo: str, comment: dict) -> bool:
    """payload 의 `in_reply_to_id` 를 믿지 않는다.

    webhook 스키마에서 이 필드는 optional 이고, 실제로 답글에도 실려 오지 않는다 — 호출 레포 두 곳에서
    `pull_request_review_comment` 실행 100 건이 전부 워크플로 `if` 에 걸러졌다 (2026-11-17 확인). 그래서
    호출 워크플로의 `if` 도 이 조건을 보지 않고, 여기서 REST 단건 조회로 확인한다 (그쪽엔 항상 실려 온다).
    """
    if comment.get("in_reply_to_id"):
        return True
    comment_id = comment.get("id")
    if not comment_id:
        return False
    try:
        fetched = gh.get(f"repos/{owner}/{repo}/pulls/comments/{comment_id}")
    except gh.GhError as error:
        # 조회가 실패하면 답글로 보지 않는다 — 판단 단계는 비용이 들어 기본값은 돌지 않는 쪽이다.
        print(f"경고: 코멘트 {comment_id} 조회 실패, 답글로 보지 않습니다: {error}", file=sys.stderr)
        return False
    return bool(isinstance(fetched, dict) and fetched.get("in_reply_to_id"))


def _is_allowed(comment: dict) -> bool:
    allowed = {item.strip() for item in os.environ.get("PCR_ALLOWED_ASSOCIATIONS", "OWNER,MEMBER").split(",")}
    association = comment.get("author_association")
    if association in allowed:
        return True
    print(f"권한이 없는 사용자의 요청은 무시합니다 ({association}).")
    return False


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
