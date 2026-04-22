#!/usr/bin/env python3
"""2인 비행기 게임용 소켓 중계 서버.

- 최대 2명의 클라이언트를 연결합니다.
- 각 클라이언트에 player_id(1 또는 2)를 부여합니다.
- 클라이언트가 보낸 JSON 라인 메시지를 상대에게 그대로 중계합니다.
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
from dataclasses import dataclass
from typing import Optional

ENCODING = "utf-8"


@dataclass
class Peer:
    conn: socket.socket
    addr: tuple[str, int]
    player_id: int


class RelayServer:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lock = threading.Lock()
        self.peers: dict[int, Peer] = {}

    def start(self) -> None:
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(2)
        print(f"[SERVER] Listening on {self.host}:{self.port}")

        try:
            while True:
                conn, addr = self.server_sock.accept()
                with self.lock:
                    if len(self.peers) >= 2:
                        conn.sendall(
                            (json.dumps({"type": "error", "message": "방이 가득 찼습니다."}) + "\n").encode(ENCODING)
                        )
                        conn.close()
                        continue

                    player_id = 1 if 1 not in self.peers else 2
                    peer = Peer(conn=conn, addr=addr, player_id=player_id)
                    self.peers[player_id] = peer

                print(f"[SERVER] Player {player_id} connected from {addr}")
                conn.sendall((json.dumps({"type": "welcome", "player_id": player_id}) + "\n").encode(ENCODING))

                self.broadcast(
                    {
                        "type": "player_joined",
                        "player_id": player_id,
                    },
                    exclude=player_id,
                )

                th = threading.Thread(target=self.handle_client, args=(peer,), daemon=True)
                th.start()
        finally:
            self.server_sock.close()

    def handle_client(self, peer: Peer) -> None:
        conn = peer.conn
        buffer = ""
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode(ENCODING)

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    payload.setdefault("from", peer.player_id)
                    self.broadcast(payload, exclude=peer.player_id)
        except ConnectionError:
            pass
        finally:
            self.remove_peer(peer.player_id)
            try:
                conn.close()
            except OSError:
                pass

    def remove_peer(self, player_id: int) -> None:
        removed = None
        with self.lock:
            removed = self.peers.pop(player_id, None)
        if removed:
            print(f"[SERVER] Player {player_id} disconnected")
            self.broadcast({"type": "player_left", "player_id": player_id}, exclude=player_id)

    def broadcast(self, payload: dict, exclude: Optional[int] = None) -> None:
        message = (json.dumps(payload, ensure_ascii=False) + "\n").encode(ENCODING)
        with self.lock:
            targets = list(self.peers.values())

        for target in targets:
            if exclude is not None and target.player_id == exclude:
                continue
            try:
                target.conn.sendall(message)
            except OSError:
                self.remove_peer(target.player_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="2인 비행기 게임 중계 서버")
    parser.add_argument("--host", default="0.0.0.0", help="바인딩할 IP (기본값: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="바인딩할 포트 (기본값: 5000)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    RelayServer(args.host, args.port).start()
