"""单元测试：核心组件健壮性。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.markdown import render as md  # noqa: E402


def t(label, cond, msg=""):
    color = "\033[32m" if cond else "\033[31m"
    print(f"{color}{'OK ' if cond else 'FAIL'}\033[0m  {label}  {msg if not cond else ''}")
    return cond


def main() -> int:
    fails = 0

    # H1
    h = md("# Hello")
    if not t("h1", "<h1>Hello</h1>" in h, h): fails += 1

    # paragraph
    h = md("This is a line.\nstill same para.\n\nNew para.")
    if not t("paragraph", "<p>This is a line. still same para.</p>" in h and "<p>New para.</p>" in h, h): fails += 1

    # bold + inline code
    h = md("a **bold** and `code` here")
    if not t("inline bold/code", "<strong>bold</strong>" in h and "<code>code</code>" in h, h): fails += 1

    # link
    h = md("link to [docs](https://example.com)")
    if not t("link", 'href="https://example.com"' in h and ">docs<" in h, h): fails += 1

    # ul
    h = md("- a\n- b\n- c")
    if not t("ul", h.count("<li>") == 3 and "<ul>" in h, h): fails += 1

    # ol
    h = md("1. a\n2. b\n3. c")
    if not t("ol", h.count("<li>") == 3 and "<ol>" in h, h): fails += 1

    # table
    table_md = "| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
    h = md(table_md)
    if not t("table", "<table>" in h and h.count("<tr>") == 3 and "<td>1</td>" in h, h): fails += 1

    # code block
    h = md("```python\nprint('hi')\n```")
    if not t("code-fence", '<pre><code class="lang-python">' in h, h): fails += 1

    # blockquote
    h = md("> quoted\n> still")
    if not t("blockquote", "<blockquote>quoted still</blockquote>" in h, h): fails += 1

    # escaping
    h = md("<script>alert(1)</script>")
    if not t("escape", "&lt;script&gt;" in h and "<script>" not in h, h): fails += 1

    # 适配器：能正常 import
    from adapters import knowledge_base, review, stock_pick, strategy, runner  # noqa
    if not t("adapters import", True): fails += 1

    # config 加载
    from core.config import CONFIG
    if not t("config root exists", CONFIG.legacy_root.exists(), str(CONFIG.legacy_root)): fails += 1

    # 旧项目台账可读
    ledger = review.ledger_rows()
    if not t("ledger non-empty", len(ledger) > 0, f"rows={len(ledger)}"): fails += 1

    # 知识库可列
    docs = knowledge_base.list_docs()
    if not t("kb docs non-empty", len(docs) > 0, f"docs={len(docs)}"): fails += 1

    # 选股池可列
    pools = stock_pick.list_pools()
    if not t("stock pools non-empty", len(pools) > 0, f"pools={len(pools)}"): fails += 1

    # 候选行解析
    if pools:
        cands = stock_pick.parse_html_candidates(pools[0])
        if not t("candidates parsed", len(cands) >= 1, f"cands={len(cands)} pool={pools[0].dir_path.name}"): fails += 1

    # 策略脚本解析
    scripts = strategy.list_strategy_scripts()
    if not t("strategy scripts", len(scripts) > 0, f"scripts={len(scripts)}"): fails += 1
    if scripts:
        if not t("strategy params extracted", isinstance(scripts[0].params, dict) and len(scripts[0].params) > 0,
                 f"keys={list(scripts[0].params.keys())}"):
            fails += 1

    print()
    print(("\033[32m✓ ALL UNIT TESTS PASSED\033[0m" if fails == 0
           else f"\033[31m✗ {fails} TEST(S) FAILED\033[0m"))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
