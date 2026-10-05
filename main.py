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

from game import CHARACTERS, COLORS, GameError, RoomManager

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


async def broadcast(room) -> None:
    await sio.emit("state", room.public_state(now()), room=room.code)


async def push_self(room, sid: str, player) -> None:
    """개인 영역 정보: 선택 중인 명령어는 본인에게만 보낸다."""
    t = now()
    await sio.emit("me", {
        "pid": player.pid,
        "command": player.command,
        "selectLeft": max(0.0, player.select_deadline - t) if player.selected is not None else 0,
        "selected": player.selected,
    }, to=sid)


def ctx(sid: str):
    s = sessions.get(sid)
    if not s:
        raise GameError("방에 먼저 입장하세요.")
    room = manager.rooms.get(s["code"])
    if room is None:
        raise GameError("방이 사라졌어요.")
    return s, room


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
    return {"colors": COLORS, "characters": CHARACTERS}


@sio.on("create_room")
async def on_create_room(sid, data=None):
    data = data or {}
    try:
        room = manager.create_room(now(), int(data.get("duration") or 300))
    except (GameError, ValueError) as e:
        return {"ok": False, "error": str(e)}
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


@sio.on("start_game")
async def on_start_game(sid, data=None):
    try:
        s, room = ctx(sid)
        if s["role"] != "host":
            raise GameError("진행자만 시작할 수 있어요.")
        room.start(now())
    except GameError as e:
        return err(e)
    await broadcast(room)
    return {"ok": True}


@sio.on("kick")
async def on_kick(sid, data):
    try:
        s, room = ctx(sid)
        if s["role"] != "host":
            raise GameError("진행자만 내보낼 수 있어요.")
        pid = data.get("pid")
        target = next((p for p in room.players.values() if p.pid == pid), None)
        if target and target.sid:
            await sio.emit("kicked", {}, to=target.sid)
        room.kick(pid)
    except GameError as e:
        return err(e)
    await broadcast(room)
    return {"ok": True}


def player_ctx(sid):
    s, room = ctx(sid)
    if s["role"] != "player":
        raise GameError("참가자만 할 수 있어요.")
    return s, room, room.players.get(s["token"])


@sio.on("move")
async def on_move(sid, data):
    try:
        s, room, p = player_ctx(sid)
        room.move(s["token"], int(data.get("dx", 0)), int(data.get("dy", 0)), now())
    except (GameError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    await broadcast(room)
    return {"ok": True}


@sio.on("select")
async def on_select(sid, data=None):
    try:
        s, room, p = player_ctx(sid)
        room.select(s["token"], now())
    except GameError as e:
        return err(e)
    await broadcast(room)
    await push_self(room, sid, p)
    return {"ok": True}


@sio.on("cancel")
async def on_cancel(sid, data=None):
    try:
        s, room, p = player_ctx(sid)
        room.cancel(s["token"], now())
    except GameError as e:
        return err(e)
    await broadcast(room)
    await push_self(room, sid, p)
    return {"ok": True}


@sio.on("submit")
async def on_submit(sid, data):
    try:
        s, room, p = player_ctx(sid)
        res = room.submit(s["token"], str(data.get("text", "")), now())
    except GameError as e:
        return err(e)
    await broadcast(room)
    await push_self(room, sid, p)
    return {"ok": True, **res}


async def ticker() -> None:
    while True:
        await asyncio.sleep(0.5)
        t = now()
        for room in list(manager.rooms.values()):
            if room.state != "playing":
                continue
            before = room.state
            expired = room.tick(t)
            for p in room.players.values():
                if p.pid in expired and p.sid:
                    await sio.emit("select_timeout", {}, to=p.sid)
                    await push_self(room, p.sid, p)
            # 남은 시간 표시를 위해 진행 중인 방은 주기적으로 상태를 보낸다
            await broadcast(room)
            if before != room.state:
                for p in room.players.values():
                    if p.sid:
                        await push_self(room, p.sid, p)
        for code in manager.cleanup(t):
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
