#!/usr/bin/env python3
"""
线圈控制 Web 前端

Linux 运行：
    python3 coil_web_app.py

然后在浏览器打开：
    http://127.0.0.1:8080
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import coil_tool


HOST = "0.0.0.0"
PORT = 8080


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Modbus 线圈控制</title>
  <style>
    body {
      margin: 0;
      font-family: Arial, "Microsoft YaHei", sans-serif;
      background: #f3f4f6;
      color: #111827;
    }
    .page {
      max-width: 820px;
      margin: 32px auto;
      padding: 0 16px;
    }
    .card {
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
      padding: 24px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 26px;
    }
    .sub {
      margin: 0 0 20px;
      color: #6b7280;
      font-size: 14px;
    }
    .toolbar {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }
    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 16px;
      cursor: pointer;
      font-size: 15px;
      background: #2563eb;
      color: white;
    }
    button.secondary {
      background: #4b5563;
    }
    button.danger {
      background: #dc2626;
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }
    .coil {
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      padding: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    .name {
      font-weight: 700;
      margin-bottom: 4px;
    }
    .addr {
      color: #6b7280;
      font-size: 13px;
    }
    .state {
      min-width: 52px;
      text-align: center;
      border-radius: 999px;
      padding: 6px 10px;
      font-weight: 700;
      color: white;
      background: #9ca3af;
    }
    .state.on {
      background: #16a34a;
    }
    .log {
      white-space: pre-wrap;
      background: #111827;
      color: #d1d5db;
      padding: 12px;
      border-radius: 10px;
      margin-top: 18px;
      min-height: 44px;
      font-family: Consolas, monospace;
      font-size: 13px;
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="card">
      <h1>Modbus 线圈控制</h1>
      <p class="sub" id="info">正在读取配置...</p>

      <div class="toolbar">
        <button onclick="loadCoils()">刷新状态</button>
        <button onclick="writeAll(true)">全部打开</button>
        <button class="danger" onclick="writeAll(false)">全部关闭</button>
      </div>

      <div class="grid" id="grid"></div>
      <div class="log" id="log">等待操作...</div>
    </div>
  </div>

  <script>
    let coilNames = [];
    let coilAddress = 0;
    let busy = false;

    function setLog(message) {
      document.getElementById("log").textContent = message;
    }

    function setBusy(value) {
      busy = value;
      document.querySelectorAll("button").forEach(button => {
        button.disabled = value;
      });
    }

    async function requestJson(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "请求失败");
      }
      return data;
    }

    function render(values) {
      const grid = document.getElementById("grid");
      grid.innerHTML = "";

      values.forEach((value, index) => {
        const card = document.createElement("div");
        card.className = "coil";

        const text = document.createElement("div");
        text.innerHTML = `
          <div class="name">${coilNames[index] || `线圈 ${index + 1}`}</div>
          <div class="addr">地址：${coilAddress + index}</div>
        `;

        const button = document.createElement("button");
        button.className = value ? "danger" : "";
        button.textContent = value ? "关闭" : "打开";
        button.onclick = () => writeOne(index, !value);

        const state = document.createElement("span");
        state.className = value ? "state on" : "state";
        state.textContent = value ? "ON" : "OFF";

        const actions = document.createElement("div");
        actions.appendChild(state);
        actions.appendChild(document.createTextNode(" "));
        actions.appendChild(button);

        card.appendChild(text);
        card.appendChild(actions);
        grid.appendChild(card);
      });
    }

    async function loadCoils() {
      if (busy) return;
      setBusy(true);
      try {
        const data = await requestJson("/api/coils");
        coilNames = data.names;
        coilAddress = data.address;
        document.getElementById("info").textContent =
          `设备 ${data.ip}:${data.port}，unit=${data.unit}，读取 ${data.count} 个线圈`;
        render(data.values);
        setLog(`读取成功：${JSON.stringify(data.values)}`);
      } catch (error) {
        setLog(`错误：${error.message}`);
      } finally {
        setBusy(false);
      }
    }

    async function writeOne(index, value) {
      if (busy) return;
      setBusy(true);
      try {
        const data = await requestJson("/api/coil", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({index, value})
        });
        render(data.values);
        setLog(`写入成功：${coilNames[index] || index} = ${value}`);
      } catch (error) {
        setLog(`错误：${error.message}`);
      } finally {
        setBusy(false);
      }
    }

    async function writeAll(value) {
      if (busy) return;
      setBusy(true);
      try {
        const values = new Array(coilNames.length || 6).fill(value);
        const data = await requestJson("/api/coils", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({values})
        });
        render(data.values);
        setLog(`全部写入成功：${JSON.stringify(values)}`);
      } catch (error) {
        setLog(`错误：${error.message}`);
      } finally {
        setBusy(false);
      }
    }

    loadCoils();
  </script>
</body>
</html>
"""


def ok_response(handler: BaseHTTPRequestHandler, data: dict) -> None:
    body = json.dumps({"ok": True, **data}, ensure_ascii=False).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def error_response(handler: BaseHTTPRequestHandler, message: str, status: int = 500) -> None:
    body = json.dumps({"ok": False, "error": message}, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def coil_payload(values):
    return {
        "ip": coil_tool.IP,
        "port": coil_tool.PORT,
        "unit": coil_tool.UNIT,
        "address": coil_tool.COIL_ADDRESS,
        "count": coil_tool.COIL_COUNT,
        "names": coil_tool.COIL_NAMES,
        "values": values,
    }


class CoilHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/coils":
            try:
                values = coil_tool.read_coils()
                ok_response(self, coil_payload(values))
            except Exception as exc:
                error_response(self, str(exc))
            return

        error_response(self, "Not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")

            if path == "/api/coils":
                values = data.get("values")
                if not isinstance(values, list) or len(values) != coil_tool.COIL_COUNT:
                    raise ValueError(f"values 必须是长度为 {coil_tool.COIL_COUNT} 的数组")
                coil_tool.write_coils(coil_tool.COIL_ADDRESS, values)
                ok_response(self, coil_payload(coil_tool.read_coils()))
                return

            if path == "/api/coil":
                index = int(data.get("index"))
                value = bool(data.get("value"))
                coil_tool.write_one_coil(index, value)
                ok_response(self, coil_payload(coil_tool.read_coils()))
                return

            error_response(self, "Not found", 404)
        except Exception as exc:
            error_response(self, str(exc))

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


def main():
    server = ThreadingHTTPServer((HOST, PORT), CoilHandler)
    print(f"线圈控制页面：http://127.0.0.1:{PORT}")
    print("按 Ctrl+C 停止服务")
    server.serve_forever()


if __name__ == "__main__":
    main()
