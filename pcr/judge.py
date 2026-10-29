"""판단 단계: Claude Code CLI(`claude -p`)를 읽기 전용으로 띄워 JSON 만 받는다.

- 로컬은 사용자의 Claude Code 로그인, CI 는 Workload Identity Federation 환경 변수로 인증된다.
- PR head 체크아웃은 `--add-dir` 로만 열고 작업 디렉토리는 빈 디렉토리다. head 의
  `.claude/settings.json` (hooks 등) 이 실행되지 않게 project 설정은 읽지 않는다.
- 읽기 도구를 `--allowedTools` 로 허용하지 않는다. 넓게 허용하면 체크아웃 밖(`/proc/self/environ`,
  OIDC 토큰 파일 등)까지 읽혀, PR 에 심은 지시로 비밀값이 리뷰 본문에 실려 공개될 수 있다.
  허용 목록이 없으면 작업 디렉토리 · `--add-dir` 안에서만 읽고 나머지는 거부된다.
- 쓰기 · 셸 · 웹 도구는 막는다. GitHub 게시는 이 단계가 아니라 코드가 한다.
- 자식 프로세스 환경에서 GitHub 토큰 · OIDC 요청 자격을 지운다.
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DENIED_TOOLS = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"]
_SCRUBBED_ENV = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_RUNTIME_TOKEN",
)


class JudgeError(RuntimeError):
    pass


def prompt(name: str) -> str:
    return (ROOT / "prompts" / f"{name}.md").read_text("utf-8")


def schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text("utf-8"))


def model_for(stage: str) -> str:
    default = "claude-sonnet-5-5" if stage == "critic" else "claude-opus-5-5"
    return os.environ.get(f"PCR_MODEL_{stage.upper()}") or os.environ.get("PCR_MODEL") or default


def ask(stage: str, text: str, schema_name: str, *, tree: Path, sandbox: Path) -> dict:
    sandbox.mkdir(parents=True, exist_ok=True)
    target_schema = schema(schema_name)
    command = [
        os.environ.get("PCR_CLAUDE_BIN", "claude"),
        "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(target_schema, ensure_ascii=False),
        "--model", model_for(stage),
        "--setting-sources", "user",
        "--strict-mcp-config",
        "--no-session-persistence",
    ]
    if os.environ.get("PCR_MAX_BUDGET_USD"):
        command += ["--max-budget-usd", os.environ["PCR_MAX_BUDGET_USD"]]
    command += ["--add-dir", str(tree), "--disallowedTools", *_DENIED_TOOLS]

    env = {key: value for key, value in os.environ.items() if key not in _SCRUBBED_ENV}
    result = subprocess.run(command, input=text, cwd=sandbox, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise JudgeError(f"{stage} 단계 claude 실행 실패: {(result.stderr or result.stdout).strip()[:500]}")
    payload = _extract(result.stdout)
    errors = validate(payload, target_schema)
    if errors:
        raise JudgeError(f"{stage} 단계 출력이 스키마와 맞지 않습니다: {'; '.join(errors[:5])}")
    return payload


def _extract(stdout: str) -> dict:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise JudgeError(f"claude 출력을 해석하지 못했습니다: {error}") from error
    if envelope.get("is_error"):
        raise JudgeError(f"claude 가 오류로 종료했습니다: {str(envelope.get('result'))[:500]}")
    if isinstance(envelope.get("structured_output"), dict):
        return envelope["structured_output"]
    text = str(envelope.get("result") or "").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise JudgeError("claude 가 JSON 을 반환하지 않았습니다.") from error


def validate(value: object, spec: dict, path: str = "$") -> list[str]:
    """스키마의 부분집합(type · properties · required · items · enum · maxLength)만 검사한다."""
    errors: list[str] = []
    expected = spec.get("type")
    checks = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    types = expected if isinstance(expected, list) else [expected] if expected else []
    if types and not any(checks[t](value) for t in types):
        return [f"{path}: {'/'.join(types)} 이어야 합니다"]
    if "enum" in spec and value not in spec["enum"]:
        errors.append(f"{path}: {spec['enum']} 중 하나여야 합니다")
    if isinstance(value, str) and "maxLength" in spec and len(value) > spec["maxLength"]:
        errors.append(f"{path}: {spec['maxLength']}자를 넘습니다")
    if isinstance(value, dict):
        for key in spec.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: 누락")
        for key, child in spec.get("properties", {}).items():
            if key in value:
                errors += validate(value[key], child, f"{path}.{key}")
    if isinstance(value, list) and "items" in spec:
        for index, item in enumerate(value):
            errors += validate(item, spec["items"], f"{path}[{index}]")
    return errors
