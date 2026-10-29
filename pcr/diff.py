"""unified diff 에서 인라인 코멘트를 달 수 있는 줄(RIGHT side)을 뽑는다."""

import re

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# 리뷰 대상에서 빼는 산출물.
_GENERATED = re.compile(
    r"(^|/)(pnpm-lock\.yaml|package-lock\.json|yarn\.lock|uv\.lock|poetry\.lock|gradle\.lockfile)$"
    r"|\.snap$|(^|/)(build|dist|out|\.next)/|\.min\.(js|css)$"
    r"|(^|/)src/lib/api/schema\.[^/]+\.d\.ts$"
)


def commentable_lines(patch: str) -> dict[str, set[int]]:
    """파일 경로 → 새 파일 기준으로 코멘트 가능한 줄 번호 (추가 줄 + hunk 안 문맥 줄)."""
    result: dict[str, set[int]] = {}
    path = None
    new_line = 0
    in_hunk = False
    for raw in patch.splitlines():
        if raw.startswith("diff --git "):
            path, in_hunk = None, False
        elif raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else target.removeprefix("b/")
            if path:
                result.setdefault(path, set())
        elif raw.startswith("@@"):
            match = _HUNK.match(raw)
            if match and path:
                new_line, in_hunk = int(match.group(1)), True
        elif in_hunk and path:
            if raw.startswith("+"):
                result[path].add(new_line)
                new_line += 1
            elif raw.startswith(" "):
                result[path].add(new_line)
                new_line += 1
            elif raw.startswith("-") or raw.startswith("\\"):
                continue
            else:
                in_hunk = False
    return result


def is_generated(path: str) -> bool:
    return bool(_GENERATED.search(path))
