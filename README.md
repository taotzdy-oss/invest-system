# 个人投资管理系统

> 本地私有、单机运行的投资策略 + 选股 + 复盘 + 知识库一体化管理系统。
> 完全只读对接旧项目 `/Users/gegezi/Desktop/投资`，新增数据落到本仓库的 `data/system.db`。

## ✨ 特性

- **零 pip 依赖**：仅用 Python 3.9+ 标准库（`http.server` + `sqlite3`），无需 pip install。
- **完全只读旧项目**：策略脚本、复盘报告、台账 CSV、知识库 MD 全部按相对路径解析，绝不修改一字节。
- **四大模块**：
  - 📊 策略管理：扫描旧 `generate_fengmang_breakout_*.py` 当作策略快照，参数解析、版本留存、版本对比、基于复盘台账的事后回测。
  - 📈 每日选股：列出所有 `锋芒爆点_*_打板观察池` 目录，渲染 HTML 候选池表，对每只票打标记 (观察/建仓/持仓/放弃) + 批注。
  - 📝 复盘管理：复盘日历、台账筛选、四个晋级分层池、复盘经验库、策略迭代日志、追加复盘笔记，可一键重跑 `rebuild_promotion_buckets.py`。
  - 📚 知识库：分类树 + 全文检索 + MD/HTML/CSV 文档渲染 + 用户笔记（可关联到知识库文档）。
- **统一入口**：浏览器访问 `http://127.0.0.1:8787` 即用，自动开浏览器。
- **运行日志**：所有"调用旧项目脚本"的子进程都记录到 `run_logs` 表，可在 `/system/logs` 查看。

## 🚀 快速开始

```bash
# 1. 进入项目目录
cd /Users/gegezi/Desktop/投资管理系统

# 2. 启动（默认端口 8787，自动打开浏览器）
bash scripts/run.sh

# 或：自定义端口
PORT=9000 bash scripts/run.sh

# 或：直接 python
python3 app.py
python3 app.py --port 9000 --no-browser
```

启动后访问 [http://127.0.0.1:8787](http://127.0.0.1:8787)。

## ✅ 自检

```bash
bash scripts/check.sh
```

预期输出：单元测试 18/18 全过，端到端冒烟测试 23/23 全过。

## 🛰 GitHub 同步

```bash
# 首次配置（创建仓库 + 关联，见 docs/部署说明.md）

# 之后一键同步
bash scripts/git_sync.sh                          # 自动 commit + push
bash scripts/git_sync.sh "feat: 新增策略对比页面"  # 自定义 commit message
AUTO_PUSH=0 bash scripts/git_sync.sh              # 仅提交不推送
```

## 📂 目录结构

```
投资管理系统/
├── app.py                 # 入口
├── config.json            # 旧项目路径 + 服务端口 + git 配置
├── core/
│   ├── config.py          # 配置加载
│   ├── db.py              # SQLite schema / 事务封装
│   ├── router.py          # 极简 http 路由
│   ├── templates.py       # 极简模板引擎
│   └── markdown.py        # 极简 Markdown->HTML
├── adapters/              # 只读对接层
│   ├── files.py
│   ├── knowledge_base.py  # 锋芒策略解析知识库_*
│   ├── review.py          # 锋芒爆点_复盘迭代
│   ├── stock_pick.py      # 锋芒爆点_*_打板观察池
│   ├── strategy.py        # generate_fengmang_breakout_*.py
│   └── runner.py          # 调用旧项目脚本
├── modules/               # 业务路由 + 视图
│   ├── home.py
│   ├── strategy.py
│   ├── picks.py
│   ├── review.py
│   └── kb.py
├── templates/layout.html
├── static/
├── data/system.db         # SQLite（git ignore）
├── scripts/
│   ├── run.sh             # 启动
│   ├── check.sh           # 自检
│   └── git_sync.sh        # 一键提交+推送
├── tests/
│   ├── test_units.py
│   └── smoke.py
└── docs/
    ├── 部署说明.md
    ├── 使用教程.md
    ├── 旧项目对接.md
    └── GitHub同步配置.md
```

## 🔒 安全约束

| 约束 | 实现 |
| --- | --- |
| 只读旧项目 | 适配器一律使用 `read_text`/`read_csv_rows`，无写操作；运行脚本是用户主动点击触发 |
| 静态文件越界 | `core/router.py` 静态文件路由会 `resolve()` 后校验是否在 `static/` 内 |
| 知识库越界 | `adapters/knowledge_base.read_doc` 同样做了根目录归属校验 |
| XSS | Markdown 渲染 + 模板渲染默认 HTML escape |
| 服务暴露面 | 默认绑定 `127.0.0.1`，不监听公网 |

## 📚 详细文档

- [docs/部署说明.md](docs/部署说明.md) - 环境准备、首次启动、常见问题
- [docs/使用教程.md](docs/使用教程.md) - 四大模块逐一演示
- [docs/旧项目对接.md](docs/旧项目对接.md) - config.json 各字段含义、自定义对接
- [docs/GitHub同步配置.md](docs/GitHub同步配置.md) - 本地 Git ↔ GitHub 全流程
