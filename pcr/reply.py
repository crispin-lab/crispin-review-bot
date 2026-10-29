"""답글 모드: 봇이 시작한 미해결 스레드의 답글에 응답하고, 수정이 확인되면 resolve 한다."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from . import context as ctx_module
from . import gh, judge, reactions
from .fingerprint import REPLY_MARKER, strip_markers
from .sanitize import sanitize
from .target import Options, Target

MAX_PAGES = 5
BATCH = 5

_THREADS_QUERY = """
query($owner:String!, $repo:String!, $num:Int!, $after:String) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$num) {
      reviewThreads(first:100, after:$after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id isResolved path line originalLine
          comments(first:100) {
            nodes { databaseId author { login } body createdAt }
          }
        }
      }
    }
  }
}
"""

_RESOLVE = "mutation($id:ID!) { resolveReviewThread(input:{threadId:$id}) { thread { id isResolved } } }"


def run(options: Options) -> int:
    target = options.target
    for warning in options.warnings:
        print(f"경고: {warning}", file=sys.stderr)
    context, _ = ctx_module.collect(target, with_prior=False)
    directory = ctx_module.save(context, "")
    threads = _pending_threads(target, context.bot_logins)
    if not threads:
        print("응답할 스레드가 없습니다.")
        return 0

    reacted = {}
    if not options.dry_run:
        for thread in threads:
            last = thread["comments"][-1]["databaseId"]
            reacted[thread["id"]] = reactions.start_comment(target, last)

    decisions = _classify(context, threads, directory)
    plan = [
        {**decision, "should_resolve": bool(decision["fix_confirmed"])}  # resolve 는 수정 확인과 같은 값으로 고정
        for decision in decisions
    ]
    _write_plan(directory, target, threads, plan)
    if options.dry_run:
        print(f"dry-run: 게시하지 않았습니다. 계획: {directory / 'replies.md'}")
        return 0

    by_id = {thread["id"]: thread for thread in threads}
    posted = resolved = failed = 0
    for decision in plan:
        thread = by_id[decision["threadId"]]
        root = thread["comments"][0]["databaseId"]
        last = thread["comments"][-1]["databaseId"]
        body = sanitize(f"{decision['reply_body'].strip()}\n\n{REPLY_MARKER}")
        try:
            gh.send("POST", f"repos/{target.slug}/pulls/{target.number}/comments/{root}/replies", {"body": body})
        except gh.GhError as error:
            # 답글이 안 올라갔으면 resolve 하지 않는다. 👀 는 남겨 둔다.
            failed += 1
            print(f"경고: {thread['path']} 답글 실패: {error}", file=sys.stderr)
            continue
        posted += 1
        done = False
        if decision["should_resolve"]:
            try:
                gh.graphql(_RESOLVE, {"id": thread["id"]})
                done = True
                resolved += 1
            except gh.GhError as error:
                print(f"경고: {thread['path']} resolve 실패: {error}", file=sys.stderr)
        reactions.finish_comment(target, last, reacted.get(thread["id"]), celebrate=done)

    skipped = len(threads) - len(plan)
    print(f"답글 {posted}건 · resolve {resolved}건 · 실패 {failed}건 · 건너뜀 {skipped}건")
    return 1 if failed else 0


def _pending_threads(target: Target, logins: list[str]) -> list[dict]:
    threads, after = [], None
    for _ in range(MAX_PAGES):
        data = gh.graphql(_THREADS_QUERY, {"owner": target.owner, "repo": target.repo, "num": target.number, "after": after})
        page = data["repository"]["pullRequest"]["reviewThreads"]
        threads += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    else:
        print(f"경고: 스레드가 {MAX_PAGES * 100}개를 넘어 일부만 봅니다.", file=sys.stderr)

    return [{**thread, "comments": thread["comments"]["nodes"]} for thread in threads if _keep(thread, logins)]


def _keep(thread: dict, logins: list[str]) -> bool:
    nodes = thread["comments"]["nodes"]
    if thread["isResolved"] or not nodes:
        return False
    first, last = (_login(nodes[0]), _login(nodes[-1]))
    # 루프 가드: 봇이 시작했고, 마지막 발화자가 봇이 아닌 스레드만.
    return first in logins and last not in logins


def _login(comment: dict) -> str | None:
    return (comment.get("author") or {}).get("login")


def _classify(context, threads: list[dict], directory: Path) -> list[dict]:
    file_cache: dict[str, str] = {}
    decisions: list[dict] = []
    for start in range(0, len(threads), BATCH):
        batch = threads[start : start + BATCH]
        blocks = [_thread_block(context, thread, file_cache) for thread in batch]
        text = "\n\n".join(
            [
                judge.prompt("reply-classify"),
                "---",
                f"## PR\n{context.target} — {context.title} @ {context.head_sha}",
                f"## PR head 체크아웃 경로\n{directory / 'tree'}",
                f"## 컨벤션\n{context.conventions or '(없음)'}",
                *blocks,
            ]
        )
        try:
            result = judge.ask("reply", text, "replies", tree=directory / "tree", sandbox=directory / "sandbox")
        except judge.JudgeError as error:
            print(f"경고: 답글 분류 실패, 이 묶음은 건너뜁니다 ({error})", file=sys.stderr)
            continue
        known = {thread["id"] for thread in batch}
        # threadId 를 모르는 응답은 추측하지 않고 버린다.
        decisions += [item for item in result["replies"] if item["threadId"] in known]
    return decisions


def _thread_block(context, thread: dict, cache: dict[str, str]) -> str:
    path = thread["path"]
    if path not in cache:
        cache[path] = _file_at_head(context, path)
    history = "\n\n".join(
        f"**{(c.get('author') or {}).get('login')}** ({c['createdAt']}):\n{strip_markers(c['body'])}"
        for c in thread["comments"]
    )
    return (
        f"## 스레드 {thread['id']}\n`{path}` line {thread['line']} (original {thread['originalLine']})\n\n"
        f"### 대화\n{history}\n\n### head 의 파일 내용\n```\n{cache[path]}\n```"
    )


def _file_at_head(context, path: str) -> str:
    try:
        data = gh.get(f"repos/{context.owner}/{context.repo}/contents/{path}?ref={context.head_sha}")
    except gh.GhError as error:
        if error.status == 404:
            return "(head 에서 삭제된 파일입니다)"
        raise
    return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")


def _write_plan(directory: Path, target: Target, threads: list[dict], plan: list[dict]) -> None:
    by_id = {thread["id"]: thread for thread in threads}
    lines = [f"# 답글 계획 — {target}", f"대상 스레드 {len(threads)} · 응답 {len(plan)}", ""]
    for item in plan:
        thread = by_id[item["threadId"]]
        lines += [
            f"## `{thread['path']}:{thread['line']}` — intent={item['intent']} resolve={item['should_resolve']}",
            "",
            item["reply_body"],
            "",
        ]
    (directory / "replies.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), "utf-8")
    (directory / "replies.md").write_text("\n".join(lines), "utf-8")
