---
name: pr-code-review
description: crispin-lab 조직의 GitHub PR 을 대상 레포의 `.claude/` 컨벤션 기준으로 리뷰하고, 인라인 + 요약을 봇 계정 이름으로 GitHub Review 하나에 게시한다. `--reply` 로 이전 봇 리뷰 스레드의 답글에 응답하고 수정이 확인되면 resolve 한다. `owner/repo#번호` 또는 PR URL 을 받을 때 사용한다.
---

# pr-code-review (로컬 진입점)

실제 동작은 전부 `crispin-review-bot` 레포의 `bin/pcr` 이 한다. CI(GitHub Actions)와 **같은 코드 · 같은
프롬프트**를 쓰므로, 이 스킬은 인자를 넘기고 확인을 받는 일만 한다. 절차를 직접 셸로 재현하지 않는다.

- `PCR_HOME` = 이 스킬이 링크된 `crispin-review-bot` 체크아웃 경로 (`skill/` 의 상위 디렉토리)
- 봇 인증: `GH_TOKEN=$(GH_CONFIG_DIR=$PCR_HOME/.bot-gh-config gh auth token)` — 사용자 본인의 `gh` 인증은 건드리지 않는다.

## 1. 도움말

인자에 `--help` / `-h` 가 있으면 `$PCR_HOME/skill/HELP.ko.md` 를 **그대로** 출력하고 끝낸다.

## 2. 봇 로그인 확인

```bash
GH_CONFIG_DIR="$PCR_HOME/.bot-gh-config" gh auth status
```

로그인돼 있지 않으면 `$PCR_HOME/skill/SETUP.md` 를 안내하고 멈춘다.

## 3. 리뷰 모드 (기본)

`--yes` 가 있으면 확인 없이 바로 게시한다:

```bash
GH_TOKEN=... "$PCR_HOME/bin/pcr" <target> [flags]
```

`--yes` 가 없으면 먼저 계획만 만든다:

```bash
GH_TOKEN=... "$PCR_HOME/bin/pcr" <target> [flags] --dry-run
```

출력된 `plan.md` 를 읽어 요약 · 인라인 코멘트 앞 3개를 사용자에게 보여 주고 게시할지 묻는다.
게시하라고 하면 **다시 리뷰하지 않고** 계획을 그대로 올린다 (head 가 바뀌었으면 `pcr` 이 거부한다):

```bash
GH_TOKEN=... "$PCR_HOME/bin/pcr" post <target>
```

사용자가 처음부터 `--dry-run` 을 줬다면 계획 경로만 알려 주고 멈춘다. 이후 같은 대화에서 "게시" / "올려" 라고
하면 위의 `pcr post` 를 실행한다.

## 4. 답글 모드 (`--reply`)

리뷰 모드와 같은 방식이다 — `--yes` 가 없으면 `--dry-run` 으로 `replies.md` 를 보여 주고 확인을 받은 뒤
`--dry-run` 없이 다시 실행한다 (답글 분류는 다시 돈다).

## 5. 종료 코드

| 코드 | 뜻 | 할 일 |
|---|---|---|
| 0 | 성공 | 게시된 URL · 건수를 보고 |
| 2 | 인자 · 인증 · GitHub · 판단 단계 오류 | 메시지를 그대로 전달 |
| 3 | 같은 head 를 10분 안에 이미 리뷰함 | `--force` 또는 대기를 안내 |

## 지킬 것

- 게시 본문은 `pcr` 이 검사한다 (생성 도구 표기 · 서명 · co-author 가 있으면 게시를 거부한다).
  우회하려고 본문을 직접 `gh api` 로 올리지 않는다.
- 이벤트는 항상 `COMMENT` 다. 승인 · 변경 요청을 하지 않는다.
