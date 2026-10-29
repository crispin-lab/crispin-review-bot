# 셋업

## 공통 — 봇 PAT

crispin-bot 계정으로 **fine-grained** PAT 를 만든다. 대상 레포가 private 이라 classic PAT 는 `repo` 전체
권한(코드 쓰기 포함)이 필요해 쓰지 않는다.

1. 사전 조건 (org 관리자 계정으로)
   - crispin-bot 이 crispin-lab **멤버**여야 Resource owner 에 org 가 보인다. 멤버로 초대하고
     Settings → Member privileges → Base permissions 는 **No permission** 으로 둔다.
   - 각 대상 레포의 Collaborators and teams 에서 crispin-bot 에 **Write** 를 준다 (스레드 resolve 에 필요).
   - Settings → Personal access tokens → Settings 에서 fine-grained 토큰 접근을 허용한다.
     관리자 승인을 켜 두었다면 발급 후 Pending requests 에서 승인한다.
2. 발급 (crispin-bot 계정으로) — Settings → Developer settings → Fine-grained tokens
   - Resource owner: **crispin-lab** · Repository access: **Only select repositories** → 대상 레포만
   - Permissions: Contents **Read-only**, Issues **Read and write**, Pull requests **Read and write**
   - 만료일을 정하고 갱신 일정을 잡아 둔다.
3. `crispin-review-bot` 은 범위에 넣지 않는다. 공개 레포라 Actions 가 토큰 없이 가져오고,
   봇이 이 레포에 접근하지 못하는 편이 공급망 측면에서 안전하다.

## 로컬

```bash
git clone https://github.com/crispin-lab/crispin-review-bot ~/documents/personal/git/crispin-review-bot
export PCR_HOME=~/documents/personal/git/crispin-review-bot

# 봇 전용 gh 설정 (본인 gh 인증과 분리)
mkdir -p "$PCR_HOME/.bot-gh-config" && chmod 700 "$PCR_HOME/.bot-gh-config"
GH_CONFIG_DIR="$PCR_HOME/.bot-gh-config" gh auth login --with-token < bot-token.txt

# 스킬 연결 (기존 스킬 디렉토리는 백업 후 교체)
ln -sfn "$PCR_HOME/skill" ~/.claude/skills/pr-code-review
```

판단 단계는 로컬 `claude` CLI 를 쓰므로 Claude Code 로그인 상태면 된다. `.bot-gh-config/` 는
`.gitignore` 에 있고 공유 저장소로 백업하지 않는다.

## CI (GitHub Actions + Workload Identity Federation)

1. Claude Console → Settings → Workload identity → **Connect workload** → GitHub Actions
   - issuer: `https://token.actions.githubusercontent.com` (JWKS discovery)
   - 서비스 계정을 리뷰용 워크스페이스에 추가
   - federation rule 은 **레포마다** 좁게. 이벤트별 `sub` 형식이 다르므로 아래처럼 잡고
     `repository_owner` 를 함께 고정한다:
     - `subject_prefix`: `repo:crispin-lab/<repo>:`
     - `claims`: `{"repository_owner": "crispin-lab"}`
     - `audience`: `https://api.anthropic.com`
   - 첫 실행이 거부되면 Workload identity → History 에서 실제 `sub` 를 보고 좁힌다.
2. 대상 레포(또는 org)에 등록
   - secret `CRISPIN_BOT_TOKEN` — 위 PAT
   - variables `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID`
     (식별자라 secret 이 아니어도 된다)
3. `crispin-review-bot` 이 private 이면 Settings → Actions → General → Access 에서
   "Accessible from repositories in the 'crispin-lab' organization" 을 켠다.
4. 레포 설정에서 fork PR 에 쓰기 토큰을 보내는 옵션이 꺼져 있는지 확인한다.
5. 대상 레포에 `examples/pcr.yml` 을 `.github/workflows/pcr.yml` 로 복사한다.
6. 자체 러너를 쓰면 repository variable `PCR_RUNNER` (없으면 `CI_RUNNER`) 에 러너 라벨을 넣는다.
   러너에는 `gh` · `git` · `curl` 만 있으면 된다 (Python · Node · `claude` 는 Action 이 받는다).
   러너 사용자의 `~/.claude` 는 쓰지 않지만, 그 계정이 Claude Code 에 로그인돼 있으면 로그인 정보가
   federation 보다 먼저 잡히는지 첫 실행 로그 · Console 사용량으로 확인한다.
7. `crispin-review-bot` 레포에 ruleset 을 건다: `main` 과 `v*` 태그는 삭제 · 강제 push · 직접 갱신 금지.
   태그를 옮길 수 있으면 `@v1` 을 쓰는 모든 레포의 봇 PAT 가 그 코드에 노출된다.
