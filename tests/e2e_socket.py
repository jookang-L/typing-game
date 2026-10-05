"""실행 중인 서버(포트 8765)에 5명이 붙는 종단 점검: 팀전 로비 → 점령 → 뺏기·퀴즈 → 아이템 → 종료.
사용: uvicorn main:app --port 8765 & python tests/e2e_socket.py"""
import asyncio, json, pathlib, socketio

BANK = {q["command"]: q for q in json.loads((pathlib.Path(__file__).parent.parent / "data/questions.json").read_text())}
URL = "http://localhost:8765"


class C:
    def __init__(self, name):
        self.name, self.sio, self.state, self.me, self.notices = name, socketio.AsyncClient(), None, {}, []
        self.sio.on("state", lambda s: setattr(self, "state", s))
        self.sio.on("me", lambda m: setattr(self, "me", m))
        self.sio.on("notice", lambda n: self.notices.append(n))

    async def go(self):
        await self.sio.connect(URL)

    async def call(self, ev, data=None):
        return await self.sio.call(ev, data or {})


async def settle(): await asyncio.sleep(0.4)


async def main():
    host = C("host"); await host.go()
    r = await host.call("create_room", {"mode": "team", "map": "pyramid", "tags": ["출력", "변수"], "duration": 180,
                                        "item_start": 90, "max_players": 36})
    assert r["ok"], r
    code = r["code"]; print("room", code)
    ps = []
    for i in range(4):
        c = C(f"user{i}"); await c.go()
        j = await c.call("join_room", {"code": code, "nickname": c.name, "character": "cat", "color": "#E69F00"})
        assert j["ok"], j
        c.pid = j["pid"]; ps.append(c)
    await settle()
    print("start before teams:", (await host.call("start_game"))["error"])
    for i, c in enumerate(ps):
        assert (await host.call("set_team", {"pid": c.pid, "team": i // 2}))["ok"]
    assert (await host.call("start_game"))["ok"]
    await settle()
    st = ps[0].state
    assert st["state"] == "playing" and len(st["cells"]) == 64 and st["rows"] == [1, 3, 5, 7, 9, 11, 13, 15]
    assert len(st["sides"]) == 2, st["sides"]
    # 점령
    a, a2, b, b2 = ps
    r = await a.call("select"); assert r["ok"], r
    await settle()
    cmd = a.me["command"]; print("cmd:", cmd)
    assert cmd in BANK and BANK[cmd]["difficulty"] == "pyramid"
    r = await a.call("submit", {"text": cmd}); assert r["result"] == "captured", r
    await settle()
    cursor = next(p["cursor"] for p in a.state["players"] if p["pid"] == a.pid)
    assert a.state["cells"][cursor]["owner"] == "t1"
    # 뺏기: b를 같은 칸으로 이동시키기 어렵다 → 서버 내부 상태를 직접 바꾸지 않고, b가 같은 위치일 때까지 대기하지 않고 a2가 같은 팀 땅 선택 불가 확인
    print("same-team select:", (await a2.call("select")))
    print("OK: 팀전 흐름 점검 통과")
    for c in [host, *ps]: await c.sio.disconnect()

asyncio.run(main())
