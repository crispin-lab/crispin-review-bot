"""리뷰 모드: 수집 → 판단(+비평) → 계획 → 게시."""

import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import context as ctx_module
from . import gh, judge, reactions
from .context import Context
from .diff import commentable_lines, is_generated
from .fingerprint import finding_fingerprint, marker, strip_markers, summary_fingerprint
from .sanitize import sanitize
from .target import Options, Target

RATE_LIMIT = timedelta(minutes=10)
EXIT_RATE_LIMITED = 3
UNPLACED = "<!-- pcr-unplaced -->"


@dataclass
class Finding:
    path: str
    line: int
    category: str
    body: str
    rule_ref: str | None
    fingerprint: str

    def comment_body(self) -> str:
        reference = f"\n\n근거: {self.rule_ref}" if self.rule_ref and self.rule_ref not in self.body else ""
        return f"{self.body.strip()}{reference}\n\n{marker(self.fingerprint)}"


def run(options: Options) -> int:
    target = options.target
    context, patch = ctx_module.collect(target)
    _warn_state(context)

    limited = _rate_limited(context, force=options.force)
    if limited:
        print(limited)
        return EXIT_RATE_LIMITED

    directory = ctx_module.save(context, patch)
    _start_reaction(target, directory)

    raw = judge.ask(
        "review",
        _review_input(context, patch, options.focus),
        "findings",
        tree=directory / "tree",
        sandbox=directory / "sandbox",
    )
    findings = _normalize(raw["findings"], context, focus=options.focus)
    inline, unplaced = _place(findings, patch)
    critic_note = None
    if options.with_critic and (inline or unplaced):
        inline, unplaced, critic_note = _critic(context, patch, inline, unplaced, directory)

    plan = _plan(context, raw, inline, unplaced, critic_note)
    _write_plan(directory, plan)
    if options.dry_run:
        _publish_dry_run(directory)
        return 0
    return post(target)


def post(target: Target) -> int:
    directory = ctx_module.work_dir(target)
    plan_path = directory / "plan.json"
    if not plan_path.exists():
        print("게시할 계획이 없습니다. 먼저 리뷰를 실행해 주세요.", file=sys.stderr)
        return 1
    plan = json.loads(plan_path.read_text("utf-8"))
    current = gh.get(f"repos/{target.slug}/pulls/{target.number}")["head"]["sha"]
    if current != plan["head_sha"]:
        print("계획을 만든 뒤 PR head 가 바뀌었습니다. 리뷰를 다시 실행해 주세요.", file=sys.stderr)
        return 1

    review = _adopt_existing(target, plan) or _submit(target, plan)
    state = reactions.load_state(directory)
    reactions.finish_issue(target, state.get("reaction_id"))
    print(f"리뷰 게시: {review.get('html_url')} (인라인 {len(plan['comments'])}건)")
    return 0


def _submit(target: Target, plan: dict) -> dict:
    payload = {
        "commit_id": plan["head_sha"],
        "body": sanitize(plan["body"]),
        "event": "COMMENT",
        "comments": [{**comment, "body": sanitize(comment["body"])} for comment in plan["comments"]],
    }
    try:
        return gh.send("POST", f"repos/{target.slug}/pulls/{target.number}/reviews", payload)
    except gh.GhError as error:
        landed = _adopt_existing(target, plan)
        if landed:
            return landed
        if error.status != 422 or not plan["comments"]:
            raise
    # 인라인 위치가 거부되면 버리지 않고 요약 본문으로 옮겨 한 번만 다시 보낸다.
    moved = "\n".join(f"- `{c['path']}:{c['line']}` — {strip_markers(c['body'])}" for c in plan["comments"])
    header = "" if "## Risks" in plan["body"] else "## Risks\n"
    payload["body"] = sanitize(plan["body"].replace(UNPLACED, f"{header}{moved}\n{UNPLACED}"))
    payload["comments"] = []
    return gh.send("POST", f"repos/{target.slug}/pulls/{target.number}/reviews", payload)


def _adopt_existing(target: Target, plan: dict) -> dict | None:
    """리뷰 API 는 멱등이 아니고 제출된 리뷰는 지울 수 없다. 재시도 전에 이미 들어갔는지 본다."""
    run_marker = f"<!-- pcr-run:{plan['run_id']} -->"
    for review in ctx_module.bot_reviews(target, plan["bot_logins"]):
        if run_marker in (review.get("body") or ""):
            return review
    return None


def _warn_state(context: Context) -> None:
    if context.state != "open" or context.draft:
        label = "draft" if context.draft else context.state
        print(f"경고: PR 이 {label} 상태입니다. 그대로 진행합니다.", file=sys.stderr)
    if context.is_big:
        print(
            f"경고: 큰 PR 입니다 ({context.changed_files}개 파일, +{context.additions}/-{context.deletions}). "
            "전체를 리뷰합니다.",
            file=sys.stderr,
        )


def _rate_limited(context: Context, *, force: bool) -> str | None:
    if force:
        return None
    summary_marker = marker(summary_fingerprint(context.number, context.head_sha))
    now = datetime.now(timezone.utc)
    for review in ctx_module.bot_reviews(context.target, context.bot_logins):
        if summary_marker not in (review.get("body") or ""):
            continue
        submitted = datetime.fromisoformat(review["submitted_at"].replace("Z", "+00:00"))
        if now - submitted < RATE_LIMIT:
            remaining = int((RATE_LIMIT - (now - submitted)).total_seconds() // 60) + 1
            return (
                f"{context.target} @ {context.head_sha[:7]} 은 {submitted:%H:%M}Z 에 이미 리뷰했습니다. "
                f"--force 를 쓰거나 {remaining}분 뒤에 다시 실행해 주세요."
            )
    return None


def _start_reaction(target: Target, directory: Path) -> None:
    state = reactions.load_state(directory)
    if not state.get("reaction_id"):
        state["reaction_id"] = reactions.start_issue(target)
        reactions.save_state(directory, state)


def _review_input(context: Context, patch: str, focus: list[str]) -> str:
    issues = "\n\n".join(f"#{i['number']} {i['title']}\n{i['body']}" for i in context.linked_issues) or "(없음)"
    prior = "\n".join(f"- {item}" for item in context.prior_findings) or "(없음)"
    return "\n\n".join(
        [
            judge.prompt("review"),
            "---",
            f"## PR\n{context.target} — {context.title}\nbase `{context.base_ref}` ← head `{context.head_ref}` "
            f"@ {context.head_sha}\n작성자: {context.author}\n\n{context.body or '(본문 없음)'}",
            f"## 연결 이슈\n{issues}",
            f"## --focus\n{', '.join(focus) if focus else '(전체)'}",
            f"## PR head 체크아웃 경로\n{ctx_module.work_dir(context.target) / 'tree'}",
            f"## 컨벤션\n{context.conventions or '(대상 레포에 .claude/CLAUDE.md 가 없습니다)'}",
            f"## 이전 봇 finding\n{prior}",
            f"## diff\n```diff\n{patch}\n```",
        ]
    )


def _normalize(raw: list[dict], context: Context, *, focus: list[str]) -> list[Finding]:
    seen = set(context.prior_fingerprints)
    findings: list[Finding] = []
    for item in raw:
        if is_generated(item["path"]) or (focus and item["category"] not in focus):
            continue
        fingerprint = finding_fingerprint(item["path"], item["line"], item["body"])
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        findings.append(
            Finding(item["path"], item["line"], item["category"], item["body"], item.get("rule_ref"), fingerprint)
        )
    return findings


def _place(findings: list[Finding], patch: str) -> tuple[list[Finding], list[Finding]]:
    lines = commentable_lines(patch)
    inline = [f for f in findings if f.line in lines.get(f.path, set())]
    unplaced = [f for f in findings if f not in inline]
    return inline, unplaced


def _critic(context: Context, patch: str, inline: list[Finding], unplaced: list[Finding], directory: Path):
    candidates = inline + unplaced
    payload = [
        {"fingerprint": f.fingerprint, "path": f.path, "line": f.line, "category": f.category, "body": f.body}
        for f in candidates
    ]
    text = "\n\n".join(
        [
            judge.prompt("critic"),
            "---",
            f"## PR\n{context.target} — {context.title}\n\n{context.body or '(본문 없음)'}",
            f"## PR head 체크아웃 경로\n{directory / 'tree'}",
            f"## 컨벤션\n{context.conventions or '(없음)'}",
            f"## diff\n```diff\n{patch}\n```",
            f"## findings\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```",
        ]
    )
    try:
        verdicts = judge.ask("critic", text, "verdicts", tree=directory / "tree", sandbox=directory / "sandbox")
    except judge.JudgeError as error:
        print(f"경고: 비평 단계 실패, finding 을 모두 유지합니다 ({error})", file=sys.stderr)
        return inline, unplaced, "Critic: parse failed, all findings kept."

    dropped = {
        v["fingerprint"]: v["reason"]
        for v in verdicts["verdicts"]
        if v["keep"] is False and v["fingerprint"] in {f.fingerprint for f in candidates}
    }
    kept_count = len(candidates) - len(dropped)
    lines = [f"Critic: kept {kept_count} / dropped {len(dropped)}."]
    lines += [f"  - {fp[:8]} {_where(candidates, fp)} — {reason[:80]}" for fp, reason in dropped.items()]
    if kept_count == 0 and dropped:
        # 비평이 전부 버렸을 때 빈 리뷰를 조용히 게시하지 않는다 — 전부 다시 포함한다.
        lines.append("  (비평이 모든 finding 을 버려 전부 다시 포함했습니다.)")
        return inline, unplaced, "\n".join(lines)
    keep = lambda f: f.fingerprint not in dropped  # noqa: E731
    return [f for f in inline if keep(f)], [f for f in unplaced if keep(f)], "\n".join(lines)


def _where(findings: list[Finding], fingerprint: str) -> str:
    finding = next(f for f in findings if f.fingerprint == fingerprint)
    return f"{finding.path}:{finding.line}"


def _plan(context: Context, raw: dict, inline: list[Finding], unplaced: list[Finding], critic_note: str | None) -> dict:
    run_id = uuid.uuid4().hex[:12]
    body = _summary(context, raw, inline, unplaced, critic_note, run_id)
    comments = [
        {"path": f.path, "line": f.line, "side": "RIGHT", "body": sanitize(f.comment_body())} for f in inline
    ]
    return {
        "run_id": run_id,
        "target": str(context.target),
        "head_sha": context.head_sha,
        "bot_logins": context.bot_logins,
        "body": sanitize(body),
        "comments": comments,
        "stats": {
            "inline": len(inline),
            "unplaced": len(unplaced),
            "by_category": _count_by_category(inline + unplaced),
            "prior": len(context.prior_fingerprints),
        },
    }


def _summary(context, raw, inline, unplaced, critic_note, run_id) -> str:
    new_count = len(inline) + len(unplaced)
    prior = len(context.prior_fingerprints)
    sections = [f"## Scope\n{context.changed_files} files, +{context.additions}/-{context.deletions}. {raw['scope'].strip()}"]

    risks = [f"- {risk.strip()}" for risk in raw["risks"] if risk.strip()] if new_count else []
    risks += [f"- `{f.path}:{f.line}` — {f.body.strip()}" for f in unplaced]
    # 게시 시 인라인 위치가 거부되면 그 코멘트를 이 자리(Risks)로 옮긴다.
    sections.append(("## Risks\n" + "\n".join(risks) + "\n" if risks else "") + UNPLACED)
    themes = [f"- {theme.strip()}" for theme in raw["themes"] if theme.strip()]
    if themes:
        sections.append("## Themes\n" + "\n".join(themes))

    if context.convention_files:
        conventions = f"{len(context.convention_files)} rule files loaded from PR head @ {context.head_sha[:7]}."
    else:
        conventions = "none loaded (.claude/CLAUDE.md 없음)."
    sections.append(f"## Conventions\n{conventions}")

    if new_count == 0:
        dedup = f"새로운 지적 사항이 없습니다. 이전 지적 {prior}건은 그대로 유효합니다." if prior else "새로운 지적 사항이 없습니다."
    elif prior:
        dedup = f"이전 지적 {prior}건은 그대로 유효하고, 이번에 {new_count}건을 새로 남깁니다."
    else:
        dedup = f"이전 지적 없음. 이번에 {new_count}건을 남깁니다."
    if critic_note:
        dedup += "\n" + critic_note
    sections.append(f"## Dedup\n{dedup}")

    sections.append(marker(summary_fingerprint(context.number, context.head_sha)) + f"\n<!-- pcr-run:{run_id} -->")
    return "\n\n".join(sections)


def _count_by_category(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.category] = counts.get(finding.category, 0) + 1
    return counts


def _write_plan(directory: Path, plan: dict) -> None:
    (directory / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), "utf-8")
    lines = [
        f"# 리뷰 계획 — {plan['target']} @ {plan['head_sha'][:7]}",
        f"게시 계정: {plan['bot_logins'][0]}",
        f"분류: {json.dumps(plan['stats']['by_category'], ensure_ascii=False)} · 인라인 {plan['stats']['inline']} · "
        f"요약으로 옮김 {plan['stats']['unplaced']} · 이전 지적 {plan['stats']['prior']}",
        "",
        "## 요약 본문",
        "",
        plan["body"],
        "",
        "## 인라인 코멘트",
    ]
    for comment in plan["comments"]:
        lines += ["", f"### `{comment['path']}:{comment['line']}`", "", comment["body"]]
    (directory / "plan.md").write_text("\n".join(lines) + "\n", "utf-8")


def _publish_dry_run(directory: Path) -> None:
    plan_md = (directory / "plan.md").read_text("utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(plan_md)
    print(f"dry-run: 게시하지 않았습니다. 계획: {directory / 'plan.md'}")
