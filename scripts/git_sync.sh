#!/usr/bin/env bash
# 一键提交 + 推送到 GitHub
#
# 用法：
#   scripts/git_sync.sh                              # 自动生成 commit message
#   scripts/git_sync.sh "feat: 新增策略对比页面"    # 指定 commit message
#   AUTO_PUSH=0 scripts/git_sync.sh                  # 只提交，不推送
#
# 首次使用前，请按 docs/部署说明.md 配置 GitHub 远程仓库。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .git ]]; then
  echo "[错误] 当前目录不是 Git 仓库；请先按 docs/部署说明.md 初始化。"
  exit 1
fi

# 切到默认分支配置
BRANCH=$(jq -r '.git.default_branch // "main"' config.json 2>/dev/null || echo "main")
REMOTE=$(jq -r '.git.remote_name // "origin"' config.json 2>/dev/null || echo "origin")
PREFIX=$(jq -r '.git.commit_prefix // "chore: "' config.json 2>/dev/null || echo "chore: ")
[[ "$BRANCH" == "null" ]] && BRANCH=main
[[ "$REMOTE" == "null" ]] && REMOTE=origin
[[ "$PREFIX" == "null" ]] && PREFIX="chore: "

# 当前分支
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# 用户指定的提交信息
MSG="${1:-}"
if [[ -z "$MSG" ]]; then
  # 自动生成：根据变更文件数自动总结
  STAGED_COUNT=$(git status --porcelain | wc -l | tr -d ' ')
  TS=$(date "+%Y-%m-%d %H:%M:%S")
  MSG="${PREFIX}本地数据同步 (${TS}, 变更 ${STAGED_COUNT} 个文件)"
fi

echo "[git] 当前分支: $CURRENT_BRANCH (目标: $BRANCH)"
echo "[git] 远程: $REMOTE"
echo "[git] commit message: $MSG"

# 改动检测
if git diff --quiet && git diff --cached --quiet; then
  if [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
    echo "[git] 无任何变更，跳过本次提交。"
    exit 0
  fi
fi

git add -A
git commit -m "$MSG" || {
  echo "[git] 提交失败（可能由 pre-commit hook 触发），请检查后重试。"
  exit 1
}

AUTO_PUSH="${AUTO_PUSH:-1}"
if [[ "$AUTO_PUSH" != "1" ]]; then
  echo "[git] AUTO_PUSH=0，已提交但未推送。"
  exit 0
fi

# 远程未配置时跳过推送
if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "[git] 未配置远程 '$REMOTE'，跳过推送。"
  echo "      首次推送请先执行： git remote add $REMOTE git@github.com:<你的用户名>/<仓库名>.git"
  exit 0
fi

# 推送（首次自动设置 upstream）
if git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
  git push "$REMOTE" "$CURRENT_BRANCH"
else
  git push -u "$REMOTE" "$CURRENT_BRANCH"
fi

echo "[git] ✅ 已推送到 $REMOTE/$CURRENT_BRANCH"
