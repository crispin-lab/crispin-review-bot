"""finding 지문. 모델이 아니라 코드가 계산한다 (모델은 해시를 정확히 못 낸다)."""

import hashlib
import re

MARKER_PATTERN = re.compile(r"<!--\s*pcr:([0-9a-f]{12})\s*-->")
REPLY_MARKER = "<!-- pcr:reply -->"


def _sha12(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def finding_fingerprint(path: str, line: int, body: str) -> str:
    return _sha12(f"{path.lower()}:{line}:{normalize(body)[:80]}")


def summary_fingerprint(pr_number: int, head_sha: str) -> str:
    return _sha12(f"summary:{pr_number}:{head_sha}")


def marker(fingerprint: str) -> str:
    return f"<!-- pcr:{fingerprint} -->"


def markers_in(text: str) -> set[str]:
    return set(MARKER_PATTERN.findall(text or ""))


def strip_markers(text: str) -> str:
    return MARKER_PATTERN.sub("", (text or "").replace(REPLY_MARKER, "")).strip()
