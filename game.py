"""게임 판정 로직 (네트워크와 무관한 순수 파이썬).

서버가 상태와 판정을 단독 관리한다. 시간은 모든 메서드에 `now`(초)로 주입해서
테스트에서 시계를 제어할 수 있게 한다.
"""
from __future__ import annotations

import json
import random
import secrets
from dataclasses import dataclass, field
from pathlib import Path

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 0, O, 1, I 제외
CODE_LENGTH = 6

MAP_SIDE = 8                # 정사각형 8x8 = 64칸
SELECT_TIME = 20.0          # 칸 선택 후 입력 제한 시간(초)
STAR_WEIGHTS = ((1, 50), (2, 30), (3, 20))
POINTS_PER_STAR = 10
DEFAULT_DURATION = 300      # 5분
MIN_DURATION, MAX_DURATION = 180, 600
MAX_PLAYERS = 9
MIN_PLAYERS_TO_START = 1    # 프로토타입: 혼자서도 테스트 가능 (PRD 개인전은 2~9명)
ENDED_ROOM_TTL = 30 * 60
EMPTY_ROOM_TTL = 30 * 60

# 색약 친화 팔레트(Okabe-Ito 기반) 9색. 최종 팔레트는 디자인 단계에서 조정.
COLORS = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2",
          "#D55E00", "#CC79A7", "#B8B8FF", "#FF8A8A"]
CHARACTERS = ["cat", "dog", "bird", "fish", "rabbit", "turtle", "ghost", "bot", "rocket"]

QUESTIONS_PATH = Path(__file__).parent / "data" / "questions.json"


class GameError(Exception):
    """사용자에게 보여줄 수 있는 오류."""


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Player:
    token: str
    pid: str
    nickname: str
    character: str
    color: str
    sid: str | None = None
    connected: bool = True
    cursor: int = 0              # 0..63
    selected: int | None = None  # 선택 중인 칸
    select_deadline: float = 0.0
    command: str | None = None
    captures: int = 0
    last_score_time: float | None = None


@dataclass
class Cell:
    stars: int
    owner: str | None = None     # 소유자 pid
    locked_by: str | None = None  # 선택 중인 pid


@dataclass
class Room:
    code: str
    host_token: str
    questions: list[dict]
    duration: int = DEFAULT_DURATION
    state: str = "lobby"         # lobby | playing | ended
    players: dict[str, Player] = field(default_factory=dict)  # token -> Player
    cells: list[Cell] = field(default_factory=list)
    started_at: float = 0.0
    ends_at: float = 0.0
    ended_at: float | None = None
    created_at: float = 0.0
    last_active: float = 0.0
    rng: random.Random = field(default_factory=random.Random)
    _bag: list[dict] = field(default_factory=list)

    # ---------- 로비 ----------
    def join(self, nickname: str, character: str, color: str, now: float) -> Player:
        if self.state != "lobby":
            raise GameError("이미 게임이 시작되어 입장할 수 없어요.")
        nickname = (nickname or "").strip()
        if not 1 <= len(nickname) <= 12:
            raise GameError("닉네임은 1~12자로 입력하세요.")
        if len(self.players) >= MAX_PLAYERS:
            raise GameError("방이 가득 찼어요.")
        if any(p.nickname == nickname for p in self.players.values()):
            raise GameError("이미 사용 중인 닉네임이에요.")
        if character not in CHARACTERS:
            raise GameError("캐릭터를 선택하세요.")
        if color not in COLORS:
            raise GameError("색상을 선택하세요.")
        if any(p.color == color for p in self.players.values()):
            raise GameError("이미 다른 사람이 고른 색이에요.")
        token = secrets.token_urlsafe(16)
        p = Player(token=token, pid=f"p{len(self.players) + 1}-{secrets.token_hex(2)}",
                   nickname=nickname, character=character, color=color)
        self.players[token] = p
        self.last_active = now
        return p

    def kick(self, pid: str) -> None:
        for token, p in list(self.players.items()):
            if p.pid == pid:
                self._release(p)
                del self.players[token]
                return

    def start(self, now: float) -> None:
        if self.state != "lobby":
            raise GameError("이미 시작된 방이에요.")
        if len(self.players) < MIN_PLAYERS_TO_START:
            raise GameError("참가자가 없어요.")
        weights = [w for _, w in STAR_WEIGHTS]
        stars = [s for s, _ in STAR_WEIGHTS]
        self.cells = [Cell(stars=self.rng.choices(stars, weights)[0])
                      for _ in range(MAP_SIDE * MAP_SIDE)]
        for i, p in enumerate(self.players.values()):
            p.cursor = (MAP_SIDE // 2 - 1 + (i % 3)) * MAP_SIDE + (i * 3) % MAP_SIDE
        self.state = "playing"
        self.started_at = now
        self.ends_at = now + self.duration
        self.last_active = now

    # ---------- 플레이 ----------
    def _player(self, token: str) -> Player:
        p = self.players.get(token)
        if p is None:
            raise GameError("참가자 정보를 찾을 수 없어요.")
        return p

    def _require_playing(self, now: float) -> None:
        self.tick(now)
        if self.state != "playing":
            raise GameError("게임이 진행 중이 아니에요.")

    def _release(self, p: Player) -> None:
        if p.selected is not None:
            cell = self.cells[p.selected]
            if cell.locked_by == p.pid:
                cell.locked_by = None
        p.selected = None
        p.command = None
        p.select_deadline = 0.0

    def _next_question(self) -> dict:
        if not self._bag:
            self._bag = [q for q in self.questions if q.get("difficulty") == "square"]
            if not self._bag:
                raise GameError("사용할 수 있는 문제가 없어요.")
            self.rng.shuffle(self._bag)
        return self._bag.pop()

    def move(self, token: str, dx: int, dy: int, now: float) -> int:
        self._require_playing(now)
        p = self._player(token)
        if p.selected is not None:
            return p.cursor  # 입력 모드에서는 커서 고정
        x, y = p.cursor % MAP_SIDE, p.cursor // MAP_SIDE
        x = min(MAP_SIDE - 1, max(0, x + (dx > 0) - (dx < 0)))
        y = min(MAP_SIDE - 1, max(0, y + (dy > 0) - (dy < 0)))
        p.cursor = y * MAP_SIDE + x
        return p.cursor

    def select(self, token: str, now: float) -> str:
        """현재 커서 칸을 선택하고 명령어를 돌려준다(그 사람에게만 보낸다)."""
        self._require_playing(now)
        p = self._player(token)
        if p.selected is not None:
            raise GameError("이미 칸을 선택했어요.")
        cell = self.cells[p.cursor]
        if cell.locked_by is not None:
            raise GameError("다른 사람이 입력 중인 칸이에요.")
        if cell.owner == p.pid:
            raise GameError("이미 내 땅이에요.")
        if cell.owner is not None:
            raise GameError("상대의 땅 뺏기는 다음 단계에서 추가돼요.")
        q = self._next_question()
        cell.locked_by = p.pid
        p.selected = p.cursor
        p.command = q["command"]
        p.select_deadline = now + SELECT_TIME
        return p.command

    def cancel(self, token: str, now: float) -> None:
        p = self._player(token)
        self._release(p)

    def submit(self, token: str, text: str, now: float) -> dict:
        """명령어 제출. 반환: {"result": "captured"|"wrong"|"timeout", ...}"""
        self.tick(now)
        p = self._player(token)
        if self.state != "playing":
            raise GameError("게임이 진행 중이 아니에요.")
        if p.selected is None:
            # tick에서 시간 초과로 잠금이 풀렸을 수 있다
            return {"result": "timeout"}
        if (text or "").strip() != p.command:
            return {"result": "wrong"}
        cell = self.cells[p.selected]
        gained = cell.stars * POINTS_PER_STAR
        cell.owner = p.pid
        cell.locked_by = None
        p.captures += 1
        p.last_score_time = now
        idx = p.selected
        p.selected = None
        p.command = None
        p.select_deadline = 0.0
        self.last_active = now
        return {"result": "captured", "cell": idx, "gained": gained}

    def disconnect(self, token: str, now: float) -> None:
        p = self.players.get(token)
        if p is None:
            return
        p.connected = False
        p.sid = None
        self._release(p)  # 점수와 땅은 유지, 선택 중이던 잠금만 해제
        self.last_active = now

    def reconnect(self, token: str, sid: str, now: float) -> Player:
        p = self._player(token)
        p.connected = True
        p.sid = sid
        self.last_active = now
        return p

    # ---------- 시간 ----------
    def tick(self, now: float) -> list[str]:
        """시간 초과 처리. 선택 시간이 지난 참가자 pid 목록을 돌려준다."""
        expired: list[str] = []
        if self.state != "playing":
            return expired
        if now >= self.ends_at:
            # 종료 시점에 진행 중이던 점령은 무효
            for p in self.players.values():
                self._release(p)
            self.state = "ended"
            self.ended_at = self.ends_at
            return expired
        for p in self.players.values():
            if p.selected is not None and now >= p.select_deadline:
                expired.append(p.pid)
                self._release(p)
        return expired

    # ---------- 점수 ----------
    def territory(self, pid: str) -> int:
        return sum(c.stars * POINTS_PER_STAR for c in self.cells if c.owner == pid)

    def cell_count(self, pid: str) -> int:
        return sum(1 for c in self.cells if c.owner == pid)

    def standings(self) -> list[dict]:
        """점수 → 보유 칸 수 → 마지막 득점 시각이 빠른 쪽 순. 완전 동률은 같은 rank."""
        rows = []
        for p in self.players.values():
            rows.append({
                "pid": p.pid, "nickname": p.nickname, "character": p.character,
                "color": p.color, "score": self.territory(p.pid),
                "cells": self.cell_count(p.pid), "captures": p.captures,
                "_t": p.last_score_time if p.last_score_time is not None else float("inf"),
            })
        rows.sort(key=lambda r: (-r["score"], -r["cells"], r["_t"]))
        rank, prev = 0, None
        for i, r in enumerate(rows):
            key = (r["score"], r["cells"], r["_t"])
            if key != prev:
                rank = i + 1
                prev = key
            r["rank"] = rank
            del r["_t"]
        return rows

    # ---------- 직렬화 (정답·토큰·명령어는 절대 포함하지 않는다) ----------
    def public_state(self, now: float) -> dict:
        return {
            "code": self.code,
            "state": self.state,
            "side": MAP_SIDE,
            "timeLeft": max(0.0, self.ends_at - now) if self.state == "playing" else 0,
            "duration": self.duration,
            "cells": [{"owner": c.owner, "stars": c.stars, "lockedBy": c.locked_by}
                      for c in self.cells],
            "players": [{"pid": p.pid, "nickname": p.nickname, "character": p.character,
                         "color": p.color, "cursor": p.cursor, "connected": p.connected,
                         "selecting": p.selected} for p in self.players.values()],
            "standings": self.standings(),
        }


class RoomManager:
    """방 생성·조회·정리와 잘못된 코드 연속 입력 차단."""

    MAX_FAILS = 5
    BLOCK_SECONDS = 30.0

    def __init__(self, questions: list[dict] | None = None):
        self.questions = questions if questions is not None else load_questions()
        self.rooms: dict[str, Room] = {}
        self._fails: dict[str, tuple[int, float]] = {}  # 클라이언트 키 -> (실패 수, 차단 해제 시각)

    def create_room(self, now: float, duration: int = DEFAULT_DURATION) -> Room:
        if not MIN_DURATION <= duration <= MAX_DURATION:
            raise GameError("제한 시간은 3~10분이에요.")
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.rooms:
                break
        room = Room(code=code, host_token=secrets.token_urlsafe(16),
                    questions=self.questions, duration=duration,
                    created_at=now, last_active=now)
        self.rooms[code] = room
        return room

    def find(self, code: str, client: str, now: float) -> Room:
        fails, blocked_until = self._fails.get(client, (0, 0.0))
        if now < blocked_until:
            raise GameError("잘못된 코드를 여러 번 입력했어요. 잠시 후 다시 시도하세요.")
        room = self.rooms.get((code or "").strip().upper())
        if room is None:
            fails += 1
            if fails >= self.MAX_FAILS:
                self._fails[client] = (0, now + self.BLOCK_SECONDS)
            else:
                self._fails[client] = (fails, 0.0)
            raise GameError("방을 찾을 수 없어요. 코드를 확인하세요.")
        self._fails.pop(client, None)
        return room

    def cleanup(self, now: float) -> list[str]:
        removed = []
        for code, room in list(self.rooms.items()):
            anyone = any(p.connected for p in room.players.values())
            ended_old = room.ended_at is not None and now - room.ended_at > ENDED_ROOM_TTL
            idle = not anyone and now - room.last_active > EMPTY_ROOM_TTL
            if ended_old or idle:
                del self.rooms[code]
                removed.append(code)
        return removed
