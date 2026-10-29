"""대상 PR 과 플래그 파싱. 로컬 스킬 인자와 PR 코멘트 명령(`/pcr ...`)이 같은 파서를 쓴다."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field

FOCUS_CATEGORIES = ("correctness", "security", "conventions", "reuse", "perf", "tests")

_SHORT = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<num>\d+)$")
_URL = re.compile(r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/pull/(?P<num>\d+)(?:[/?#].*)?$")

_BOOL_FLAGS = {
    "--dry-run": "dry_run",
    "--yes": "yes",
    "-y": "yes",
    "--force": "force",
    "--with-critic": "with_critic",
    "--auto-reply": "auto_reply",
    "--reply": "reply",
    "--help": "help",
    "-h": "help",
}
_REVIEW_ONLY = ("force", "with_critic", "auto_reply", "focus")


class ArgsError(ValueError):
    pass


@dataclass
class Target:
    owner: str
    repo: str
    number: int

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    def __str__(self) -> str:
        return f"{self.slug}#{self.number}"


@dataclass
class Options:
    target: Target | None = None
    dry_run: bool = False
    yes: bool = False
    force: bool = False
    with_critic: bool = False
    auto_reply: bool = False
    reply: bool = False
    help: bool = False
    focus: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def allowed_owner() -> str:
    return os.environ.get("PCR_ALLOWED_OWNER", "crispin-lab")


def parse_target(text: str) -> Target:
    match = _SHORT.match(text) or _URL.match(text)
    if not match:
        raise ArgsError(f"대상을 해석하지 못했습니다: {text!r} (owner/repo#번호 또는 PR URL)")
    target = Target(match["owner"], match["repo"], int(match["num"]))
    if target.owner != allowed_owner():
        raise ArgsError(f"{allowed_owner()} 조직의 PR 만 리뷰할 수 있습니다.")
    return target


def parse(tokens: list[str], *, default_target: Target | None = None) -> Options:
    options = Options(target=default_target)
    iterator = iter(tokens)
    for token in iterator:
        if token in _BOOL_FLAGS:
            setattr(options, _BOOL_FLAGS[token], True)
        elif token == "--focus" or token.startswith("--focus="):
            value = token.split("=", 1)[1] if "=" in token else next(iterator, "")
            options.focus = _parse_focus(value)
        elif token.startswith("-"):
            raise ArgsError(f"알 수 없는 플래그입니다: {token}")
        elif default_target is None and options.target is None:
            options.target = parse_target(token)
        else:
            raise ArgsError(f"해석할 수 없는 인자입니다: {token}")
    if options.help:
        return options
    if options.target is None:
        raise ArgsError("리뷰할 PR 을 지정해 주세요 (owner/repo#번호 또는 PR URL).")
    if options.reply:
        ignored = [name for name in _REVIEW_ONLY if getattr(options, name)]
        if ignored:
            options.warnings.append(f"--reply 에서는 무시됩니다: {', '.join(ignored)}")
    return options


def parse_command(body: str, target: Target) -> Options | None:
    """PR 코멘트 첫 줄이 정확히 `/pcr` 로 시작할 때만 명령으로 본다."""
    first_line = (body or "").strip().splitlines()[0] if (body or "").strip() else ""
    if first_line != "/pcr" and not first_line.startswith("/pcr "):
        return None
    try:
        tokens = shlex.split(first_line)[1:]
    except ValueError as error:
        raise ArgsError(f"명령을 해석하지 못했습니다: {error}") from error
    return parse(tokens, default_target=target)


def _parse_focus(value: str) -> list[str]:
    categories = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [item for item in categories if item not in FOCUS_CATEGORIES]
    if not categories or unknown:
        raise ArgsError(f"--focus 는 {', '.join(FOCUS_CATEGORIES)} 중에서 골라 주세요.")
    return categories
