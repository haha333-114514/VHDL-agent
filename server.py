"""Start the local 知电 application with Python 3.10+, no pip dependencies."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import socket
import sys
from urllib.parse import unquote, urlparse, parse_qs
import webbrowser

from zhidian.catalog import TASKS, QUIZZES, public_task
from zhidian.provider import load_env
from zhidian.service import Service
from zhidian.simulator import find_ghdl

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "web"


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can silently share a port with another local app.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_handler(service: Service):
    csrf = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        server_version = "Zhidian/0.4"

        def log_message(self, fmt, *args):
            # Never log request bodies, source code or credentials.
            if args and isinstance(args[0], str) and "/api/runs/" in args[0] and "artifact" not in args[0]:
                return
            super().log_message(fmt, *args)

        def allowed_host(self):
            try:
                return urlparse("http://" + self.headers.get("Host", "")).hostname in {"localhost", "127.0.0.1", "::1"}
            except ValueError:
                return False

        def send_bytes(self, content: bytes, content_type: str, code=200, filename=None):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def send_json(self, data, code=200):
            self.send_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code)

        def do_GET(self):
            if not self.allowed_host():
                return self.send_json({"error": "仅允许本机访问。"}, 403)
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            try:
                if path == "/api/health":
                    return self.send_json({"ok": True, "name": "知电", "version": "0.4.0", "ghdl": bool(find_ghdl()), "provider": service.config.public(), "csrf": csrf})
                if path == "/api/tasks":
                    return self.send_json({"tasks": [public_task(task) for task in TASKS.values()]})
                if path == "/api/profile":
                    return self.send_json(service.store.profile())
                if path == "/api/history":
                    return self.send_json({"runs": service.store.history()})
                if path == "/api/quizzes":
                    task_id = parse_qs(parsed.query).get("task_id", [None])[0]
                    return self.send_json({"quizzes": service.quizzes(task_id)})
                if path.startswith("/api/runs/"):
                    parts = path.split("/")
                    run_id = parts[3]
                    job = service.get(run_id)
                    if len(parts) == 4:
                        return self.send_json(job)
                    if len(parts) == 5 and parts[4] == "report":
                        if job["status"] != "complete":
                            raise ValueError("实验完成后才能导出报告。")
                        content = (service.directory / "runs" / run_id / "report.md").read_bytes()
                        return self.send_bytes(content, "text/markdown; charset=utf-8", filename=f"zhidian-{run_id[:8]}.md")
                    if len(parts) > 5 and parts[4] == "artifact":
                        base = (service.directory / "runs" / run_id).resolve()
                        artifact = (base / "/".join(parts[5:])).resolve()
                        allowed = artifact.suffix in {".vcd", ".log"} or artifact.name in {"zd_tb.vhd","candidate.vhd","vectors.txt","observed.txt","checks.json"}
                        if not artifact.is_relative_to(base) or not allowed or not artifact.is_file():
                            raise FileNotFoundError("未找到该实验产物。")
                        if artifact.stat().st_size > 8_000_000:
                            raise ValueError("该产物超过网页下载上限，请从本地 data/runs 目录读取。")
                        return self.send_bytes(artifact.read_bytes(), "text/plain; charset=utf-8", filename=artifact.name)
                    raise FileNotFoundError("未找到接口。")
                if path.startswith("/api/"):
                    raise FileNotFoundError("未找到接口。")
                relative = "index.html" if path == "/" else path.lstrip("/")
                file = (STATIC / relative).resolve()
                if not file.is_relative_to(STATIC.resolve()) or not file.is_file():
                    raise FileNotFoundError("未找到页面。")
                mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                if file.suffix in {".js", ".css", ".html", ".svg"}:
                    mime += "; charset=utf-8"
                self.send_bytes(file.read_bytes(), mime)
            except FileNotFoundError as exc:
                self.send_json({"error": str(exc)}, 404)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
            except Exception:
                self.send_json({"error": "读取失败，请查看本机服务状态。"}, 500)

        def do_POST(self):
            origin = self.headers.get("Origin")
            expected = "http://" + self.headers.get("Host", "")
            if not self.allowed_host() or (origin and origin != expected) or self.headers.get("X-Zhidian-Token") != csrf:
                return self.send_json({"error": "请求来源校验失败，请刷新本地页面。"}, 403)
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                return self.send_json({"error": "仅接受 JSON 请求。"}, 415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 100000:
                    raise ValueError("请求体为空或超过 100 KB。")
                values = json.loads(self.rfile.read(length))
                if not isinstance(values, dict):
                    raise ValueError("请求格式应为 JSON 对象。")
                path = urlparse(self.path).path
                if path == "/api/run":
                    return self.send_json(service.start(values), 202)
                if path == "/api/config":
                    return self.send_json(service.config.update(values))
                if path == "/api/hint":
                    level = values.get("level")
                    if type(level) is not int:
                        raise ValueError("提示级别应为整数。")
                    return self.send_json(service.hint(values.get("run_id", ""), level))
                if path == "/api/quiz":
                    quiz_id = values.get("quiz_id")
                    if quiz_id not in QUIZZES:
                        raise ValueError("未知练习。")
                    quiz = QUIZZES[quiz_id]
                    choice = values.get("choice")
                    if type(choice) is not int or not 0 <= choice < len(quiz["options"]):
                        raise ValueError("请选择一个有效答案。")
                    return self.send_json(service.store.save_quiz(quiz_id, quiz, choice))
                self.send_json({"error": "未找到接口。"}, 404)
            except (ValueError, TypeError) as exc:
                self.send_json({"error": str(exc)}, 400)
            except Exception:
                self.send_json({"error": "操作失败，请查看本机服务状态。"}, 500)

    return Handler


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="知电 · 数字电路学习智能体")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    load_env(ROOT / ".env")
    service = Service(args.data_dir)
    try:
        server = LocalHTTPServer(("127.0.0.1", args.port), make_handler(service))
    except OSError:
        print(f"端口 {args.port} 不可用。可使用 python server.py --port 8766", flush=True)
        return 1
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"知电已启动：{url}", flush=True)
    print(f"GHDL：{'就绪' if find_ghdl() else '未找到，请设置 GHDL_PATH'}；数据目录：{service.directory}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n知电服务已停止。", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
