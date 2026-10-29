"""`gh api` 래퍼.

- 인증은 `GH_TOKEN` 하나로 받는다 (로컬은 봇 gh config 의 토큰, CI 는 봇 PAT).
- 본문은 항상 `--input <file>` 로 보낸다. `-f body=...` 로 넘기면 한국어·백틱·`$`·줄바꿈이
  깨진다 (PR #52, #53).
- POST 성공 여부는 `gh` 의 exit code 로만 판단한다. 응답은 파일로 받아 따로 파싱한다.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path


class GhError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _run(args: list[str], *, input_path: Path | None = None) -> str:
    command = ["gh", *args]
    if input_path is not None:
        command += ["--input", str(input_path)]
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        code = subprocess.call(command, stdout=out, stderr=err, env=_env())
        out.seek(0)
        err.seek(0)
        stdout = out.read().decode("utf-8")
        stderr = err.read().decode("utf-8", errors="replace")
    if code != 0:
        raise GhError(f"gh {' '.join(args[:3])} 실패: {stderr.strip() or stdout.strip()}", _status_of(stderr))
    return stdout


def _env() -> dict[str, str]:
    env = dict(os.environ)
    if not env.get("GH_TOKEN"):
        raise GhError("GH_TOKEN 이 설정되어 있지 않습니다.")
    env.setdefault("GH_PROMPT_DISABLED", "1")
    return env


def _status_of(stderr: str) -> int | None:
    for token in stderr.replace("(", " ").replace(")", " ").split():
        if token.startswith("HTTP"):
            digits = token.removeprefix("HTTP").strip(":")
            if digits.isdigit():
                return int(digits)
    return None


def get(path: str, *, accept: str | None = None) -> object:
    args = ["api", path]
    if accept:
        args += ["-H", f"Accept: {accept}"]
    return json.loads(_run(args) or "null")


def get_raw(path: str, *, accept: str) -> str:
    return _run(["api", path, "-H", f"Accept: {accept}"])


def get_paginated(path: str) -> list:
    pages = json.loads(_run(["api", path, "--paginate", "--slurp"]) or "[]")
    return [item for page in pages for item in page]


def send(method: str, path: str, payload: dict | None = None) -> object:
    args = ["api", "--method", method, path, "-H", "Accept: application/vnd.github+json"]
    if payload is None:
        return json.loads(_run(args) or "null")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        input_path = Path(handle.name)
    try:
        return json.loads(_run(args, input_path=input_path) or "null")
    finally:
        input_path.unlink(missing_ok=True)


def graphql(query: str, variables: dict) -> dict:
    payload = {"query": query, "variables": variables}
    data = send("POST", "graphql", payload)
    if not isinstance(data, dict) or data.get("errors"):
        raise GhError(f"GraphQL 오류: {json.dumps(data, ensure_ascii=False)[:500]}")
    return data["data"]


def login() -> str:
    data = get("user")
    if not isinstance(data, dict) or not data.get("login"):
        raise GhError("봇 계정 정보를 가져오지 못했습니다. GH_TOKEN 을 확인해 주세요.")
    return data["login"]


def git_auth_env() -> dict[str, str]:
    """토큰을 URL · .git/config · 프로세스 인자에 남기지 않고 git 에 넘긴다."""
    import base64

    token = _env()["GH_TOKEN"]
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env
