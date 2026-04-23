#!/usr/bin/env python3
"""2인 소켓 비행기 게임 클라이언트 (10단계 PVP+PVE)."""

from __future__ import annotations

import argparse
import json
import math
import queue
import random
import socket
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass

ENCODING = "utf-8"
WIDTH, HEIGHT = 900, 600
PLAYER_SIZE = 18
ENEMY_SIZE = 16
PLAYER_SPEED = 7
PLAYER_BULLET_SPEED = 11
ENEMY_BULLET_SPEED = 6
SEND_INTERVAL = 0.018
SIM_INTERVAL = 0.01
MAX_LEVEL = 10
COUNTDOWN_SECONDS = 3
POWERUP_DURATION = 15.0
ITEM_FALL_SPEED = 2.4
BOSS_FIRE_INTERVAL_BASE = 1.3
ENEMY_SPREAD_FIRE_INTERVAL = 1.0


@dataclass
class PlayerState:
    player_id: int
    x: float
    y: float
    alive: bool = True
    score: int = 0


@dataclass
class EnemyState:
    eid: int
    x: float
    y: float
    hp: int
    vx: float
    carrier: bool = False
    boss: bool = False


@dataclass
class MissileState:
    owner: str  # p1, p2, enemy
    x: float
    y: float
    vx: float
    vy: float
    homing: bool = False


@dataclass
class ItemState:
    kind: str  # homing
    x: float
    y: float


class AirplaneGameClient:
    def __init__(self, host: str, port: int, mode: str = "multi") -> None:
        self.mode = mode
        self.network_enabled = mode == "multi"
        self.required_players = 2 if self.network_enabled else 1
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) if self.network_enabled else None
        self.recv_queue: queue.Queue[dict] = queue.Queue()
        self.running = True

        self.player_id = 0
        self.connected_players: set[int] = set()

        self.players: dict[int, PlayerState] = {}
        self.remote_input: dict[int, dict] = {1: {}, 2: {}}
        self.local_input: dict[str, bool] = {
            "left": False,
            "right": False,
            "up": False,
            "down": False,
            "fire": False,
        }

        self.enemies: list[EnemyState] = []
        self.missiles: list[MissileState] = []
        self.items: list[ItemState] = []
        self.level = 1
        self.kills_in_level = 0
        self.level_target = self.get_level_target(1)
        self.stage_grunt_total = 0
        self.stage_grunt_killed = 0
        self.boss_spawned = False
        self.stage_item_quota = 1
        self.stage_item_spawned = 0
        self.winner_text = ""
        self.game_over = False
        self.paused = False
        self.game_started = False
        self.countdown_end_ts: float | None = None
        self.countdown_remaining = COUNTDOWN_SECONDS
        self.display_players: dict[int, PlayerState] = {}

        self.last_fire_time = {1: 0.0, 2: 0.0}
        self.homing_until = {1: 0.0, 2: 0.0}
        self.countdown_remaining = COUNTDOWN_SECONDS
        self.last_enemy_fire = 0.0
        self.last_enemy_spread_fire = 0.0
        self.last_boss_fire = 0.0
        self.enemy_id_seed = 1
        self.last_state_send = 0.0
        self.last_input_send = 0.0
        self.last_sim = time.time()

        self.root = tk.Tk()
        self.root.title("2인 비행기 전쟁 (10단계)")
        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg="#061826")
        self.canvas.pack()
        self.player_sprites: dict[int, tk.PhotoImage] = {}
        self.enemy_sprites: dict[int, tk.PhotoImage] = {}
        self.build_sprite_assets()

        self.status_var = tk.StringVar(value="서버 연결 중...")
        tk.Label(self.root, textvariable=self.status_var, anchor="w").pack(fill="x")

        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.bind("<KeyRelease>", self.on_key_release)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def get_level_target(self, level: int) -> int:
        return 5 + (level - 1) * 3

    def build_sprite_assets(self) -> None:
        self.player_sprites[1] = self.make_player_sprite("#ef4444")
        self.player_sprites[2] = self.make_player_sprite("#3b82f6")
        for level in range(1, MAX_LEVEL + 1):
            self.enemy_sprites[level] = self.make_enemy_sprite(level)

    def make_player_sprite(self, primary: str) -> tk.PhotoImage:
        size = 42
        bg = "#061826"
        img = tk.PhotoImage(width=size, height=size)
        img.put(bg, to=(0, 0, size, size))

        # 기수/동체
        for y in range(4, 34):
            half = max(1, (y - 4) // 2)
            cx = size // 2
            img.put(primary, to=(cx - half, y, cx + half + 1, y + 1))
        # 꼬리
        img.put("#e5e7eb", to=(size // 2 - 2, 34, size // 2 + 3, 40))
        # 날개
        img.put(primary, to=(7, 22, 35, 26))
        # 캐노피
        img.put("#f8fafc", to=(size // 2 - 2, 10, size // 2 + 3, 15))
        return img

    def make_enemy_sprite(self, level: int) -> tk.PhotoImage:
        size = 38
        bg = "#061826"
        palette = [
            "#f97316",
            "#f59e0b",
            "#eab308",
            "#84cc16",
            "#22c55e",
            "#14b8a6",
            "#06b6d4",
            "#3b82f6",
            "#8b5cf6",
            "#ec4899",
        ]
        primary = palette[(level - 1) % len(palette)]
        secondary = "#111827"

        img = tk.PhotoImage(width=size, height=size)
        img.put(bg, to=(0, 0, size, size))

        # 단계별 형태 변형 (날개 폭/몸통 높이)
        wing = 9 + (level % 4) * 2
        top = 6 + (level % 3)
        body_h = 20 + (level % 5)
        cx = size // 2

        # 몸통
        img.put(primary, to=(cx - 4, top, cx + 5, top + body_h))
        # 날개
        img.put(primary, to=(cx - wing, top + 9, cx + wing + 1, top + 13))
        # 꼬리
        img.put(primary, to=(cx - 8, top + body_h - 2, cx + 9, top + body_h + 2))
        # 무늬
        stripe_y = top + 4 + (level % 4) * 3
        img.put(secondary, to=(cx - wing + 2, stripe_y, cx + wing - 1, stripe_y + 2))
        img.put("#f8fafc", to=(cx - 2, top + 2, cx + 3, top + 6))
        return img

    def init_players(self) -> None:
        self.players = {1: PlayerState(1, WIDTH * 0.25, HEIGHT - 60)}
        self.display_players = {1: PlayerState(1, WIDTH * 0.25, HEIGHT - 60)}
        if self.network_enabled:
            self.players[2] = PlayerState(2, WIDTH * 0.75, HEIGHT - 60)
            self.display_players[2] = PlayerState(2, WIDTH * 0.75, HEIGHT - 60)

    def connect(self) -> None:
        if not self.network_enabled:
            self.player_id = 1
            self.connected_players = {1}
            self.init_players()
            self.try_schedule_start_countdown("싱글플레이")
            self.status_var.set("싱글플레이 준비 완료")
            return

        self.sock.connect((self.host, self.port))
        threading.Thread(target=self.recv_loop, daemon=True).start()

        deadline = time.time() + 5
        while self.player_id == 0 and time.time() < deadline:
            self.process_messages_once()
            time.sleep(0.01)

        if self.player_id == 0:
            raise RuntimeError("서버에서 welcome 메시지를 받지 못했습니다.")

        side_text = "왼쪽" if self.player_id == 1 else "오른쪽"
        self.status_var.set(f"연결됨: 내 비행기={self.player_id}번 ({side_text})")

        if self.player_id == 1:
            self.try_schedule_start_countdown("초기 접속")

    def recv_loop(self) -> None:
        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(8192)
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
                        self.recv_queue.put(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except OSError:
                break

    def on_key_press(self, event: tk.Event) -> None:
        k = event.keysym.lower()
        if k in ("left", "a"):
            self.local_input["left"] = True
        elif k in ("right", "d"):
            self.local_input["right"] = True
        elif k in ("up", "w"):
            self.local_input["up"] = True
        elif k in ("down", "s"):
            self.local_input["down"] = True
        elif k in ("space", "return"):
            self.local_input["fire"] = True
        elif k == "p":
            if self.network_enabled:
                self.send_control("toggle_pause")
            elif self.game_started and not self.game_over:
                self.paused = not self.paused
        elif k == "r":
            if self.network_enabled:
                self.send_control("restart")
            else:
                self.reset_match_state()
                self.try_schedule_start_countdown("재시작")

    def on_key_release(self, event: tk.Event) -> None:
        k = event.keysym.lower()
        if k in ("left", "a"):
            self.local_input["left"] = False
        elif k in ("right", "d"):
            self.local_input["right"] = False
        elif k in ("up", "w"):
            self.local_input["up"] = False
        elif k in ("down", "s"):
            self.local_input["down"] = False
        elif k in ("space", "return"):
            self.local_input["fire"] = False

    def send_control(self, action: str) -> None:
        if not self.network_enabled:
            return
        self.safe_send({"type": "control", "action": action})

    def game_tick(self) -> None:
        if not self.running:
            return

        self.process_messages_once()
        self.send_input_if_needed()

        if self.player_id == 1:
            self.host_simulate()
            self.send_world_state_if_needed()

        self.render()
        self.root.after(10, self.game_tick)

    def process_messages_once(self) -> None:
        while True:
            try:
                msg = self.recv_queue.get_nowait()
            except queue.Empty:
                return

            mtype = msg.get("type")
            if mtype == "welcome":
                self.player_id = int(msg["player_id"])
                self.connected_players = set(int(v) for v in msg.get("connected_players", [self.player_id]))
                self.init_players()
            elif mtype == "input":
                pid = int(msg.get("from", 0))
                if pid in (1, 2):
                    self.remote_input[pid] = {
                        "left": bool(msg.get("left")),
                        "right": bool(msg.get("right")),
                        "up": bool(msg.get("up")),
                        "down": bool(msg.get("down")),
                        "fire": bool(msg.get("fire")),
                    }
            elif mtype == "control":
                if self.player_id == 1:
                    self.handle_control_message(msg)
            elif mtype == "countdown":
                self.countdown_end_ts = float(msg.get("end_ts", 0.0))
                self.countdown_remaining = int(msg.get("countdown_remaining", COUNTDOWN_SECONDS))
                self.game_started = False
                self.paused = False
                self.game_over = False
                self.winner_text = ""
            elif mtype == "world_state":
                if self.player_id != 1:
                    self.apply_world_state(msg)
            elif mtype == "player_joined":
                pid = int(msg.get("player_id", 0))
                if pid:
                    self.connected_players.add(pid)
                self.status_var.set("상대가 접속했습니다. 카운트다운 준비...")
                if self.player_id == 1:
                    self.try_schedule_start_countdown("플레이어 입장")
            elif mtype == "player_left":
                pid = int(msg.get("player_id", 0))
                if pid in self.connected_players:
                    self.connected_players.remove(pid)
                self.status_var.set("상대가 나갔습니다. 대기 중...")
                self.game_started = False
                self.paused = True
            elif mtype == "error":
                self.status_var.set(f"서버 에러: {msg.get('message', 'unknown')}")
            elif mtype == "disconnected":
                self.status_var.set("서버와 연결이 끊어졌습니다.")

    def handle_control_message(self, msg: dict) -> None:
        action = msg.get("action")
        if action == "toggle_pause" and self.game_started and not self.game_over:
            self.paused = not self.paused
            state = "일시정지" if self.paused else "재시작"
            self.status_var.set(f"게임 {state}")
        elif action == "restart":
            self.reset_match_state()
            self.try_schedule_start_countdown("재시작")

    def try_schedule_start_countdown(self, reason: str) -> None:
        if len(self.connected_players) < self.required_players:
            self.status_var.set("2명 접속 대기 중..." if self.network_enabled else "싱글플레이 준비 중...")
            return

        self.reset_match_state()
        self.countdown_end_ts = time.time() + COUNTDOWN_SECONDS
        self.status_var.set(f"{reason}: {COUNTDOWN_SECONDS}초 후 시작")
        self.countdown_remaining = COUNTDOWN_SECONDS
        self.safe_send({"type": "countdown", "end_ts": self.countdown_end_ts, "countdown_remaining": COUNTDOWN_SECONDS})

    def reset_match_state(self) -> None:
        self.init_players()
        self.enemies.clear()
        self.missiles.clear()
        self.items.clear()
        self.level = 1
        self.kills_in_level = 0
        self.level_target = self.get_level_target(1)
        self.init_stage_state()
        self.stage_item_quota = 1
        self.stage_item_spawned = 0
        self.winner_text = ""
        self.game_over = False
        self.paused = False
        self.game_started = False
        self.last_enemy_fire = 0.0
        self.last_enemy_spread_fire = 0.0
        self.last_boss_fire = 0.0
        self.enemy_id_seed = 1
        self.last_fire_time = {1: 0.0, 2: 0.0}
        self.homing_until = {1: 0.0, 2: 0.0}
        self.countdown_remaining = COUNTDOWN_SECONDS

    def init_stage_state(self) -> None:
        self.stage_grunt_total = 6 + self.level * 2
        self.stage_grunt_killed = 0
        self.boss_spawned = False

    def send_input_if_needed(self) -> None:
        if not self.network_enabled:
            return
        now = time.time()
        if now - self.last_input_send < SEND_INTERVAL:
            return
        self.last_input_send = now

        payload = {"type": "input", **self.local_input}
        self.safe_send(payload)

    def host_simulate(self) -> None:
        now = time.time()
        dt = now - self.last_sim
        if dt < SIM_INTERVAL:
            return
        dt = min(dt, 0.033)
        self.last_sim = now

        if len(self.connected_players) < self.required_players:
            return

        if not self.game_started:
            if self.countdown_end_ts is None:
                return
            remain = self.countdown_end_ts - time.time()
            if remain > 0:
                self.countdown_remaining = int(math.ceil(remain))
                self.status_var.set(f"모든 플레이어 입장 완료. {self.countdown_remaining}초 후 시작")
                return

            self.game_started = True
            self.countdown_remaining = 0
            self.spawn_level_enemies(reset=True)
            self.status_var.set("게임 시작!")

        if self.game_over or self.paused:
            return

        self.remote_input[self.player_id] = dict(self.local_input)
        self.update_players(dt)
        self.update_enemies(dt)
        self.update_missiles(dt)
        self.update_items(dt)
        self.handle_collisions()
        self.check_level_progress()

    def update_players(self, dt: float) -> None:
        for pid, p in self.players.items():
            if not p.alive:
                continue
            inp = self.remote_input.get(pid, {})
            speed = PLAYER_SPEED * dt * 60
            if inp.get("left"):
                p.x -= speed
            if inp.get("right"):
                p.x += speed
            if inp.get("up"):
                p.y -= speed
            if inp.get("down"):
                p.y += speed
            p.x = max(PLAYER_SIZE, min(WIDTH - PLAYER_SIZE, p.x))
            p.y = max(PLAYER_SIZE + 80, min(HEIGHT - PLAYER_SIZE, p.y))

            if inp.get("fire"):
                self.spawn_player_bullet(pid)

    def spawn_player_bullet(self, pid: int) -> None:
        now = time.time()
        if now - self.last_fire_time[pid] < 0.22:
            return
        self.last_fire_time[pid] = now

        p = self.players[pid]
        if not p.alive:
            return
        homing = time.time() < self.homing_until.get(pid, 0.0)
        self.missiles.append(
            MissileState(owner=f"p{pid}", x=p.x, y=p.y - PLAYER_SIZE, vx=0, vy=-PLAYER_BULLET_SPEED, homing=homing)
        )

    def update_enemies(self, dt: float) -> None:
        for e in self.enemies:
            e.x += e.vx * dt * 60
            if e.x < ENEMY_SIZE or e.x > WIDTH - ENEMY_SIZE:
                e.vx *= -1
                e.y += 15

        # 화면 아래로 완전히 내려간 적은 제거해서 다음 웨이브가 정상 생성되게 함
        self.enemies = [e for e in self.enemies if e.y < HEIGHT + ENEMY_SIZE and e.hp > 0]

        now = time.time()
        bosses = [e for e in self.enemies if e.boss and e.hp > 0]
        grunts = [e for e in self.enemies if (not e.boss) and e.hp > 0]

        # 일반 적 기본 사격
        if now - self.last_enemy_fire > max(0.45, 1.15 - self.level * 0.07):
            self.last_enemy_fire = now
            if grunts:
                shooter = random.choice(grunts)
                self.fire_enemy_aimed(shooter)

        # 졸병 절반 처치 이후 일반 적 랜덤 퍼짐 사격
        if self.stage_grunt_killed >= max(1, self.stage_grunt_total // 2):
            if now - self.last_enemy_spread_fire > ENEMY_SPREAD_FIRE_INTERVAL:
                self.last_enemy_spread_fire = now
                if grunts:
                    shooter = random.choice(grunts)
                    spread_count = 2 + self.level // 3
                    self.fire_spread_burst(shooter.x, shooter.y + ENEMY_SIZE, spread_count, spread_deg=70, speed=ENEMY_BULLET_SPEED)

        # 보스 불꽃 퍼짐 미사일
        if bosses:
            interval = max(0.35, BOSS_FIRE_INTERVAL_BASE - self.level * 0.06)
            if now - self.last_boss_fire > interval:
                self.last_boss_fire = now
                boss = bosses[0]
                flame_count = 3 + self.level  # 단계별 1개씩 증가
                self.fire_spread_burst(boss.x, boss.y + ENEMY_SIZE, flame_count, spread_deg=110, speed=ENEMY_BULLET_SPEED + 1.2)

    def fire_enemy_aimed(self, shooter: EnemyState) -> None:
        target = self.pick_target_player(shooter)
        dx = target.x - shooter.x
        dy = max(1.0, target.y - shooter.y)
        mag = math.sqrt(dx * dx + dy * dy)
        vx = ENEMY_BULLET_SPEED * dx / mag
        vy = ENEMY_BULLET_SPEED * dy / mag
        self.missiles.append(MissileState(owner="enemy", x=shooter.x, y=shooter.y + ENEMY_SIZE, vx=vx, vy=vy))

    def fire_spread_burst(self, x: float, y: float, count: int, spread_deg: float, speed: float) -> None:
        if count <= 1:
            self.missiles.append(MissileState(owner="enemy", x=x, y=y, vx=0.0, vy=speed))
            return
        start = -spread_deg / 2.0
        step = spread_deg / (count - 1)
        for i in range(count):
            angle_deg = start + step * i
            rad = math.radians(angle_deg)
            vx = math.sin(rad) * speed
            vy = math.cos(rad) * speed
            self.missiles.append(MissileState(owner="enemy", x=x, y=y, vx=vx, vy=vy))

    def pick_target_player(self, shooter: EnemyState) -> PlayerState:
        candidates = [p for p in self.players.values() if p.alive]
        if not candidates:
            return self.players[1]
        return min(candidates, key=lambda p: abs(p.x - shooter.x) + abs(p.y - shooter.y))

    def update_missiles(self, dt: float) -> None:
        for m in self.missiles:
            if m.homing and m.owner.startswith("p"):
                target = self.pick_nearest_enemy(m.x, m.y)
                if target is not None:
                    dx = target.x - m.x
                    dy = target.y - m.y
                    mag = max(1.0, math.sqrt(dx * dx + dy * dy))
                    desired_vx = PLAYER_BULLET_SPEED * dx / mag
                    desired_vy = PLAYER_BULLET_SPEED * dy / mag
                    turn = 0.28
                    m.vx += (desired_vx - m.vx) * turn
                    m.vy += (desired_vy - m.vy) * turn
            m.x += m.vx * dt * 60
            m.y += m.vy * dt * 60
        self.missiles = [m for m in self.missiles if -30 < m.x < WIDTH + 30 and -30 < m.y < HEIGHT + 30]

    def pick_nearest_enemy(self, x: float, y: float) -> EnemyState | None:
        living = [e for e in self.enemies if e.hp > 0]
        if not living:
            return None
        return min(living, key=lambda e: abs(e.x - x) + abs(e.y - y))

    def update_items(self, dt: float) -> None:
        active: list[ItemState] = []
        for item in self.items:
            item.y += ITEM_FALL_SPEED * dt * 60
            collected = False
            for pid, p in self.players.items():
                if not p.alive:
                    continue
                if abs(item.x - p.x) < 24 and abs(item.y - p.y) < 24:
                    if item.kind == "homing":
                        self.homing_until[pid] = time.time() + POWERUP_DURATION
                    collected = True
                    break
            if not collected and item.y < HEIGHT + 40:
                active.append(item)
        self.items = active

    def handle_collisions(self) -> None:
        kept_missiles: list[MissileState] = []
        for m in self.missiles:
            hit = False
            if m.owner.startswith("p"):
                for e in self.enemies:
                    if e.hp <= 0:
                        continue
                    if abs(m.x - e.x) < ENEMY_SIZE and abs(m.y - e.y) < ENEMY_SIZE:
                        e.hp -= 1
                        hit = True
                        if e.hp <= 0:
                            killer = int(m.owner[1])
                            self.on_enemy_destroyed(e, killer)
                        break
            else:
                for p in self.players.values():
                    if not p.alive:
                        continue
                    if abs(m.x - p.x) < PLAYER_SIZE and abs(m.y - p.y) < PLAYER_SIZE:
                        p.alive = False
                        hit = True
                        self.finish_game(reason=f"플레이어 {p.player_id} 피격")
                        break

            if not hit:
                kept_missiles.append(m)

        self.missiles = kept_missiles
        self.enemies = [e for e in self.enemies if e.hp > 0]

    def on_enemy_destroyed(self, enemy: EnemyState, killer: int) -> None:
        bonus = 3 if enemy.boss else 1
        self.players[killer].score += bonus
        self.kills_in_level += bonus
        if not enemy.boss:
            self.stage_grunt_killed += 1
        if enemy.carrier and self.stage_item_spawned < self.stage_item_quota:
            self.items.append(ItemState(kind="homing", x=enemy.x, y=enemy.y))
            self.stage_item_spawned += 1

    def check_level_progress(self) -> None:
        if self.game_over:
            return
        boss_alive = any(e.boss and e.hp > 0 for e in self.enemies)
        grunts_alive = any((not e.boss) and e.hp > 0 for e in self.enemies)

        # 졸병 전멸 후 보스 등장
        if self.stage_grunt_killed >= self.stage_grunt_total and not boss_alive and not self.boss_spawned:
            self.spawn_boss_enemy()
            self.boss_spawned = True
            return

        # 졸병이 남았는데 화면에 없으면 다음 웨이브 보충
        if self.stage_grunt_killed < self.stage_grunt_total and not grunts_alive:
            self.spawn_level_enemies(reset=False)
            return

        # 보스 처치 시 다음 단계
        if self.boss_spawned and not boss_alive:
            if self.level >= MAX_LEVEL:
                self.finish_game(reason="10단계 보스 클리어")
                return
            self.level += 1
            self.kills_in_level = 0
            self.level_target = self.get_level_target(self.level)
            self.init_stage_state()
            self.stage_item_quota = self.level
            self.stage_item_spawned = 0
            self.enemies.clear()
            self.spawn_level_enemies(reset=True)

    def spawn_level_enemies(self, reset: bool) -> None:
        if reset:
            self.enemies.clear()
        if self.boss_spawned:
            return

        remaining = max(0, self.stage_grunt_total - self.stage_grunt_killed)
        if remaining == 0:
            return

        base_count = 4 + self.level * 2
        count = min(base_count, remaining)
        hp = 1 if self.level <= 3 else (2 if self.level <= 7 else 3)
        min_y, max_y = (70, 220) if reset else (60, 180)
        remaining_carriers = max(0, self.stage_item_quota - self.stage_item_spawned)

        for idx in range(count):
            x = random.randint(ENEMY_SIZE + 10, WIDTH - ENEMY_SIZE - 10)
            y = random.randint(min_y, max_y)
            vx = random.choice([-1, 1]) * (1.2 + self.level * 0.15)
            carrier = idx < remaining_carriers
            self.enemies.append(EnemyState(eid=self.enemy_id_seed, x=x, y=y, hp=hp, vx=vx, carrier=carrier))
            self.enemy_id_seed += 1

    def spawn_boss_enemy(self) -> None:
        boss_hp = 8 + self.level * 3
        self.enemies.append(
            EnemyState(
                eid=self.enemy_id_seed,
                x=WIDTH / 2,
                y=110,
                hp=boss_hp,
                vx=2.2 + self.level * 0.15,
                carrier=False,
                boss=True,
            )
        )
        self.enemy_id_seed += 1

    def finish_game(self, reason: str) -> None:
        if self.game_over:
            return
        self.game_over = True

        p1 = self.players[1]
        if not self.network_enabled:
            self.winner_text = f"{reason} | 싱글플레이 최종 점수: {p1.score}"
            self.status_var.set(self.winner_text)
            return

        p2 = self.players[2]
        if p1.score > p2.score:
            winner = "플레이어 1 승리"
        elif p2.score > p1.score:
            winner = "플레이어 2 승리"
        else:
            winner = "무승부"

        self.winner_text = f"{reason} | 결과: {winner} (P1:{p1.score} / P2:{p2.score})"
        self.status_var.set(self.winner_text)

    def send_world_state_if_needed(self) -> None:
        if not self.network_enabled:
            return
        now = time.time()
        if now - self.last_state_send < SEND_INTERVAL:
            return
        self.last_state_send = now

        payload = {
            "type": "world_state",
            "players": {str(pid): asdict(p) for pid, p in self.players.items()},
            "enemies": [asdict(e) for e in self.enemies],
            "missiles": [asdict(m) for m in self.missiles],
            "items": [asdict(i) for i in self.items],
            "level": self.level,
            "kills_in_level": self.kills_in_level,
            "level_target": self.level_target,
            "stage_grunt_total": self.stage_grunt_total,
            "stage_grunt_killed": self.stage_grunt_killed,
            "boss_spawned": self.boss_spawned,
            "stage_item_quota": self.stage_item_quota,
            "stage_item_spawned": self.stage_item_spawned,
            "homing_until": self.homing_until,
            "game_over": self.game_over,
            "winner_text": self.winner_text,
            "paused": self.paused,
            "game_started": self.game_started,
            "countdown_end_ts": self.countdown_end_ts,
            "countdown_remaining": self.countdown_remaining,
        }
        self.safe_send(payload)

    def apply_world_state(self, msg: dict) -> None:
        pmap = msg.get("players", {})
        if pmap:
            for key, pdata in pmap.items():
                pid = int(key)
                self.players[pid] = PlayerState(**pdata)

        self.enemies = [EnemyState(**e) for e in msg.get("enemies", [])]
        self.missiles = [MissileState(**m) for m in msg.get("missiles", [])]
        self.items = [ItemState(**i) for i in msg.get("items", [])]
        self.level = int(msg.get("level", self.level))
        self.kills_in_level = int(msg.get("kills_in_level", self.kills_in_level))
        self.level_target = int(msg.get("level_target", self.level_target))
        self.stage_grunt_total = int(msg.get("stage_grunt_total", self.stage_grunt_total))
        self.stage_grunt_killed = int(msg.get("stage_grunt_killed", self.stage_grunt_killed))
        self.boss_spawned = bool(msg.get("boss_spawned", self.boss_spawned))
        self.stage_item_quota = int(msg.get("stage_item_quota", self.stage_item_quota))
        self.stage_item_spawned = int(msg.get("stage_item_spawned", self.stage_item_spawned))
        homing_until = msg.get("homing_until", self.homing_until)
        self.homing_until = {int(k): float(v) for k, v in homing_until.items()}
        self.game_over = bool(msg.get("game_over", False))
        self.winner_text = msg.get("winner_text", "")
        self.paused = bool(msg.get("paused", False))
        self.game_started = bool(msg.get("game_started", False))
        self.countdown_end_ts = msg.get("countdown_end_ts", self.countdown_end_ts)
        self.countdown_remaining = int(msg.get("countdown_remaining", self.countdown_remaining))
        if self.winner_text:
            self.status_var.set(self.winner_text)

    def safe_send(self, payload: dict) -> None:
        if not self.network_enabled or self.sock is None:
            return
        try:
            self.sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode(ENCODING))
        except OSError:
            self.running = False
            self.status_var.set("서버 전송 실패")

    def render(self) -> None:
        self.canvas.delete("all")
        self.update_display_positions()
        self.draw_stars()
        self.draw_hud()

        for e in self.enemies:
            self.draw_enemy(e)
        for item in self.items:
            self.draw_item(item)
        for m in self.missiles:
            self.draw_missile(m)
        for pid in sorted(self.players.keys()):
            self.draw_player(self.display_players.get(pid, self.players[pid]), pid == self.player_id)

        self.draw_overlay()

    def update_display_positions(self) -> None:
        for pid, p in self.players.items():
            d = self.display_players.get(pid)
            if d is None:
                self.display_players[pid] = PlayerState(p.player_id, p.x, p.y, p.alive, p.score)
                continue

            # 호스트는 즉시 반영, 원격은 보간으로 부드럽게 이동
            alpha = 1.0 if self.player_id == 1 else 0.38
            d.x += (p.x - d.x) * alpha
            d.y += (p.y - d.y) * alpha
            d.alive = p.alive
            d.score = p.score

    def draw_overlay(self) -> None:
        if self.game_over:
            self.canvas.create_rectangle(130, 250, WIDTH - 130, 340, fill="#000000", outline="white")
            self.canvas.create_text(WIDTH // 2, 295, text="GAME OVER", fill="#fbbf24", font=("Arial", 28, "bold"))
            self.canvas.create_text(WIDTH // 2, 322, text=self.winner_text, fill="white", font=("Arial", 12))
            return

        if self.paused and self.game_started:
            self.canvas.create_rectangle(250, 260, WIDTH - 250, 320, fill="#000000", outline="white")
            self.canvas.create_text(WIDTH // 2, 290, text="PAUSED (P:재개 / R:재시작)", fill="#f9fafb", font=("Arial", 16, "bold"))
            return

        if not self.game_started:
            remain = self.countdown_remaining
            msg = ("2명 접속 대기 중" if self.network_enabled else "싱글플레이 준비 중") if len(self.connected_players) < self.required_players else f"{remain}초 후 시작"
            self.canvas.create_rectangle(280, 260, WIDTH - 280, 320, fill="#000000", outline="white")
            self.canvas.create_text(WIDTH // 2, 290, text=msg, fill="#f9fafb", font=("Arial", 16, "bold"))

    def draw_stars(self) -> None:
        for x in range(10, WIDTH, 40):
            y = (x * 17) % HEIGHT
            self.canvas.create_oval(x, y, x + 2, y + 2, fill="#7dd3fc", outline="")

    def draw_hud(self) -> None:
        p1 = self.players.get(1, PlayerState(1, 0, 0))
        p2 = self.players.get(2)
        score_text = (
            f"Stage {self.level}/{MAX_LEVEL} | 졸병 처치: {self.stage_grunt_killed}/{self.stage_grunt_total}"
            f" | P1 점수:{p1.score} ({'생존' if p1.alive else '사망'})"
        )
        if p2 is not None:
            score_text += f" | P2 점수:{p2.score} ({'생존' if p2.alive else '사망'})"
        boss_alive = any(e.boss for e in self.enemies)
        boss_status = "보스 출현" if boss_alive else ("보스 대기" if not self.boss_spawned else "보스 처치")
        score_text += (
            f" | {boss_status} | 아이템:{self.stage_item_spawned}/{self.stage_item_quota}"
            f" | 접속:{len(self.connected_players)}/{self.required_players}"
        )

        now = time.time()
        p1_buff = max(0, int(self.homing_until.get(1, 0.0) - now))
        buff_text = f"유도미사일 P1:{p1_buff}s"
        if p2 is not None:
            p2_buff = max(0, int(self.homing_until.get(2, 0.0) - now))
            buff_text += f" / P2:{p2_buff}s"
        self.canvas.create_text(
            10,
            10,
            anchor="nw",
            fill="white",
            text=score_text,
        )
        self.canvas.create_text(
            10,
            34,
            anchor="nw",
            fill="#fcd34d",
            text=(
                f"모드:{'멀티' if self.network_enabled else '싱글'} | "
                f"{buff_text} | 조작: 이동(WASD/방향키), 발사(Space), 일시정지(P), 재시작(R)"
            ),
        )

    def draw_player(self, p: PlayerState, is_me: bool) -> None:
        x, y = p.x, p.y
        body_color = "#ef4444" if p.player_id == 1 else "#3b82f6"
        wing_color = "#cbd5e1"
        if not p.alive:
            body_color = "#6b7280"
            wing_color = "#9ca3af"

        # 사각 프레임 이미지 대신 실제 비행기 형태로 직접 렌더링
        fuselage = [
            x,
            y - 24,
            x - 9,
            y + 10,
            x,
            y + 22,
            x + 9,
            y + 10,
        ]
        left_wing = [x - 9, y + 4, x - 28, y + 14, x - 10, y + 16]
        right_wing = [x + 9, y + 4, x + 28, y + 14, x + 10, y + 16]
        tail = [x - 5, y + 18, x, y + 30, x + 5, y + 18]

        self.canvas.create_polygon(fuselage, fill=body_color, outline="white", width=2)
        self.canvas.create_polygon(left_wing, fill=wing_color, outline="white", width=1)
        self.canvas.create_polygon(right_wing, fill=wing_color, outline="white", width=1)
        self.canvas.create_polygon(tail, fill=wing_color, outline="white", width=1)
        self.canvas.create_oval(x - 3, y - 8, x + 3, y - 2, fill="#f8fafc", outline="")
        if not p.alive:
            self.canvas.create_oval(x - 20, y - 20, x + 20, y + 20, outline="#6b7280", width=3)
        tag = "나" if is_me else f"상대(P{p.player_id})"
        self.canvas.create_text(x, y + PLAYER_SIZE + 14, text=tag, fill="white")

    def draw_enemy(self, e: EnemyState) -> None:
        x, y = e.x, e.y
        sprite = self.enemy_sprites.get(self.level, self.enemy_sprites[MAX_LEVEL])
        self.canvas.create_image(x, y, image=sprite)
        if e.boss:
            self.canvas.create_oval(x - 34, y - 34, x + 34, y + 34, outline="#f43f5e", width=3)
            self.canvas.create_text(x, y - 28, text="BOSS", fill="#fecdd3", font=("Arial", 10, "bold"))
        if e.carrier:
            self.canvas.create_oval(x - 22, y - 22, x + 22, y + 22, outline="#fde047", width=2)
        self.canvas.create_text(x, y, text=str(e.hp), fill="white")

    def draw_item(self, item: ItemState) -> None:
        x, y = item.x, item.y
        if item.kind == "homing":
            self.canvas.create_oval(x - 10, y - 10, x + 10, y + 10, fill="#22d3ee", outline="#e0f2fe", width=2)
            self.canvas.create_text(x, y, text="H", fill="#082f49", font=("Arial", 10, "bold"))

    def draw_missile(self, m: MissileState) -> None:
        color = "#a78bfa"
        if m.owner == "p1":
            color = "#ef4444"
        elif m.owner == "p2":
            color = "#3b82f6"
        self.canvas.create_oval(m.x - 3, m.y - 6, m.x + 3, m.y + 6, fill=color, outline="")

    def run(self) -> None:
        self.connect()
        self.game_tick()
        self.root.mainloop()

    def close(self) -> None:
        self.running = False
        try:
            if self.sock is not None:
                self.sock.close()
        except OSError:
            pass
        self.root.destroy()



def choose_game_mode() -> str:
    selected = {"mode": "multi"}

    root = tk.Tk()
    root.title("게임 모드 선택")
    root.geometry("320x170")
    root.resizable(False, False)

    tk.Label(root, text="플레이 모드를 선택하세요", font=("Arial", 13, "bold")).pack(pady=16)

    def set_mode(mode: str) -> None:
        selected["mode"] = mode
        root.destroy()

    tk.Button(root, text="싱글플레이", width=20, command=lambda: set_mode("single")).pack(pady=6)
    tk.Button(root, text="2인 멀티플레이", width=20, command=lambda: set_mode("multi")).pack(pady=6)

    root.mainloop()
    return selected["mode"]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="2인 소켓 비행기 게임 클라이언트")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--single", action="store_true", help="싱글플레이로 즉시 시작 (서버 불필요)")
    mode_group.add_argument("--multi", action="store_true", help="멀티플레이로 즉시 시작 (서버 필요)")
    parser.add_argument("--host", default="", help="서버 IP (미입력 시 실행 중에 질문)")
    parser.add_argument("--port", type=int, default=5000, help="서버 포트")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.single:
        mode = "single"
    elif args.multi:
        mode = "multi"
    else:
        mode = choose_game_mode()

    host = args.host.strip()
    if mode == "multi" and not host:
        try:
            entered = input("서버 IP를 입력하세요 (엔터=127.0.0.1): ").strip()
            host = entered or "127.0.0.1"
        except EOFError:
            host = "127.0.0.1"

    if mode == "single" and not host:
        host = "127.0.0.1"

    AirplaneGameClient(host, args.port, mode=mode).run()
