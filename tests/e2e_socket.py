"""실행 중인 서버(포트 8765)에 두 명이 붙는 수동 점검 스크립트."""
import asyncio, socketio

async def main():
    host, a = socketio.AsyncClient(), socketio.AsyncClient()
    states = []
    mine = {}
    a.on("state", lambda s: states.append(s))
    a.on("me", lambda m: mine.update(m))
    for c in (host, a):
        await c.connect("http://localhost:8765")
    r = await host.call("create_room", {"duration": 180})
    code = r["code"]; print("room", code)
    j = await a.call("join_room", {"code": code, "nickname": "tester", "character": "cat", "color": "#E69F00"})
    print("join", j["ok"])
    print("start", await host.call("start_game", {}))
    print("move", await a.call("move", {"dx": 1, "dy": 0}))
    print("select", await a.call("select", {}))
    await asyncio.sleep(0.3)
    cmd = mine["command"]; print("cmd", cmd)
    print("wrong", await a.call("submit", {"text": "nope"}))
    print("ok", await a.call("submit", {"text": cmd}))
    await asyncio.sleep(0.8)
    st = states[-1]
    print("score", st["standings"][0]["score"], "leak", cmd in str(st))
    await host.disconnect(); await a.disconnect()
asyncio.run(main())
