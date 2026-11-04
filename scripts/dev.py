"""Start the FE and BE from the repository's shared uv environment.

Run from the project root: uv run python scripts/dev.py
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    node = shutil.which("node")
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    if not node or not vite.is_file():
        print("Node.js 22.12 이상과 FE 의존성이 필요합니다. npm --prefix frontend ci를 실행하세요.")
        return 1
    backend_port = os.environ.get("BACKEND_PORT", "8000")
    frontend_port = os.environ.get("FRONTEND_PORT", "5173")
    processes: list[subprocess.Popen] = []

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--app-dir",
                    "backend",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    backend_port,
                ],
                cwd=ROOT,
                start_new_session=True,
            )
        )
        processes.append(
            subprocess.Popen(
                [node, str(vite), "--host", "127.0.0.1", "--port", frontend_port],
                cwd=ROOT / "frontend",
                start_new_session=True,
                env={**os.environ, "BACKEND_URL": f"http://127.0.0.1:{backend_port}"},
            )
        )
        print(
            f"FE: http://127.0.0.1:{frontend_port} | API: http://127.0.0.1:{backend_port}/docs",
            flush=True,
        )
        print("모델 미연결 예시 모드 · 종료: Ctrl+C", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.2)
        return next(
            (process.returncode for process in processes if process.returncode is not None), 1
        )
    except KeyboardInterrupt:
        return 0
    finally:
        # A repeated signal must not interrupt cleanup and leave a server running.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for process in processes:
            if process.poll() is None:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
