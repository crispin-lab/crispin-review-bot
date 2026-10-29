# 셋업

## 공통 — 봇 PAT

crispin-bot 계정으로 fine-grained PAT 를 만든다.

- Repository access: 리뷰 대상 레포 + `crispin-review-bot`
- Permissions: Contents **Read**, Issues **Read and write** (👀/🎉), Pull requests **Read and write** (리뷰 · 답글 · resolve)
- 만료일을 정하고 갱신 일정을 잡아 둔다.

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
