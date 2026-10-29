"""진입점.

    pcr <target> [flags]     리뷰 (또는 --reply 로 답글 모드)
    pcr post <target>        dry-run 으로 만든 계획을 그대로 게시
    pcr ci                   GitHub Actions 이벤트를 읽어 알맞은 모드로 실행
"""

import sys

from . import ci, judge, review
from .gh import GhError
from .judge import JudgeError
from .sanitize import AttributionError
from .target import ArgsError, parse, parse_target

HELP_PATH = judge.ROOT / "skill" / "HELP.ko.md"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return _dispatch(argv)
    except (ArgsError, GhError, JudgeError, AttributionError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2


def _dispatch(argv: list[str]) -> int:
    if not argv:
        print(HELP_PATH.read_text("utf-8"))
        return 2
    command = argv[0]
    if command == "ci":
        return ci.run()
    if command == "post":
        return review.post(parse_target(_single(argv)))
    options = parse(argv)
    if options.help:
        print(HELP_PATH.read_text("utf-8"))
        return 0
    return run(options)


def run(options) -> int:
    from . import reply

    if options.reply:
        return reply.run(options)
    code = review.run(options)
    if code == 0 and options.auto_reply and not options.dry_run:
        options.reply = True
        return reply.run(options)
    return code


def _single(argv: list[str]) -> str:
    if len(argv) != 2:
        raise ArgsError(f"사용법: pcr {argv[0]} owner/repo#번호")
    return argv[1]
