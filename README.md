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
