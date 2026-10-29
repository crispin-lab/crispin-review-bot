# crispin-review-bot

crispin-lab 조직 PR 을 대상 레포의 `.claude/` 컨벤션 기준으로 리뷰하고, crispin-bot 이름으로 GitHub Review 를
남기는 도구. 로컬(Claude Code 스킬)과 GitHub Actions 가 같은 코드로 돈다.

## 구조

```
bin/pcr              CLI 진입점
pcr/                 절차 (수집 · 지문 · 중복 제거 · 라인 검증 · 게시 · 반응 · 답글)
prompts/             판단 지시 (review · critic · reply-classify)
schemas/             판단 출력 JSON 스키마
skill/               로컬 Claude Code 스킬 (SKILL.md · HELP.ko.md · SETUP.md)
action.yml           GitHub Action (composite)
examples/pcr.yml     대상 레포에 복사할 워크플로
```

## 흐름

```
수집 (PR · diff · 연결 이슈 · head 체크아웃 · .claude/ 컨벤션 · 기존 봇 지문)
  → 판단: claude -p, 읽기 전용 도구만, JSON 스키마로 출력 고정
  → (선택) 2차 비평
  → 계획: 지문 계산 · 중복 제거 · 인라인 가능 줄 검증 · 요약 조립 · 본문 검사
  → 게시: 리뷰 1회 POST (재시도 전 같은 실행 마커로 이미 들어갔는지 확인) · 👀→🎉
```

- **인증**: GitHub 은 `GH_TOKEN`(crispin-bot PAT) 하나. Claude 는 로컬은 Claude Code 로그인,
  CI 는 Workload Identity Federation (정적 API 키 없음).
- **안전**: 판단 단계는 PR head 를 `--add-dir` 로만 읽고 project 설정(hooks 등)을 불러오지 않는다.
  쓰기 · 셸 · 웹 도구가 없다. 게시 본문은 `pcr/sanitize.py` 가 검사한다.

## 보안 (공개 레포)

이 레포는 공개다. 코드에 비밀값은 없고, 비밀값은 호출하는 레포의 secret 으로만 들어온다.

- **판단 단계 격리**: 읽기 도구를 허용 목록으로 주지 않는다 (넓게 주면 체크아웃 밖 · `/proc` 까지 읽힌다).
  자식 프로세스 환경에서 `GH_TOKEN` · OIDC 요청 자격을 지운다. 게시 본문에 토큰 · JWT · 개인키 모양의
  문자열이 있으면 게시하지 않는다.
- **fork PR**: 컨벤션을 head 가 아니라 base 에서 읽는다 (작성자가 룰을 고쳐 지적을 피하지 못하게).
  fork PR 에는 secret · `id-token: write` 가 전달되지 않아 자동 리뷰가 돌지 않는다.
- **`/pcr` 명령**: OWNER · MEMBER 만 실행된다 (워크플로 `if` 와 코드에서 두 번 확인).
- **공급망**: 이 레포에 push 할 수 있는 사람은 봇 PAT 와 Anthropic 토큰을 쥔 코드를 바꿀 수 있다.
  `main` 과 `v*` 태그를 ruleset 으로 보호한다 (태그 생성 · 이동은 관리자만). 호출하는 레포는 `@v1` 을 쓰므로
  **`v1` 을 옮기는 순간 모든 레포에 리뷰 없이 적용된다** — 옮기기 전에 `main` 의 변경을 확인한다.
  레포 · 사람이 늘면 커밋 SHA 고정 + 버전 태그(`v1.0.x`) + Dependabot 으로 바꾼다.

## 사용

- 로컬: `/pr-code-review crispin-lab/<repo>#<번호> [flags]`
- PR 코멘트: `/pcr [flags]`
- 플래그: `skill/HELP.ko.md`
- 셋업: `skill/SETUP.md`

## 개발

```bash
python3 -m unittest discover -s tests -t .
```

배포는 태그로 한다. 대상 레포는 `crispin-lab/crispin-review-bot@v1` 을 쓰므로, 호환되는 변경은
`v1` 태그를 옮기고 깨지는 변경은 `v2` 를 만든다.

```bash
git fetch origin main && git tag -f v1 origin/main && git push -f origin v1
```

`examples/pcr.yml` (트리거 · `if` · 권한 · 러너) 을 바꾼 릴리스는 태그만으로 반영되지 않는다 — 각 레포가
복사해 쓰는 파일이라 레포마다 `.github/workflows/pcr.yml` 을 같이 고친다.
