"""脚本运行适配器：在子进程里调用旧项目 python 脚本，记录到 run_logs。"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from core.db import tx


def run_python(script_path: Path, kind: str = "stock_pick",
               cwd: Path | None = None, timeout: int = 600) -> dict:
    """同步执行旧项目脚本，返回 {ok, stdout, stderr, exit_code, duration_ms}。"""
    cwd = cwd or script_path.parent
    cmd = ["python3", str(script_path)]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        stderr = (e.stderr or "") + f"\n[TIMEOUT after {timeout}s]"
        exit_code = -1
    except FileNotFoundError as e:
        stdout = ""; stderr = str(e); exit_code = -2
    duration_ms = int((time.time() - started) * 1000)

    with tx() as conn:
        conn.execute(
            "INSERT INTO run_logs (kind, cmd, cwd, exit_code, stdout, stderr, duration_ms) "
            "VALUES (?,?,?,?,?,?,?)",
            (kind, " ".join(cmd), str(cwd), exit_code, stdout[-20000:], stderr[-20000:], duration_ms),
        )

    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms,
        "cmd": " ".join(cmd),
    }


def list_recent_logs(kind: str | None = None, limit: int = 30) -> list[dict]:
    from core.db import get_conn
    conn = get_conn()
    try:
        if kind:
            cur = conn.execute(
                "SELECT * FROM run_logs WHERE kind=? ORDER BY id DESC LIMIT ?",
                (kind, limit),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM run_logs ORDER BY id DESC LIMIT ?", (limit,),
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
