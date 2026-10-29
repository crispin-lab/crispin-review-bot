"""PR 컨텍스트 수집: 메타데이터 · diff · 연결 이슈 · head 체크아웃 · 컨벤션 · 기존 봇 지문."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import gh
from .fingerprint import markers_in, strip_markers
from .target import Target

_LINKED_ISSUE = re.compile(r"(?:fixes|closes|resolves|refs)\s+#(\d+)", re.IGNORECASE)
_IMPORT = re.compile(r"^@(\S+\.md)\s*$", re.MULTILINE)
MAX_LINKED_ISSUES = 5
BIG_PR_FILES = 50
BIG_PR_CHANGES = 2000


@dataclass
class Context:
    owner: str
    repo: str
    number: int
    title: str
    body: str
    author: str
    head_sha: str
    base_ref: str
    head_ref: str
    state: str
    draft: bool
    additions: int
    deletions: int
    changed_files: int
    files: list[dict]
    linked_issues: list[dict]
    bot_logins: list[str]
    prior_fingerprints: list[str]
    prior_findings: list[str]
    conventions: str
    convention_files: list[str]
    conventions_from: str = "head"
    conventions_sha: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def target(self) -> Target:
        return Target(self.owner, self.repo, self.number)

    @property
    def is_big(self) -> bool:
        return self.changed_files > BIG_PR_FILES or self.additions + self.deletions > BIG_PR_CHANGES


def work_dir(target: Target) -> Path:
    root = os.environ.get("PCR_WORK_DIR") or os.path.join(
        os.environ.get("RUNNER_TEMP") or os.path.expanduser("~/.cache"), "pcr"
    )
    path = Path(root) / f"{target.owner}__{target.repo}__{target.number}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bot_logins() -> list[str]:
    """현재 토큰의 계정 + 전환 기간에 함께 인정할 이전 봇 계정 (`PCR_LEGACY_BOT_LOGINS`)."""
    logins = [gh.login()]
    legacy = os.environ.get("PCR_LEGACY_BOT_LOGINS", "")
    logins += [item.strip() for item in legacy.split(",") if item.strip() and item.strip() not in logins]
    return logins


def collect(target: Target, *, with_prior: bool = True) -> tuple[Context, str]:
    try:
        pr = gh.get(f"repos/{target.slug}/pulls/{target.number}")
    except gh.GhError as error:
        if error.status == 404:
            # private 레포는 권한이 없어도 403 이 아니라 404 를 준다.
            raise gh.GhError(
                f"{target} 을 읽지 못했습니다 (404). PR 이 없거나 봇 토큰이 이 레포에 접근하지 못합니다 — "
                "PAT 의 레포 선택 · org 승인 대기 · 봇 계정의 레포 권한을 확인해 주세요.",
                404,
            ) from error
        raise
    files = gh.get_paginated(f"repos/{target.slug}/pulls/{target.number}/files?per_page=100")
    patch = gh.get_raw(f"repos/{target.slug}/pulls/{target.number}", accept="application/vnd.github.diff")
    head_sha = pr["head"]["sha"]

    logins = bot_logins()
    tree = checkout(target, head_sha)
    # fork PR 은 작성자가 head 의 .claude/ 룰을 고쳐 지적을 피해 갈 수 있다 → base 의 룰로 본다.
    head_repo = (pr["head"].get("repo") or {}).get("full_name")
    from_fork = head_repo != target.slug
    rules_tree = checkout(target, pr["base"]["sha"], name="base-tree") if from_fork else tree
    conventions, convention_files = load_conventions(rules_tree)
    prior_fps, prior_bodies = (_prior_bot_findings(target, logins) if with_prior else ([], []))

    context = Context(
        owner=target.owner,
        repo=target.repo,
        number=target.number,
        title=pr.get("title") or "",
        body=pr.get("body") or "",
        author=(pr.get("user") or {}).get("login", ""),
        head_sha=head_sha,
        base_ref=pr["base"]["ref"],
        head_ref=pr["head"]["ref"],
        state="merged" if pr.get("merged") else pr.get("state", ""),
        draft=bool(pr.get("draft")),
        additions=pr.get("additions", 0),
        deletions=pr.get("deletions", 0),
        changed_files=pr.get("changed_files", 0),
        files=[{"path": f["filename"], "status": f["status"], "changes": f.get("changes", 0)} for f in files],
        linked_issues=_linked_issues(target, pr.get("body") or ""),
        bot_logins=logins,
        prior_fingerprints=sorted(prior_fps),
        prior_findings=prior_bodies,
        conventions=conventions,
        convention_files=convention_files,
        conventions_from="base" if from_fork else "head",
        conventions_sha=pr["base"]["sha"] if from_fork else head_sha,
    )
    return context, patch


def checkout(target: Target, sha: str, *, name: str = "tree") -> Path:
    """SHA 를 얕게 받아 둔다. 컨벤션은 로컬 체크아웃이 아니라 PR 의 커밋 기준이어야 한다."""
    tree = work_dir(target) / name
    if (tree / ".git").exists() and _git(tree, "rev-parse", "HEAD").strip() == sha:
        return tree
    tree.mkdir(parents=True, exist_ok=True)
    if not (tree / ".git").exists():
        _git(tree, "init", "--quiet")
    _git(tree, "fetch", "--quiet", "--depth", "1", "--no-tags", f"https://github.com/{target.slug}", sha)
    _git(tree, "checkout", "--quiet", "--force", "--detach", "FETCH_HEAD")
    return tree


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=gh.git_auth_env(), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise gh.GhError(f"git {args[0]} 실패: {result.stderr.strip()}")
    return result.stdout


def load_conventions(tree: Path) -> tuple[str, list[str]]:
    claude_md = tree / ".claude" / "CLAUDE.md"
    if not claude_md.is_file():
        return "", []
    sections = [f"### .claude/CLAUDE.md\n\n{claude_md.read_text(encoding='utf-8')}"]
    loaded = [".claude/CLAUDE.md"]
    for relative in _IMPORT.findall(claude_md.read_text(encoding="utf-8")):
        path = (claude_md.parent / relative).resolve()
        if not path.is_relative_to(tree.resolve()) or not path.is_file():
            continue
        name = str(path.relative_to(tree.resolve()))
        sections.append(f"### {name}\n\n{path.read_text(encoding='utf-8')}")
        loaded.append(name)
    return "\n\n".join(sections), loaded


def _linked_issues(target: Target, body: str) -> list[dict]:
    issues = []
    for number in list(dict.fromkeys(_LINKED_ISSUE.findall(body)))[:MAX_LINKED_ISSUES]:
        try:
            issue = gh.get(f"repos/{target.slug}/issues/{number}")
        except gh.GhError:
            continue
        issues.append({"number": int(number), "title": issue.get("title", ""), "body": issue.get("body") or ""})
    return issues


def _prior_bot_findings(target: Target, logins: list[str]) -> tuple[set[str], list[str]]:
    comments = gh.get_paginated(f"repos/{target.slug}/pulls/{target.number}/comments?per_page=100")
    reviews = gh.get_paginated(f"repos/{target.slug}/pulls/{target.number}/reviews?per_page=100")
    fingerprints: set[str] = set()
    bodies: list[str] = []
    for item in comments:
        if (item.get("user") or {}).get("login") in logins:
            fingerprints |= markers_in(item.get("body", ""))
            bodies.append(f"{item.get('path')}:{item.get('line') or item.get('original_line')} — "
                          f"{strip_markers(item.get('body', ''))[:300]}")
    for item in reviews:
        if (item.get("user") or {}).get("login") in logins:
            fingerprints |= markers_in(item.get("body", ""))
    return fingerprints, bodies


def bot_reviews(target: Target, logins: list[str]) -> list[dict]:
    reviews = gh.get_paginated(f"repos/{target.slug}/pulls/{target.number}/reviews?per_page=100")
    return [item for item in reviews if (item.get("user") or {}).get("login") in logins]


def save(context: Context, patch: str) -> Path:
    directory = work_dir(context.target)
    (directory / "context.json").write_text(json.dumps(asdict(context), ensure_ascii=False, indent=2), "utf-8")
    (directory / "diff.patch").write_text(patch, "utf-8")
    return directory


def load(target: Target) -> tuple[Context, str]:
    directory = work_dir(target)
    data = json.loads((directory / "context.json").read_text("utf-8"))
    return Context(**data), (directory / "diff.patch").read_text("utf-8")
