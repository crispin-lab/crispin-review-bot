"""게시 직전 본문 검사.

리뷰 · 답글 본문 어디에도 생성 도구 표기(footer, co-author, 생성 도구 언급)가
남지 않게 한다. 1차로 그런 줄을 지우고, 지운 뒤에도 남아 있으면 게시를 거부한다.
"""

from __future__ import annotations

import re

# 줄 단위로 통째로 지우는 패턴. footer 형태로 붙는 표기가 대상이다.
_STRIP_LINE_PATTERNS = [
    re.compile(r"^\s*[_*>]*\s*generated\s+(by|with)\b", re.IGNORECASE),
    re.compile(r"^\s*co-authored-by\s*:", re.IGNORECASE),
    re.compile(r"claude\.ai/code", re.IGNORECASE),
    re.compile(r"claude\.com/claude-code", re.IGNORECASE),
    re.compile("\N{ROBOT FACE}"),
]

# 지운 뒤에도 남아 있으면 게시를 막는 패턴.
_FORBIDDEN_PATTERNS = [
    re.compile(r"generated\s+(by|with)\s+\[?(claude|ai|copilot|chatgpt|gpt|llm)", re.IGNORECASE),
    re.compile(r"co-authored-by", re.IGNORECASE),
    re.compile(r"claude\.ai/code", re.IGNORECASE),
    re.compile("\N{ROBOT FACE}"),
    re.compile(r"\b(AI|LLM)[- ]?(generated|assisted|written)\b", re.IGNORECASE),
    re.compile(
        r"(AI|인공지능|LLM|클로드|claude|봇)\s*(가|이|로|으로|를 통해|에 의해)?\s*"
        r"(자동\s*)?(생성|작성)(된|한|했|함|됨|하였|되었)",
        re.IGNORECASE,
    ),
    re.compile(r"생성\s*도구"),
]


# 비밀값처럼 보이는 문자열. 판단 단계가 속아 비밀값을 본문에 실어도 공개 레포에 올라가지 않게 한다.
_SECRET_PATTERNS = [
    re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


class AttributionError(ValueError):
    pass


class SecretLeakError(ValueError):
    pass


def sanitize(body: str) -> str:
    lines = [line for line in body.splitlines() if not _is_attribution_line(line)]
    cleaned = "\n".join(_drop_dangling_rule(lines)).rstrip() + "\n"
    for pattern in _SECRET_PATTERNS:
        if pattern.search(cleaned):
            raise SecretLeakError("게시 본문에 비밀값으로 보이는 문자열이 있어 게시하지 않습니다.")
    for pattern in _FORBIDDEN_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            raise AttributionError(f"게시 본문에 생성 도구 표기가 남아 있습니다: {match.group(0)!r}")
    return cleaned


def _is_attribution_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in _STRIP_LINE_PATTERNS)


def _drop_dangling_rule(lines: list[str]) -> list[str]:
    # footer 를 지우고 나면 그 위의 구분선(`---`)만 덩그러니 남는다.
    trimmed = list(lines)
    while trimmed and trimmed[-1].strip() in ("", "---", "***", "___"):
        trimmed.pop()
    return trimmed
