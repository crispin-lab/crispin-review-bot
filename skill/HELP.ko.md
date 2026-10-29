**pr-code-review** — crispin-lab 조직 PR 리뷰 / 답글 자동화

## 사용법

```
로컬:  /pr-code-review <target> [flags]
PR:    /pcr [flags]                (PR 대화 탭 코멘트, 첫 줄)
```

`<target>` 은 `owner/repo#번호` 또는 PR URL. `owner` 는 `crispin-lab` 이어야 합니다. PR 코멘트에서는 생략합니다.

## 두 가지 모드

**리뷰 (기본)** — PR head 기준 `.claude/` 룰로 diff 를 리뷰하고 인라인 + 요약을 리뷰 하나로 게시합니다.
이전 봇 지적과 지문이 같으면 다시 달지 않습니다. 시작 시 👀, 게시 후 🎉.

**답글 (`--reply`)** — 봇이 시작했고 마지막 답글이 봇이 아닌 미해결 스레드에 응답합니다.
"수정했다" 는 답글은 head 에서 실제로 고쳐졌을 때만 resolve 합니다.

## 플래그

| 플래그 | 모드 | 설명 |
|---|---|---|
| `--help`, `-h` | 둘 다 | 이 도움말 |
| `--dry-run` | 둘 다 | 게시하지 않고 계획만 만듭니다 (CI 에서는 Job Summary 에 출력). 로컬에서는 이후 "게시" 로 그대로 올릴 수 있습니다 |
| `--yes`, `-y` | 둘 다 | 로컬에서 확인 없이 게시합니다. CI 는 항상 이 동작입니다 |
| `--reply` | 답글 | 답글 모드로 전환 |
| `--focus <cat>[,...]` | 리뷰 | `correctness`, `security`, `conventions`, `reuse`, `perf`, `tests` 중에서만 지적 |
| `--with-critic` | 리뷰 | 2차 비평으로 오탐을 걸러 냅니다. 버린 이유는 요약 Dedup 절에 남고, 전부 버려지면 전부 다시 포함합니다 |
| `--auto-reply` | 리뷰 | 리뷰 게시 후 답글 모드까지 이어서 실행 |
| `--force` | 리뷰 | 같은 head 를 10분 안에 다시 리뷰 |

## 예시

```
/pcr
/pcr --focus security,conventions --with-critic
/pcr --dry-run
/pcr --reply
```
