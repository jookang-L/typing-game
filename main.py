"""FastAPI + python-socketio 서버. 실행: uvicorn main:app --host 0.0.0.0 --port 8000

단일 프로세스로만 실행한다 (방 상태가 메모리에 있음).
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

import socketio
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from game import (CHARACTERS, COLORS, HIDE_LAST_MINUTE_MIN_DURATION, ITEMS, ITEM_KINDS, MIN_QUESTIONS_PER_TAG,
                  TAGS, GameError, RoomManager)
from maps import MAP_LABELS, MAP_ROWS

STATIC_DIR = Path(__file__).parent / "static"

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*",
                           ping_interval=10, ping_timeout=20)
manager = RoomManager()
# sid -> {"code": str, "role": "host" | "player", "token": str}
sessions: dict[str, dict] = {}


def now() -> float:
    return time.monotonic()


def client_key(sid: str) -> str:
    env = sio.get_environ(sid) or {}
    return env.get("HTTP_X_FORWARDED_FOR", env.get("REMOTE_ADDR", sid)).split(",")[0].strip()


def err(e: GameError) -> dict:
    return {"ok": False, "error": str(e)}


def room_sids(room) -> list[tuple[str, dict]]:
    return [(sid, s) for sid, s in sessions.items() if s["code"] == room.code]


async def broadcast(room) -> None:
    """상태 전송. 마지막 1분 점수 비공개 중에는 사람마다 다른 상태를 보낸다."""
    t = now()
    if room.scores_hidden(t):
        for sid, s in room_sids(room):
            await sio.emit("state", room.public_state(t, s["token"] if s["role"] == "player" else None), to=sid)
    else:
        await sio.emit("state", room.public_state(t), room=room.code)


async def push_self(room, sid: str, player) -> None:
    """개인 영역 정보: 명령어·퀴즈·아이템은 본인에게만 보낸다."""
    await sio.emit("me", room.me_state(player, now()), to=sid)


async def push_all_me(room) -> None:
    for sid, s in room_sids(room):
        if s["role"] == "player":
            p = room.players.get(s["token"])
            if p:
                await push_self(room, sid, p)


async def drain_notices(room) -> None:
    pending, room.notices = room.notices, []
    for n in pending:
        if n.get("to"):
            p = room._by_pid(n["to"])
            if p and p.sid:
                await sio.emit("notice", n, to=p.sid)
        else:
            await sio.emit("notice", n, room=room.code)
    if pending:
        await push_all_me(room)


_pending: dict[str, asyncio.Task] = {}


def request_broadcast(room, delay: float = 0.2) -> None:
    """상태 전송을 모아서 보낸다. 36명이 동시에 움직여도 방당 초당 5번 안팎으로 제한."""
    if room.code in _pending:
        return

    async def flush():
        await asyncio.sleep(delay)
        _pending.pop(room.code, None)
        if room.code in manager.rooms:
            await broadcast(room)

    _pending[room.code] = asyncio.create_task(flush())


async def after_action(room, sid: str, player) -> None:
    request_broadcast(room)
    await drain_notices(room)
    if player:
        await push_self(room, sid, player)


def ctx(sid: str):
    s = sessions.get(sid)
    if not s:
        raise GameError("방에 먼저 입장하세요.")
    room = manager.rooms.get(s["code"])
    if room is None:
        raise GameError("방이 사라졌어요.")
    return s, room


def host_ctx(sid: str):
    s, room = ctx(sid)
    if s["role"] != "host":
        raise GameError("진행자만 할 수 있어요.")
    return s, room


def player_ctx(sid: str):
    s, room = ctx(sid)
    if s["role"] != "player":
        raise GameError("참가자만 할 수 있어요.")
    return s, room, room.players.get(s["token"])


@sio.event
async def disconnect(sid):
    s = sessions.pop(sid, None)
    if not s or s["role"] != "player":
        return
    room = manager.rooms.get(s["code"])
    if room:
        room.disconnect(s["token"], now())
        await broadcast(room)


@sio.on("meta")
async def on_meta(sid, data=None):
    return {
        "colors": COLORS, "characters": CHARACTERS, "tags": TAGS,
        "tagCounts": manager.tag_counts(), "minQuestions": MIN_QUESTIONS_PER_TAG,
        "maps": [{"id": k, "label": MAP_LABELS[k], "rows": MAP_ROWS[k]} for k in MAP_ROWS],
        "items": [{"name": n, "kind": ITEM_KINDS[n]} for n in ITEMS],
        "hideMinDuration": HIDE_LAST_MINUTE_MIN_DURATION,
        "itemStartOptions": {str(d): manager.item_start_options(d) for d in range(180, 601, 60)},
    }


@sio.on("create_room")
async def on_create_room(sid, data=None):
    try:
        room = manager.create_room(now(), data or {})
    except GameError as e:
        return err(e)
    sessions[sid] = {"code": room.code, "role": "host", "token": room.host_token}
    await sio.enter_room(sid, room.code)
    await sio.emit("state", room.public_state(now()), to=sid)
    return {"ok": True, "code": room.code, "hostToken": room.host_token}


@sio.on("join_room")
async def on_join_room(sid, data):
    try:
        room = manager.find(data.get("code"), client_key(sid), now())
        p = room.join(data.get("nickname"), data.get("character"), data.get("color"), now())
    except GameError as e:
        return err(e)
    p.sid = sid
    sessions[sid] = {"code": room.code, "role": "player", "token": p.token}
    await sio.enter_room(sid, room.code)
    await broadcast(room)
    return {"ok": True, "code": room.code, "token": p.token, "pid": p.pid}


@sio.on("rejoin")
async def on_rejoin(sid, data):
    """새로고침·끊김 복구. 호스트 토큰 또는 참가자 토큰."""
    try:
        room = manager.find(data.get("code"), client_key(sid), now())
        token = data.get("token") or ""
        if token == room.host_token:
            sessions[sid] = {"code": room.code, "role": "host", "token": token}
            await sio.enter_room(sid, room.code)
            await sio.emit("state", room.public_state(now()), to=sid)
            return {"ok": True, "role": "host", "code": room.code}
        p = room.reconnect(token, sid, now())
    except GameError as e:
        return err(e)
    sessions[sid] = {"code": room.code, "role": "player", "token": token}
    await sio.enter_room(sid, room.code)
    await broadcast(room)
    await push_self(room, sid, p)
    return {"ok": True, "role": "player", "code": room.code, "pid": p.pid}


@sio.on("assign_teams")
async def on_assign_teams(sid, data=None):
    try:
        _, room = host_ctx(sid)
        room.assign_teams()
    except GameError as e:
        return err(e)
    await broadcast(room)
    return {"ok": True}


@sio.on("set_team")
async def on_set_team(sid, data):
    try:
        _, room = host_ctx(sid)
        team = data.get("team")
        room.set_team(data.get("pid"), None if team in (None, "") else int(team))
    except (GameError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    await broadcast(room)
    return {"ok": True}


@sio.on("start_game")
async def on_start_game(sid, data=None):
    try:
        _, room = host_ctx(sid)
        room.start(now())
    except GameError as e:
        return err(e)
    await broadcast(room)
    await push_all_me(room)
    return {"ok": True}


@sio.on("end_game")
async def on_end_game(sid, data=None):
    try:
        _, room = host_ctx(sid)
        room.force_end(now())
    except GameError as e:
        return err(e)
    await broadcast(room)
    await drain_notices(room)
    return {"ok": True}


@sio.on("kick")
async def on_kick(sid, data):
    try:
        _, room = host_ctx(sid)
        pid = data.get("pid")
        target = room._by_pid(pid)
        if target and target.sid:
            await sio.emit("kicked", {}, to=target.sid)
            sessions.pop(target.sid, None)
        room.kick(pid)
    except GameError as e:
        return err(e)
    await broadcast(room)
    return {"ok": True}


@sio.on("move")
async def on_move(sid, data):
    """이동은 가벼운 cursor 이벤트만 보낸다 (전체 상태는 주기적으로 전송)."""
    try:
        s, room, p = player_ctx(sid)
        idx = room.move(s["token"], int(data.get("dx", 0)), int(data.get("dy", 0)), now())
    except (GameError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    await sio.emit("cursor", {"pid": p.pid, "cursor": idx}, room=room.code)
    return {"ok": True}


async def run_action(sid, fn):
    try:
        s, room, p = player_ctx(sid)
        res = fn(room, s["token"])
    except GameError as e:
        return err(e)
    await after_action(room, sid, p)
    return {"ok": True, **(res or {})}


@sio.on("select")
async def on_select(sid, data=None):
    def go(r, t):
        r.select(t, now())
    return await run_action(sid, go)


@sio.on("cancel")
async def on_cancel(sid, data=None):
    return await run_action(sid, lambda r, t: r.cancel(t, now()))


@sio.on("submit")
async def on_submit(sid, data):
    return await run_action(sid, lambda r, t: r.submit(t, str(data.get("text", "")), now()))


@sio.on("answer")
async def on_answer(sid, data):
    def go(r, t):
        try:
            n = int(data.get("n"))
        except (TypeError, ValueError):
            raise GameError("보기 번호를 입력하세요.")
        return r.answer(t, n, now())
    return await run_action(sid, go)


@sio.on("use_item")
async def on_use_item(sid, data):
    return await run_action(sid, lambda r, t: r.use_item(t, str(data.get("name", "")), now()))


async def ticker() -> None:
    n = 0
    while True:
        await asyncio.sleep(0.5)
        n += 1
        t = now()
        for room in list(manager.rooms.values()):
            if room.state != "playing":
                continue
            before = room.state
            expired = room.tick(t)
            if expired or room.notices or before != room.state or n % 4 == 0:
                request_broadcast(room, 0.05)
            await drain_notices(room)
            if n % 2 == 0 or before != room.state:
                await push_all_me(room)
        for code in manager.cleanup(t):
            for sid in [k for k, v in sessions.items() if v["code"] == code]:
                sessions.pop(sid, None)
            await sio.close_room(code)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(ticker())
    yield
    task.cancel()


fastapi_app = FastAPI(lifespan=lifespan)


@fastapi_app.get("/health")
async def health():
    return {"ok": True}


@fastapi_app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


fastapi_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 문제 은행(data/)은 정적 경로에 두지 않는다. 정적 파일은 static/ 아래만 공개된다.
# uvicorn main:app 이 이 객체를 실행한다 (Socket.IO + FastAPI)
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
