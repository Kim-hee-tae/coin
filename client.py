#!/usr/bin/env python3
"""2인 소켓 비행기 게임 클라이언트 (tkinter 기반)."""

from __future__ import annotations

import argparse
import json
import queue
import socket
import threading
import time
import tkinter as tk
from dataclasses import dataclass

ENCODING = "utf-8"
WIDTH, HEIGHT = 700, 500
PLANE_SIZE = 22
SPEED = 6
SEND_INTERVAL = 0.05


@dataclass
class PlaneState:
    x: float
    y: float
    hp: int = 5


class AirplaneGameClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.recv_queue: queue.Queue[dict] = queue.Queue()
        self.running = True

        self.player_id = 0
        self.local = PlaneState(WIDTH * 0.25, HEIGHT * 0.5)
        self.remote = PlaneState(WIDTH * 0.75, HEIGHT * 0.5)

        self.keys: set[str] = set()

        self.root = tk.Tk()
        self.root.title("2인 비행기 게임 (소켓)")
        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg="#061826")
        self.canvas.pack()

        self.status_var = tk.StringVar(value="서버 연결 중...")
        tk.Label(self.root, textvariable=self.status_var, anchor="w").pack(fill="x")

        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.bind("<KeyRelease>", self.on_key_release)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.last_send = 0.0

    def connect(self) -> None:
        self.sock.connect((self.host, self.port))
        t = threading.Thread(target=self.recv_loop, daemon=True)
        t.start()

        deadline = time.time() + 5
        while self.player_id == 0 and time.time() < deadline:
            self.process_messages_once()
            time.sleep(0.01)

        if self.player_id == 0:
            raise RuntimeError("서버에서 welcome 메시지를 받지 못했습니다.")

        side_text = "왼쪽" if self.player_id == 1 else "오른쪽"
        self.status_var.set(f"연결됨: 내 비행기={self.player_id}번 ({side_text})")

        if self.player_id == 1:
            self.local.x = WIDTH * 0.25
            self.remote.x = WIDTH * 0.75
        else:
            self.local.x = WIDTH * 0.75
            self.remote.x = WIDTH * 0.25

    def recv_loop(self) -> None:
        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(4096)
                if not data:
                    self.recv_queue.put({"type": "disconnected"})
                    break
                buffer += data.decode(ENCODING)
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        self.recv_queue.put(msg)
                    except json.JSONDecodeError:
                        continue
            except OSError:
                break

    def on_key_press(self, event: tk.Event) -> None:
        self.keys.add(event.keysym)

    def on_key_release(self, event: tk.Event) -> None:
        self.keys.discard(event.keysym)

    def game_tick(self) -> None:
        if not self.running:
            return

        self.process_messages_once()
        self.update_local_position()
        self.send_state_if_needed()
        self.render()

        self.root.after(16, self.game_tick)

    def process_messages_once(self) -> None:
        while True:
            try:
                msg = self.recv_queue.get_nowait()
            except queue.Empty:
                return

            mtype = msg.get("type")
            if mtype == "welcome":
                self.player_id = int(msg["player_id"])
            elif mtype == "state":
                self.remote.x = float(msg.get("x", self.remote.x))
                self.remote.y = float(msg.get("y", self.remote.y))
                self.remote.hp = int(msg.get("hp", self.remote.hp))
            elif mtype == "player_joined":
                self.status_var.set("상대가 접속했습니다. 게임 시작!")
            elif mtype == "player_left":
                self.status_var.set("상대가 나갔습니다. 대기 중...")
            elif mtype == "error":
                self.status_var.set(f"서버 에러: {msg.get('message', 'unknown')}")
            elif mtype == "disconnected":
                self.status_var.set("서버와 연결이 끊어졌습니다.")

    def update_local_position(self) -> None:
        if "Left" in self.keys or "a" in self.keys:
            self.local.x -= SPEED
        if "Right" in self.keys or "d" in self.keys:
            self.local.x += SPEED
        if "Up" in self.keys or "w" in self.keys:
            self.local.y -= SPEED
        if "Down" in self.keys or "s" in self.keys:
            self.local.y += SPEED

        self.local.x = max(PLANE_SIZE, min(WIDTH - PLANE_SIZE, self.local.x))
        self.local.y = max(PLANE_SIZE, min(HEIGHT - PLANE_SIZE, self.local.y))

    def send_state_if_needed(self) -> None:
        now = time.time()
        if now - self.last_send < SEND_INTERVAL:
            return
        self.last_send = now

        payload = {
            "type": "state",
            "x": self.local.x,
            "y": self.local.y,
            "hp": self.local.hp,
        }
        try:
            self.sock.sendall((json.dumps(payload) + "\n").encode(ENCODING))
        except OSError:
            self.running = False
            self.status_var.set("서버 전송 실패")

    def render(self) -> None:
        self.canvas.delete("all")
        self.draw_mid_line()
        self.draw_plane(self.local, color="#4ade80", label="나")
        self.draw_plane(self.remote, color="#f87171", label="상대")

    def draw_mid_line(self) -> None:
        for y in range(0, HEIGHT, 20):
            self.canvas.create_line(WIDTH // 2, y, WIDTH // 2, y + 10, fill="#2a3d4d")

    def draw_plane(self, plane: PlaneState, color: str, label: str) -> None:
        x, y = plane.x, plane.y
        points = [
            x,
            y - PLANE_SIZE,
            x - PLANE_SIZE,
            y + PLANE_SIZE,
            x,
            y + PLANE_SIZE // 2,
            x + PLANE_SIZE,
            y + PLANE_SIZE,
        ]
        self.canvas.create_polygon(points, fill=color, outline="white", width=2)
        self.canvas.create_text(x, y + PLANE_SIZE + 14, text=f"{label} HP:{plane.hp}", fill="white")

    def run(self) -> None:
        self.connect()
        self.game_tick()
        self.root.mainloop()

    def close(self) -> None:
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="2인 소켓 비행기 게임 클라이언트")
    parser.add_argument("--host", default="127.0.0.1", help="서버 IP")
    parser.add_argument("--port", type=int, default=5000, help="서버 포트")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    AirplaneGameClient(args.host, args.port).run()
