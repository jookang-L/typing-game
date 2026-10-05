"""게임 판정 로직 (네트워크와 무관한 순수 파이썬).

서버가 상태와 판정을 단독 관리한다. 시간은 모든 메서드에 `now`(초)로 주입해서
테스트에서 시계를 제어할 수 있게 한다. 퀴즈 정답·명령어·토큰은 public_state에 넣지 않는다.
"""
from __future__ import annotations

import json
import math
import os
import random
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from maps import MAP_ROWS, Layout

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 0, O, 1, I 제외
CODE_LENGTH = 6

SELECT_TIME = 20.0           # 칸 선택 후 명령어 입력 제한(초)
QUIZ_TIME = 15.0
WRONG_COOLDOWN = 5.0
STAR_WEIGHTS = ((1, 50), (2, 30), (3, 20))
POINTS_PER_STAR = 10
DEFAULT_DURATION = 300
MIN_DURATION, MAX_DURATION = 180, 600
SOLO_MIN, SOLO_MAX = 2, 9
TEAM_SIZE, MAX_TEAMS = 4, 9
MIN_QUESTIONS_PER_TAG = 10
ENDED_ROOM_TTL = 30 * 60
EMPTY_ROOM_TTL = 30 * 60
HIDE_LAST_MINUTE_MIN_DURATION = 240

# 아이템 (PRD 7장). 이름이 곧 사용 명령어다.
ITEMS = ["bonus()", "x2", "sleep(5)", "blur()", "try/except", "private", "hint()"]
ITEM_KINDS = {"bonus()": "reward", "x2": "reward", "sleep(5)": "attack", "blur()": "attack",
              "try/except": "defense", "private": "defense", "hint()": "util"}
INVENTORY_SIZE = 2
ITEM_CAP = 4                 # 동시에 존재하는 아이템 칸 수
ITEM_FIRST_BATCH = 2
ITEM_INTERVALS = (30, 20, 10)  # 초반/중반/후반 새 아이템 간격
ITEM_START_MIN = 90
BONUS_POINTS = 30
X2_SECONDS = 15
SLEEP_SECONDS = 5
BLUR_SECONDS = 10
TRY_EXCEPT_SECONDS = 20
PRIVATE_SECONDS = 12
PRIVATE_COOLDOWN = 30
REVENGE_SECONDS = 30
HIT_IMMUNE_SECONDS = 5

# 색약 친화 팔레트(Okabe-Ito 기반) 9색. 팀 색과 개인 색에 같은 목록을 쓴다.
COLORS = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2",
          "#D55E00", "#CC79A7", "#B8B8FF", "#FF8A8A"]
CHARACTERS = ["cat", "dog", "bird", "fish", "rabbit", "turtle", "ghost", "bot", "rocket"]
TAGS = ["출력", "변수", "입력", "연산자", "자료형", "컨테이너", "조건문", "반복문", "함수"]

QUESTIONS_PATH = Path(__file__).parent / "data" / "questions.json"


def dev_mode() -> bool:
    """TYPING_DEV=1 이면 혼자서도 시작할 수 있다 (로컬 테스트용)."""
    return os.environ.get("TYPING_DEV") == "1"


class GameError(Exception):
    """사용자에게 보여줄 수 있는 오류."""


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Settings:
    mode: str = "solo"                 # solo | team
    map: str = "square"
    tags: list[str] = field(default_factory=list)
    max_players: int = SOLO_MAX
    duration: int = DEFAULT_DURATION
    item_start: int | None = None      # 게임 시작 후 초. None 이면 아이템 없음
    hide_last_minute: bool = False


@dataclass
class Player:
    token: str
    pid: str
    nickname: str
    character: str
    color: str
    sid: str | None = None
    connected: bool = True
    team: int | None = None
    cursor: int = 0
    selected: int | None = None
    phase: str | None = None           # None | typing | quiz
    command: str | None = None
    select_deadline: float = 0.0
    qdata: dict | None = None          # 이 칸의 문제 세트 (정답 포함, 서버 전용)
    quiz_order: list[int] = field(default_factory=list)
    quiz_hidden: set[int] = field(default_factory=set)
    quiz_deadline: float = 0.0
    cooldowns: dict[int, float] = field(default_factory=dict)
    items: list[str] = field(default_factory=list)
    hint_pending: bool = False
    sleep_until: float = 0.0
    blur_until: float = 0.0
    x2_until: float = 0.0
    immune_until: float = 0.0
    private_cd_until: float = 0.0
    hit_immune_until: float = 0.0
    captures: int = 0
    quiz_correct: int = 0
    personal_score: int = 0


@dataclass
class Cell:
    stars: int
    owner: str | None = None           # 소유 side id (개인전 pid / 팀전 팀 id)
    locked_by: str | None = None
    ever_owned: bool = False
    item: str | None = None
    protected_until: float = 0.0
    last_q: str | None = None


@dataclass
class Side:
    id: str
    kind: str                          # player | team
    name: str
    color: str
    members: list[str]
    bonus: int = 0
    last_score_time: float | None = None
    revenge: tuple[str, float] | None = None   # (공격한 side id, 만료 시각)
    last_captured: int | None = None


@dataclass
class Room:
    code: str
    host_token: str
    questions: list[dict]
    settings: Settings
    state: str = "lobby"               # lobby | playing | ended
    players: dict[str, Player] = field(default_factory=dict)   # token -> Player
    layout: Layout | None = None
    cells: list[Cell] = field(default_factory=list)
    sides: dict[str, Side] = field(default_factory=dict)
    side_order: list[str] = field(default_factory=list)
    started_at: float = 0.0
    ends_at: float = 0.0
    ended_at: float | None = None
    created_at: float = 0.0
    last_active: float = 0.0
    rng: random.Random = field(default_factory=random.Random)
    notices: list[dict] = field(default_factory=list)
    item_started: bool = False
    next_spawn: float = 0.0
    _bag: list[dict] = field(default_factory=list)

    # ---------- 로비 ----------
    @property
    def duration(self) -> int:
        return self.settings.duration

    def join(self, nickname: str, character: str, color: str, now: float) -> Player:
        if self.state != "lobby":
            raise GameError("이미 게임이 시작되어 입장할 수 없어요.")
        nickname = (nickname or "").strip()
        if not 1 <= len(nickname) <= 12:
            raise GameError("닉네임은 1~12자로 입력하세요.")
        if len(self.players) >= self.settings.max_players:
            raise GameError("방이 가득 찼어요.")
        if any(p.nickname == nickname for p in self.players.values()):
            raise GameError("이미 사용 중인 닉네임이에요.")
        if character not in CHARACTERS:
            raise GameError("캐릭터를 선택하세요.")
        if color not in COLORS:
            raise GameError("색상을 선택하세요.")
        if self.settings.mode == "solo" and any(p.color == color for p in self.players.values()):
            raise GameError("이미 다른 사람이 고른 색이에요.")
        token = secrets.token_urlsafe(16)
        p = Player(token=token, pid=f"p{secrets.token_hex(3)}", nickname=nickname,
                   character=character, color=color)
        self.players[token] = p
        self.last_active = now
        return p

    def kick(self, pid: str) -> None:
        for token, p in list(self.players.items()):
            if p.pid == pid:
                self._release(p)
                del self.players[token]
                return

    def _by_pid(self, pid: str) -> Player | None:
        return next((p for p in self.players.values() if p.pid == pid), None)

    def assign_teams(self) -> None:
        """랜덤 배정: 팀 수 = ceil(인원/4), 팀 간 인원 차이 1명 이하."""
        if self.state != "lobby" or self.settings.mode != "team":
            raise GameError("팀전 로비에서만 배정할 수 있어요.")
        plist = list(self.players.values())
        if not plist:
            raise GameError("참가자가 없어요.")
        n_teams = min(MAX_TEAMS, math.ceil(len(plist) / TEAM_SIZE))
        self.rng.shuffle(plist)
        for i, p in enumerate(plist):
            p.team = i % n_teams

    def set_team(self, pid: str, team: int | None) -> None:
        if self.state != "lobby" or self.settings.mode != "team":
            raise GameError("팀전 로비에서만 옮길 수 있어요.")
        p = self._by_pid(pid)
        if p is None:
            raise GameError("참가자를 찾을 수 없어요.")
        if team is not None:
            if not 0 <= team < MAX_TEAMS:
                raise GameError("팀 번호가 올바르지 않아요.")
            size = sum(1 for q in self.players.values() if q.team == team and q is not p)
            if size >= TEAM_SIZE:
                raise GameError("팀당 최대 4명이에요.")
        p.team = team

    def start_problems(self) -> str | None:
        """시작할 수 없는 이유 (없으면 None)."""
        n = len(self.players)
        if self.settings.mode == "solo":
            if n < (1 if dev_mode() else SOLO_MIN):
                return f"개인전은 최소 {SOLO_MIN}명이 필요해요."
            return None
        if any(p.team is None for p in self.players.values()):
            return "팀이 정해지지 않은 참가자가 있어요."
        sizes: dict[int, int] = {}
        for p in self.players.values():
            sizes[p.team] = sizes.get(p.team, 0) + 1
        if dev_mode() and sizes:
            return None
        if len(sizes) < 2:
            return "팀전은 2팀 이상이 필요해요. (최소 4명, 팀당 2명 이상)"
        if min(sizes.values()) < 2:
            return "팀당 최소 2명이 필요해요."
        return None

    def start(self, now: float) -> None:
        if self.state != "lobby":
            raise GameError("이미 시작된 방이에요.")
        problem = self.start_problems()
        if problem:
            raise GameError(problem)
        self.layout = Layout(MAP_ROWS[self.settings.map])
        weights = [w for _, w in STAR_WEIGHTS]
        stars = [s for s, _ in STAR_WEIGHTS]
        self.cells = [Cell(stars=self.rng.choices(stars, weights)[0]) for _ in range(len(self.layout))]
        self._build_sides()
        plist = list(self.players.values())
        for i, p in enumerate(plist):
            p.cursor = self.layout.center() if i == 0 else self.rng.randrange(len(self.cells))
        self.state = "playing"
        self.started_at = now
        self.ends_at = now + self.duration
        self.last_active = now

    def _build_sides(self) -> None:
        self.sides, self.side_order = {}, []
        if self.settings.mode == "solo":
            for p in self.players.values():
                self.sides[p.pid] = Side(p.pid, "player", p.nickname, p.color, [p.pid])
                self.side_order.append(p.pid)
            return
        used = sorted({p.team for p in self.players.values()})
        for i, t in enumerate(used):
            members = [p.pid for p in self.players.values() if p.team == t]
            sid = f"t{i + 1}"
            self.sides[sid] = Side(sid, "team", f"{i + 1}팀", COLORS[i], members)
            self.side_order.append(sid)

    def side_of(self, p: Player) -> Side:
        for s in self.sides.values():
            if p.pid in s.members:
                return s
        raise GameError("소속을 찾을 수 없어요.")

    # ---------- 공통 ----------
    def _player(self, token: str) -> Player:
        p = self.players.get(token)
        if p is None:
            raise GameError("참가자 정보를 찾을 수 없어요.")
        return p

    def _require_playing(self, now: float) -> None:
        self.tick(now)
        if self.state != "playing":
            raise GameError("게임이 진행 중이 아니에요.")

    def _notice(self, kind: str, to: str | None = None, **data) -> None:
        self.notices.append({"type": kind, "to": to, **data})

    def _release(self, p: Player) -> None:
        if p.selected is not None and p.selected < len(self.cells):
            cell = self.cells[p.selected]
            if cell.locked_by == p.pid:
                cell.locked_by = None
        p.selected = None
        p.phase = None
        p.command = None
        p.qdata = None
        p.quiz_order = []
        p.quiz_hidden = set()
        p.select_deadline = 0.0
        p.quiz_deadline = 0.0

    def _pool(self) -> list[dict]:
        tags = set(self.settings.tags)
        return [q for q in self.questions if q["tag"] in tags and q["difficulty"] == self.settings.map]

    def _next_question(self, avoid: str | None) -> dict:
        if not self._bag:
            self._bag = self._pool()
            if not self._bag:
                raise GameError("사용할 수 있는 문제가 없어요.")
            self.rng.shuffle(self._bag)
        idx = len(self._bag) - 1
        if avoid and self._bag[idx]["id"] == avoid and len(self._bag) > 1:
            idx -= 1   # 같은 칸을 다시 고르면 다른 문제
        return self._bag.pop(idx)

    def _blocked(self, p: Player, now: float) -> None:
        if now < p.sleep_until:
            raise GameError(f"sleep! {math.ceil(p.sleep_until - now)}초 동안 입력할 수 없어요.")

    # ---------- 이동·선택 ----------
    def move(self, token: str, dx: int, dy: int, now: float) -> int:
        self._require_playing(now)
        p = self._player(token)
        if p.phase is not None:
            return p.cursor
        p.cursor = self.layout.move(p.cursor, (dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
        return p.cursor

    def select(self, token: str, now: float) -> str:
        self._require_playing(now)
        p = self._player(token)
        self._blocked(p, now)
        if p.phase is not None:
            raise GameError("이미 칸을 선택했어요.")
        idx = p.cursor
        cell = self.cells[idx]
        side = self.side_of(p)
        if cell.locked_by is not None:
            raise GameError("다른 사람이 입력 중인 칸이에요.")
        if cell.owner == side.id:
            raise GameError("이미 우리 땅이에요." if side.kind == "team" else "이미 내 땅이에요.")
        if cell.owner is not None and now < cell.protected_until:
            raise GameError("보호 중인 칸이에요.")
        if now < p.cooldowns.get(idx, 0.0):
            raise GameError(f"{math.ceil(p.cooldowns[idx] - now)}초 뒤에 이 칸에 다시 도전할 수 있어요.")
        q = self._next_question(cell.last_q)
        cell.last_q = q["id"]
        cell.locked_by = p.pid
        p.selected = idx
        p.phase = "typing"
        p.qdata = q
        p.command = q["command"]
        p.select_deadline = now + SELECT_TIME
        return p.command

    def cancel(self, token: str, now: float) -> None:
        p = self._player(token)
        if p.phase == "quiz":
            return  # 퀴즈 중에는 취소할 수 없다 (시간 초과/오답으로 끝난다)
        self._release(p)

    def submit(self, token: str, text: str, now: float) -> dict:
        """명령어 제출. result: captured | quiz | wrong | timeout | protected"""
        self.tick(now)
        p = self._player(token)
        if self.state != "playing":
            raise GameError("게임이 진행 중이 아니에요.")
        if p.phase != "typing":
            return {"result": "timeout"}
        self._blocked(p, now)
        if (text or "").strip() != p.command:
            return {"result": "wrong"}
        cell = self.cells[p.selected]
        if cell.owner is None:
            return self._capture(p, now, steal=False)
        if now < cell.protected_until:
            self._release(p)
            return {"result": "protected"}
        self._start_quiz(p, now)
        return {"result": "quiz"}

    # ---------- 점령·뺏기 ----------
    def _bonus_for_capture(self, p: Player, side: Side, stars_points: int, now: float) -> int:
        if now < p.x2_until:
            side.bonus += stars_points
            p.personal_score += stars_points
            return stars_points
        return 0

    def _capture(self, p: Player, now: float, steal: bool) -> dict:
        idx = p.selected
        cell = self.cells[idx]
        side = self.side_of(p)
        gained = cell.stars * POINTS_PER_STAR
        prev_owner = cell.owner
        cell.owner = side.id
        cell.locked_by = None
        cell.ever_owned = True
        p.captures += 1
        p.personal_score += gained
        side.last_score_time = now
        side.last_captured = idx
        extra = self._bonus_for_capture(p, side, gained, now)
        got_item = None
        replaced = None
        if steal:
            p.quiz_correct += 1
            victim = self.sides.get(prev_owner)
            if victim:
                victim.revenge = (side.id, now + REVENGE_SECONDS)
                self._notice("stolen", to=None, attacker=p.nickname, attacker_side=side.id,
                             victim_side=victim.id, cell=idx)
        elif cell.item:
            got_item, replaced = self._give_item(p, cell.item)
            cell.item = None
        self.last_active = now
        self._release(p)
        res = {"result": "stolen" if steal else "captured", "cell": idx, "gained": gained, "extra": extra}
        if got_item:
            res["item"] = got_item
            if replaced:
                res["replaced"] = replaced
        return res

    def _give_item(self, p: Player, name: str) -> tuple[str, str | None]:
        replaced = None
        if len(p.items) >= INVENTORY_SIZE:
            replaced = p.items.pop(0)   # 가장 먼저 획득한 아이템이 대체된다
        p.items.append(name)
        return name, replaced

    def _start_quiz(self, p: Player, now: float) -> None:
        order = [0, 1, 2, 3]
        self.rng.shuffle(order)
        p.quiz_order = order   # 화면 i번째 보기 = 원본 order[i]
        p.quiz_hidden = set()
        if p.hint_pending:
            wrong = [i for i, o in enumerate(order) if o != p.qdata["quiz"]["answer"]]
            p.quiz_hidden = set(self.rng.sample(wrong, 2))
            p.hint_pending = False
        p.phase = "quiz"
        p.quiz_deadline = now + QUIZ_TIME

    def answer(self, token: str, number: int, now: float) -> dict:
        """number: 화면에 보이는 보기 번호 1~4."""
        self.tick(now)
        p = self._player(token)
        if self.state != "playing":
            raise GameError("게임이 진행 중이 아니에요.")
        if p.phase != "quiz":
            return {"result": "timeout"}
        self._blocked(p, now)
        if not 1 <= number <= 4 or (number - 1) in p.quiz_hidden:
            raise GameError("선택할 수 없는 보기예요.")
        quiz = p.qdata["quiz"]
        correct_pos = p.quiz_order.index(quiz["answer"]) + 1
        if now >= p.quiz_deadline:
            return self._quiz_fail(p, now, "timeout", quiz, correct_pos)
        if p.quiz_order[number - 1] != quiz["answer"]:
            return self._quiz_fail(p, now, "wrong", quiz, correct_pos)
        cell = self.cells[p.selected]
        if cell.owner == self.side_of(p).id or cell.owner is None:
            self._release(p)
            return {"result": "timeout"}
        res = self._capture(p, now, steal=True)
        res.update(explanation=quiz["explanation"], correct=correct_pos)
        return res

    def _quiz_fail(self, p: Player, now: float, kind: str, quiz: dict, correct_pos: int) -> dict:
        p.cooldowns[p.selected] = now + WRONG_COOLDOWN
        self._release(p)
        return {"result": kind, "explanation": quiz["explanation"], "correct": correct_pos,
                "cooldown": WRONG_COOLDOWN}

    # ---------- 아이템 ----------
    def use_item(self, token: str, name: str, now: float) -> dict:
        self._require_playing(now)
        p = self._player(token)
        name = (name or "").strip()
        if name not in ITEMS:
            return {"result": "typo"}           # 일반 오타는 조용히 처리
        if name not in p.items:
            return {"result": "missing"}        # "아이템이 없습니다" 경고, 패널티 없음
        self._blocked(p, now)
        side = self.side_of(p)
        res: dict = {"result": "used", "item": name}
        if name == "bonus()":
            side.bonus += BONUS_POINTS
            p.personal_score += BONUS_POINTS
            side.last_score_time = now
            res["gained"] = BONUS_POINTS
        elif name == "x2":
            p.x2_until = now + X2_SECONDS
            res["seconds"] = X2_SECONDS
        elif name == "hint()":
            p.hint_pending = True
        elif name == "private":
            if now < p.private_cd_until:
                raise GameError(f"private 쿨타임 {math.ceil(p.private_cd_until - now)}초 남았어요.")
            p.immune_until = now + PRIVATE_SECONDS
            p.private_cd_until = now + PRIVATE_SECONDS + PRIVATE_COOLDOWN
            res["seconds"] = PRIVATE_SECONDS
        elif name == "try/except":
            idx = side.last_captured
            if idx is None or self.cells[idx].owner != side.id:
                raise GameError("보호할 땅이 없어요. 먼저 칸을 점령하세요.")
            self.cells[idx].protected_until = now + TRY_EXCEPT_SECONDS
            res.update(seconds=TRY_EXCEPT_SECONDS, cell=idx)
        else:   # sleep(5) / blur()
            res.update(self._use_attack(p, side, name, now))
        p.items.remove(name)
        self.last_active = now
        return res

    def _pick_target(self, side: Side, now: float) -> Side | None:
        rev = side.revenge
        if rev and now < rev[1] and rev[0] in self.sides and rev[0] != side.id:
            return self.sides[rev[0]]
        ranking = [r for r in self._ranked(now) if r["id"] != side.id]
        if not ranking:
            return None
        top = self._ranked(now)[0]
        pick = top["id"] if top["id"] != side.id else ranking[0]["id"]   # 내가 1위면 2위
        return self.sides[pick]

    def _use_attack(self, p: Player, side: Side, name: str, now: float) -> dict:
        target_side = self._pick_target(side, now)
        candidates = []
        if target_side:
            candidates = [self._by_pid(m) for m in target_side.members]
            candidates = [c for c in candidates if c and c.connected]
        if not candidates:
            raise GameError("지금은 방해할 대상이 없어요.")
        t = self.rng.choice(candidates)
        if now < t.immune_until:
            self._notice("blocked", to=p.pid, item=name)
            self._notice("defended", to=t.pid, item=name)
            return {"blocked": True, "reason": "private"}
        if now < t.hit_immune_until:
            self._notice("blocked", to=p.pid, item=name)
            return {"blocked": True, "reason": "recent"}
        secs = SLEEP_SECONDS if name == "sleep(5)" else BLUR_SECONDS
        if name == "sleep(5)":
            t.sleep_until = now + secs
        else:
            t.blur_until = now + secs
        t.hit_immune_until = now + secs + HIT_IMMUNE_SECONDS
        if side.revenge and side.revenge[0] == target_side.id:
            side.revenge = None
        self._notice("hit", to=t.pid, item=name, seconds=secs)
        return {"blocked": False, "target": t.nickname}

    def spawn_item(self, now: float) -> bool:
        if sum(1 for c in self.cells if c.item) >= ITEM_CAP:
            return False
        cands = [i for i, c in enumerate(self.cells)
                 if c.owner is None and not c.ever_owned and c.locked_by is None and c.item is None]
        if not cands:
            return False
        self.cells[self.rng.choice(cands)].item = self.rng.choice(ITEMS)
        return True

    def _interval(self, elapsed: float) -> float:
        span = max(1.0, self.duration - self.settings.item_start)
        part = min(2, int((elapsed - self.settings.item_start) // (span / 3)))
        return ITEM_INTERVALS[max(0, part)]

    def _tick_items(self, now: float) -> None:
        start = self.settings.item_start
        if start is None:
            return
        elapsed = now - self.started_at
        if elapsed < start:
            return
        if not self.item_started:
            self.item_started = True
            spawned = sum(self.spawn_item(now) for _ in range(ITEM_FIRST_BATCH))
            self.next_spawn = elapsed + self._interval(elapsed)
            if spawned:
                self._notice("item_spawn")
            return
        if elapsed >= self.next_spawn:
            if self.spawn_item(now):
                self._notice("item_spawn")
                self.next_spawn = elapsed + self._interval(elapsed)

    # ---------- 연결 ----------
    def disconnect(self, token: str, now: float) -> None:
        p = self.players.get(token)
        if p is None:
            return
        p.connected = False
        p.sid = None
        self._release(p)   # 점수와 땅은 유지, 선택 중이던 잠금만 해제
        self.last_active = now

    def reconnect(self, token: str, sid: str, now: float) -> Player:
        p = self._player(token)
        p.connected = True
        p.sid = sid
        self.last_active = now
        return p

    def force_end(self, now: float) -> None:
        if self.state != "playing":
            raise GameError("진행 중인 게임이 없어요.")
        self._finish(now)

    # ---------- 시간 ----------
    def _finish(self, now: float) -> None:
        for p in self.players.values():
            self._release(p)   # 진행 중이던 점령(입력/퀴즈)은 무효
        self.state = "ended"
        self.ended_at = min(now, self.ends_at)
        self._notice("game_end")

    def tick(self, now: float) -> list[tuple[str, str]]:
        """시간 처리. 시간 초과된 (pid, 'typing'|'quiz') 목록을 돌려준다."""
        expired: list[tuple[str, str]] = []
        if self.state != "playing":
            return expired
        if now >= self.ends_at:
            self._finish(now)
            return expired
        for p in self.players.values():
            if p.phase == "typing" and now >= p.select_deadline:
                expired.append((p.pid, "typing"))
                self._release(p)
            elif p.phase == "quiz" and now >= p.quiz_deadline:
                expired.append((p.pid, "quiz"))
                quiz = p.qdata["quiz"]
                correct_pos = p.quiz_order.index(quiz["answer"]) + 1
                info = self._quiz_fail(p, now, "timeout", quiz, correct_pos)
                self._notice("quiz_timeout", to=p.pid, **info)
        self._tick_items(now)
        return expired

    # ---------- 점수 ----------
    def _ranked(self, now: float) -> list[dict]:
        """내부 점수 기준 순위 (숨김 옵션과 무관). 평균 점수 → 칸 수 → 먼저 득점한 쪽."""
        terr: dict[str, int] = {}
        count: dict[str, int] = {}
        for c in self.cells:
            if c.owner:
                terr[c.owner] = terr.get(c.owner, 0) + c.stars * POINTS_PER_STAR
                count[c.owner] = count.get(c.owner, 0) + 1
        rows = []
        for sid in self.side_order:
            s = self.sides[sid]
            total = terr.get(sid, 0) + s.bonus
            n = max(1, len(s.members))
            rows.append({"id": sid, "territory": terr.get(sid, 0), "bonus": s.bonus, "total": total,
                         "avg": round(total / n, 1), "cells": count.get(sid, 0), "n": n,
                         "_k": (-total / n, -count.get(sid, 0),
                                s.last_score_time if s.last_score_time is not None else float("inf"))})
        rows.sort(key=lambda r: r["_k"])
        rank, prev = 0, None
        for i, r in enumerate(rows):
            if r["_k"] != prev:
                rank, prev = i + 1, r["_k"]
            r["rank"] = rank
        return rows

    def standings(self, now: float) -> list[dict]:
        out = []
        for r in self._ranked(now):
            s = self.sides[r["id"]]
            members = []
            for m in s.members:
                p = self._by_pid(m)
                if p:
                    members.append({"pid": p.pid, "nickname": p.nickname, "character": p.character,
                                    "color": p.color, "captures": p.captures,
                                    "quizCorrect": p.quiz_correct, "score": p.personal_score})
            out.append({"id": s.id, "kind": s.kind, "name": s.name, "color": s.color,
                        "territory": r["territory"], "bonus": r["bonus"], "score": r["total"],
                        "avg": r["avg"], "cells": r["cells"], "rank": r["rank"], "members": members})
        return out

    def scores_hidden(self, now: float) -> bool:
        return (self.settings.hide_last_minute and self.state == "playing"
                and self.ends_at - now <= 60)

    # ---------- 직렬화 (정답·토큰·명령어는 절대 포함하지 않는다) ----------
    def public_state(self, now: float, viewer_token: str | None = None) -> dict:
        playing = self.state == "playing"
        viewer = self.players.get(viewer_token) if viewer_token else None
        my_side = None
        if viewer and self.sides:
            my_side = self.side_of(viewer).id
        hidden = self.scores_hidden(now)
        stand = self.standings(now) if self.sides else []
        if hidden:
            stand.sort(key=lambda s: self.side_order.index(s["id"]))   # 순위 노출 방지
            for s in stand:
                if s["id"] != my_side:
                    s.update(score=None, avg=None, rank=None, territory=None, bonus=None)
                    for m in s["members"]:
                        m["score"] = None
        # 아이템 등장까지 남은 시간
        next_item = None
        st = self.settings
        if playing and st.item_start is not None:
            elapsed = now - self.started_at
            if not self.item_started:
                next_item = max(0.0, st.item_start - elapsed)
            elif sum(1 for c in self.cells if c.item) < ITEM_CAP:
                next_item = max(0.0, self.next_spawn - elapsed)
        return {
            "code": self.code,
            "state": self.state,
            "settings": {"mode": st.mode, "map": st.map, "tags": st.tags, "maxPlayers": st.max_players,
                         "duration": st.duration, "itemStart": st.item_start,
                         "hideLastMinute": st.hide_last_minute},
            "rows": MAP_ROWS[st.map],
            "timeLeft": max(0.0, self.ends_at - now) if playing else 0,
            "nextItemIn": next_item,
            "scoresHidden": hidden,
            "startProblem": self.start_problems() if self.state == "lobby" else None,
            "cells": [{"owner": c.owner, "stars": c.stars, "lockedBy": c.locked_by,
                       "item": bool(c.item)} for c in self.cells],
            "players": [{"pid": p.pid, "nickname": p.nickname, "character": p.character,
                         "color": p.color, "team": p.team, "cursor": p.cursor,
                         "connected": p.connected, "selecting": p.selected,
                         "immuneLeft": max(0.0, p.immune_until - now)} for p in self.players.values()],
            "sides": stand,
        }

    def me_state(self, p: Player, now: float) -> dict:
        quiz = None
        if p.phase == "quiz" and p.qdata:
            q = p.qdata["quiz"]
            quiz = {"type": q["type"], "question": q["question"],
                    "choices": [{"text": q["choices"][o], "off": i in p.quiz_hidden}
                                for i, o in enumerate(p.quiz_order)],
                    "left": max(0.0, p.quiz_deadline - now)}
        side = self.side_of(p).id if self.sides else None
        rev = None
        if self.sides:
            r = self.side_of(p).revenge
            if r and now < r[1] and r[0] in self.sides:
                rev = {"name": self.sides[r[0]].name, "left": r[1] - now}
        return {
            "pid": p.pid, "side": side, "items": list(p.items), "phase": p.phase,
            "command": p.command if p.phase == "typing" else None,
            "selectLeft": max(0.0, p.select_deadline - now) if p.phase == "typing" else 0,
            "selected": p.selected, "quiz": quiz,
            "sleepLeft": max(0.0, p.sleep_until - now), "blurLeft": max(0.0, p.blur_until - now),
            "x2Left": max(0.0, p.x2_until - now), "immuneLeft": max(0.0, p.immune_until - now),
            "privateCd": max(0.0, p.private_cd_until - now), "hint": p.hint_pending,
            "revenge": rev, "cooldowns": {str(k): max(0.0, v - now) for k, v in p.cooldowns.items() if v > now},
        }


class RoomManager:
    """방 생성·조회·정리와 잘못된 코드 연속 입력 차단."""

    MAX_FAILS = 5
    BLOCK_SECONDS = 30.0

    def __init__(self, questions: list[dict] | None = None):
        self.questions = questions if questions is not None else load_questions()
        self.rooms: dict[str, Room] = {}
        self._fails: dict[str, tuple[int, float]] = {}

    def tag_counts(self) -> dict[str, dict[str, int]]:
        """맵(난이도)별 태그 문제 수. 방 만들기 화면에서 10개 미만 태그를 막는 데 쓴다."""
        out: dict[str, dict[str, int]] = {m: {} for m in MAP_ROWS}
        for q in self.questions:
            d = out.setdefault(q["difficulty"], {})
            d[q["tag"]] = d.get(q["tag"], 0) + 1
        return out

    def item_start_options(self, duration: int) -> list[int]:
        return list(range(ITEM_START_MIN, duration - 60 + 1, 30))

    def validate_settings(self, raw: dict) -> Settings:
        mode = raw.get("mode", "solo")
        if mode not in ("solo", "team"):
            raise GameError("게임 모드가 올바르지 않아요.")
        map_ = raw.get("map", "square")
        if map_ not in MAP_ROWS:
            raise GameError("맵이 올바르지 않아요.")
        try:
            duration = int(raw.get("duration", DEFAULT_DURATION))
        except (TypeError, ValueError):
            raise GameError("제한 시간이 올바르지 않아요.")
        if not MIN_DURATION <= duration <= MAX_DURATION or duration % 60:
            raise GameError("제한 시간은 3~10분(1분 단위)이에요.")
        tags = list(raw.get("tags") or [])
        if not tags:
            raise GameError("문제 태그를 1개 이상 선택하세요.")
        counts = self.tag_counts()[map_]
        for t in tags:
            if t not in TAGS:
                raise GameError("알 수 없는 태그예요.")
            if counts.get(t, 0) < MIN_QUESTIONS_PER_TAG:
                raise GameError(f"'{t}' 태그는 문제가 {MIN_QUESTIONS_PER_TAG}개 미만이라 선택할 수 없어요.")
        try:
            max_players = int(raw.get("max_players", SOLO_MAX if mode == "solo" else 36))
        except (TypeError, ValueError):
            raise GameError("최대 인원이 올바르지 않아요.")
        if mode == "solo" and not SOLO_MIN <= max_players <= SOLO_MAX:
            raise GameError("개인전은 2~9명이에요.")
        if mode == "team" and not 4 <= max_players <= TEAM_SIZE * MAX_TEAMS:
            raise GameError("팀전은 4~36명이에요.")
        item_start = raw.get("item_start")
        if item_start in ("", "none"):
            item_start = None
        if item_start is not None:
            try:
                item_start = int(item_start)
            except (TypeError, ValueError):
                raise GameError("아이템 시작 시점이 올바르지 않아요.")
            if item_start not in self.item_start_options(duration):
                raise GameError("아이템 시작 시점은 1:30부터 종료 1분 전까지 30초 단위예요.")
        hide = bool(raw.get("hide_last_minute"))
        if hide and duration < HIDE_LAST_MINUTE_MIN_DURATION:
            raise GameError("점수 비공개는 제한 시간이 4분 이상일 때만 선택할 수 있어요.")
        return Settings(mode=mode, map=map_, tags=tags, max_players=max_players, duration=duration,
                        item_start=item_start, hide_last_minute=hide)

    def create_room(self, now: float, raw: dict | None = None) -> Room:
        raw = dict(raw or {})
        if "tags" not in raw:
            raw["tags"] = [t for t, n in self.tag_counts()["square"].items()
                           if n >= MIN_QUESTIONS_PER_TAG][:1]
        settings = self.validate_settings(raw)
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.rooms:
                break
        room = Room(code=code, host_token=secrets.token_urlsafe(16), questions=self.questions,
                    settings=settings, created_at=now, last_active=now)
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
