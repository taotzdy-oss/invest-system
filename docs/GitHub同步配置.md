# GitHub 同步配置

> 目标：把 `/Users/gegezi/Desktop/投资管理系统` 关联到你的 GitHub 账号，并通过 `scripts/git_sync.sh` 一键提交 + 推送。
>
> 旧项目目录 `/Users/gegezi/Desktop/投资` **不会**被纳入版本控制（仓库根在新目录，没有 include 关系）。

---

## 一、首次配置（一次性）

### 1.1 配置 Git 全局身份（如已设置可跳过）

```bash
git config --global user.name  "你的名字"
git config --global user.email "你的邮箱@xxx"
git config --global init.defaultBranch main
```

确认：

```bash
git config --global --list | grep -E "user\.|init\.default"
```

### 1.2 生成 SSH Key（推荐，免每次输密码）

```bash
ls -la ~/.ssh/id_ed25519.pub 2>/dev/null || \
  ssh-keygen -t ed25519 -C "你的邮箱@xxx" -f ~/.ssh/id_ed25519 -N ""

# 启动 ssh-agent 并加载 key（macOS）
eval "$(ssh-agent -s)"
ssh-add --apple-use-keychain ~/.ssh/id_ed25519 2>/dev/null || ssh-add ~/.ssh/id_ed25519

# 复制公钥到剪贴板
pbcopy < ~/.ssh/id_ed25519.pub
```

打开 [https://github.com/settings/keys](https://github.com/settings/keys) → "New SSH key" → 粘贴。

测试连接：

```bash
ssh -T git@github.com
# 期望输出 "Hi <你的用户名>! You've successfully authenticated..."
```

### 1.3 在 GitHub 上创建空仓库

1. 访问 [https://github.com/new](https://github.com/new)
2. **Repository name**：例如 `personal-invest-mgmt`
3. **Visibility**：建议 **Private**（这是你的本地选股/复盘数据）
4. **不要**勾选 "Add README" / "Add .gitignore" / "Add license"（避免和本地冲突）
5. 点 **Create repository**

记下仓库 SSH 地址，例如：

```
git@github.com:<你的用户名>/personal-invest-mgmt.git
```

### 1.4 本地仓库初始化 + 关联远程

> 本仓库已由系统初始化时 `git init` 完成。如果你看到 `.git/` 已存在可直接跳到关联远程。

```bash
cd /Users/gegezi/Desktop/投资管理系统

# (如果还没初始化)
git init
git branch -M main

# 关联远程
git remote add origin git@github.com:<你的用户名>/personal-invest-mgmt.git
git remote -v   # 验证

# 首次推送（设置上游分支）
git push -u origin main
```

> 如果远程仓库不是 SSH 而是 HTTPS：`git remote set-url origin https://github.com/<用户名>/<仓库>.git`

---

## 二、日常同步：一键命令

```bash
cd /Users/gegezi/Desktop/投资管理系统
bash scripts/git_sync.sh
```

行为：
1. 自动检测 `.git/` 是否存在
2. 用 `config.json -> git` 里的 `default_branch` / `remote_name` / `commit_prefix` 配置（默认 `main` / `origin` / `chore: `）
3. 如有变更：`git add -A` + `git commit -m "<前缀>本地数据同步 (时间, 文件数)"`
4. 自动 `git push`（首次自动加 `-u`）

带自定义提交信息：

```bash
bash scripts/git_sync.sh "feat: 新增 v3 调参版本对比页"
```

仅提交不推送：

```bash
AUTO_PUSH=0 bash scripts/git_sync.sh
```

## 三、定时自动同步（可选）

### 方式 A：macOS launchd（推荐，能在登录后台跑）

创建 `~/Library/LaunchAgents/com.local.invest.gitsync.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.local.invest.gitsync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/gegezi/Desktop/投资管理系统/scripts/git_sync.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key>
  <string>/Users/gegezi/Desktop/投资管理系统/data/gitsync.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/gegezi/Desktop/投资管理系统/data/gitsync.err</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.local.invest.gitsync.plist
launchctl list | grep invest
```

> 表示每天 23:30 自动同步。修改 `Hour` / `Minute` 调整时间。

### 方式 B：crontab

```bash
crontab -e
# 加入下面这行（每天 23:30 同步）
30 23 * * * /bin/bash /Users/gegezi/Desktop/投资管理系统/scripts/git_sync.sh >> /Users/gegezi/Desktop/投资管理系统/data/gitsync.log 2>&1
```

## 四、常见问题

### Q: push 时报 `Authentication failed`
- 用 SSH 时：跑 `ssh -T git@github.com` 验证。
- 用 HTTPS 时：先 `git config --global credential.helper osxkeychain`，下一次输入用户名 + Personal Access Token（不再是密码），系统会记住。

### Q: 第一次推送报 `! [rejected] main -> main (fetch first)`
GitHub 仓库非空（创建时勾选了 README）。
```bash
git pull --rebase origin main
git push -u origin main
```

### Q: 想推到不同分支
```bash
git checkout -b dev
bash scripts/git_sync.sh    # 自动按当前分支推送
```

### Q: 想保留 `data/system.db` 上云
默认 `.gitignore` 忽略数据库。如果你想多端同步本地数据库，把 `.gitignore` 中 `data/system.db` 那一行删除即可。
**不建议**这么做：sqlite 二进制文件 diff 噪音大且包含交易批注，最好留本地。

### Q: 想用 GitHub CLI (`gh`) 创建仓库
```bash
brew install gh
gh auth login
cd /Users/gegezi/Desktop/投资管理系统
gh repo create personal-invest-mgmt --private --source=. --remote=origin --push
```
