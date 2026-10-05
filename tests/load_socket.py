"""36명(9팀) 부하 점검: 사람처럼 이동·점령·뺏기·아이템을 무작위로 시도한다.
사용: uvicorn main:app --port 8765 & python tests/load_socket.py [초]"""
import asyncio, json, pathlib, random, sys, time, socketio

BANK = json.loads((pathlib.Path(__file__).parent.parent / "data/questions.json").read_text())
ANS = {q["command"]: q for q in BANK}
URL = "http://localhost:8765"
DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 60
COLORS = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#B8B8FF", "#FF8A8A"]
ITEMS = ["bonus()", "x2", "sleep(5)", "blur()", "try/except", "private", "hint()"]
stats = {"captured": 0, "stolen": 0, "wrong": 0, "errors": 0, "items": 0, "state_bytes": 0, "states": 0}


async def player(i, code, stop):
    c = socketio.AsyncClient()
    box = {"me": {}}
    c.on("me", lambda m: box.update(me=m))
    def on_state(s):
        stats["states"] += 1; stats["state_bytes"] += len(json.dumps(s))
    c.on("state", on_state)
    await c.connect(URL)
    r = await c.call("join_room", {"code": code, "nickname": f"u{i}", "character": "cat", "color": COLORS[i % 9]})
    assert r["ok"], r
    box["pid"] = r["pid"]
    await stop["start"].wait()
    rng = random.Random(i)
    while time.time() < stop["end"]:
        try:
            for _ in range(rng.randint(1, 6)):
                await c.call("move", {"dx": rng.choice([-1, 0, 1]), "dy": rng.choice([-1, 0, 1])})
                await asyncio.sleep(0.02)
            if box["me"].get("items") and rng.random() < 0.5:
                u = await c.call("use_item", {"name": rng.choice(box["me"]["items"])})
                stats["items"] += u.get("ok", False)
            r = await c.call("select")
            if not r["ok"]:
                await asyncio.sleep(0.05); continue
            await asyncio.sleep(0.15)
            cmd = box["me"].get("command")
            if not cmd:
                continue
            await asyncio.sleep(rng.uniform(0.1, 0.6))
            r = await c.call("submit", {"text": cmd})
            if r.get("result") == "captured": stats["captured"] += 1
            elif r.get("result") == "quiz":
                await asyncio.sleep(0.2)
                q = ANS[cmd]["quiz"]
                texts = [x["text"] for x in box["me"]["quiz"]["choices"]]
                pos = texts.index(q["choices"][q["answer"]]) + 1 if rng.random() < 0.6 else rng.randint(1, 4)
                a = await c.call("answer", {"n": pos})
                if a.get("result") == "stolen": stats["stolen"] += 1
                elif a.get("result") in ("wrong", "timeout"): stats["wrong"] += 1
        except Exception as e:  # noqa
            stats["errors"] += 1; print("err", repr(e)[:120])
    await c.disconnect()


async def main():
    host = socketio.AsyncClient(); await host.connect(URL)
    r = await host.call("create_room", {"mode": "team", "map": "circle", "tags": ["출력", "변수", "반복문"], "duration": 180,
                                        "item_start": 90, "max_players": 36})
    code = r["code"]
    stop = {"start": asyncio.Event(), "end": 0}
    tasks = [asyncio.create_task(player(i, code, stop)) for i in range(36)]
    await asyncio.sleep(3)
    assert (await host.call("assign_teams"))["ok"]
    r = await host.call("start_game"); assert r["ok"], r
    stop["end"] = time.time() + DUR; stop["start"].set()
    t0 = time.time()
    await asyncio.gather(*tasks)
    final = await host.call("end_game")
    print("elapsed", round(time.time() - t0), "stats", stats, "end", final)
    await host.disconnect()

asyncio.run(main())
