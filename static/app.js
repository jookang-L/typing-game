/* 얇은 화면 계층: 서버 상태를 그리고 입력을 서버로 보낸다. 정답/판정은 서버가 한다. */
const $ = (id) => document.getElementById(id);
const sock = io();
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  del(k) { try { localStorage.removeItem(k); } catch {} },
};

const ADJ = ["빠른", "용감한", "졸린", "똑똑한", "수줍은", "씩씩한", "느긋한", "반짝이는"];
const NOUN = ["고양이", "코더", "거북이", "토끼", "로봇", "여우", "펭귄", "다람쥐"];
const randNick = () => ADJ[Math.floor(Math.random() * ADJ.length)] + NOUN[Math.floor(Math.random() * NOUN.length)] + Math.floor(Math.random() * 90 + 10);

let S = { role: null, pid: null, state: null, me: null, recvAt: 0, char: null, color: null };

function show(id) {
  for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== id;
  lucide.createIcons();
}
let toastTimer;
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}
const icon = (name) => `<i data-lucide="${name}"></i>`;

/* ---------- 입장 화면 ---------- */
function buildPickers(meta) {
  S.char = S.char || meta.characters[0];
  S.color = S.color || meta.colors[0];
  $("chars").innerHTML = meta.characters.map((c) => `<button type="button" data-c="${c}" class="${c === S.char ? "sel" : ""}" aria-label="${c}">${icon(c)}</button>`).join("");
  $("colors").innerHTML = meta.colors.map((c) => `<button type="button" data-col="${c}" class="${c === S.color ? "sel" : ""}" aria-label="색상 ${c}"><span class="swatch" style="background:${c}"></span></button>`).join("");
  lucide.createIcons(); updatePreview();
}
function updatePreview() {
  $("preview").innerHTML = `<span class="chip" style="--c:${S.color}">${icon(S.char)} ${escapeHtml($("nick").value || "…")}</span>`;
  lucide.createIcons();
}
const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

$("chars").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.char = b.dataset.c; for (const x of $("chars").children) x.classList.toggle("sel", x === b); updatePreview(); });
$("colors").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.color = b.dataset.col; for (const x of $("colors").children) x.classList.toggle("sel", x === b); updatePreview(); });
$("nick").addEventListener("input", updatePreview);
$("reroll").onclick = () => { $("nick").value = randNick(); updatePreview(); };
$("tab-join").onclick = () => setTab("join");
$("tab-host").onclick = () => setTab("host");
function setTab(t) {
  $("tab-join").classList.toggle("active", t === "join"); $("tab-host").classList.toggle("active", t === "host");
  $("join-form").hidden = t !== "join"; $("host-form").hidden = t !== "host";
}
$("dur").innerHTML = [3, 4, 5, 6, 7, 8, 9, 10].map((m) => `<option value="${m * 60}" ${m === 5 ? "selected" : ""}>${m}분</option>`).join("");

$("join-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sock.emit("join_room", { code: $("code").value.trim().toUpperCase(), nickname: $("nick").value, character: S.char, color: S.color }, (r) => {
    if (!r.ok) return toast(r.error);
    S.role = "player"; S.pid = r.pid;
    store.set("code", r.code); store.set("token", r.token); store.set("role", "player");
    show("v-lobby"); render();
  });
});
$("host-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sock.emit("create_room", { duration: Number($("dur").value) }, (r) => {
    if (!r.ok) return toast(r.error);
    S.role = "host";
    store.set("code", r.code); store.set("token", r.hostToken); store.set("role", "host");
    show("v-lobby"); render();
  });
});
$("start").onclick = () => sock.emit("start_game", {}, (r) => { if (!r.ok) toast(r.error); });
$("again").onclick = () => { ["code", "token", "role"].forEach(store.del); location.reload(); };

/* ---------- 상태 수신 ---------- */
sock.on("state", (st) => { S.state = st; S.recvAt = performance.now(); render(); });
sock.on("me", (m) => { S.me = m; S.meAt = performance.now(); renderMe(); });
sock.on("select_timeout", () => toast("시간 초과! 잠금이 풀렸어요."));
sock.on("kicked", () => { ["code", "token", "role"].forEach(store.del); toast("진행자가 내보냈어요."); setTimeout(() => location.reload(), 800); });

sock.on("connect", () => {
  const code = store.get("code"), token = store.get("token");
  if (!code || !token) return;
  sock.emit("rejoin", { code, token }, (r) => {
    if (!r.ok) { ["code", "token", "role"].forEach(store.del); return; }
    S.role = r.role; S.pid = r.pid || null;
    show("v-lobby"); render();
  });
});

function render() {
  const st = S.state; if (!st) return;
  const inRoom = S.role !== null;
  if (!inRoom) return;
  if (st.state === "lobby") {
    show("v-lobby");
    $("lobby-code").textContent = st.code;
    $("lobby-list").innerHTML = st.players.map((p) => `<li class="chip" style="--c:${p.color}">${icon(p.character)} ${escapeHtml(p.nickname)}${p.connected ? "" : " (끊김)"}</li>`).join("") || '<li class="muted">아직 아무도 없어요</li>';
    $("start").hidden = S.role !== "host"; $("lobby-wait").hidden = S.role === "host";
    lucide.createIcons();
  } else if (st.state === "playing") {
    if ($("v-game").hidden) show("v-game");
    renderGame(st);
  } else if (st.state === "ended") {
    if ($("v-end").hidden) show("v-end");
    $("final").innerHTML = st.standings.map((r) => `<li class="${r.pid === S.pid ? "me" : ""}">${icon(r.character)} ${escapeHtml(r.nickname)} <span class="muted">${r.rank}위 · ${r.cells}칸</span><span class="pts">${r.score}점</span></li>`).join("");
    lucide.createIcons();
  }
}

function renderGame(st) {
  $("g-code").textContent = st.code;
  $("g-role").textContent = S.role === "host" ? "진행자 (관전)" : "";
  $("me").hidden = S.role !== "player";
  const board = $("board");
  board.style.gridTemplateColumns = `repeat(${st.side}, 1fr)`;
  const byPid = Object.fromEntries(st.players.map((p) => [p.pid, p]));
  const cursorsAt = {};
  for (const p of st.players) (cursorsAt[p.cursor] ||= []).push(p);
  board.innerHTML = st.cells.map((c, i) => {
    const owner = c.owner && byPid[c.owner];
    const lk = c.lockedBy && byPid[c.lockedBy];
    const mine = S.pid && cursorsAt[i]?.some((p) => p.pid === S.pid);
    const others = (cursorsAt[i] || []).filter((p) => p.pid !== S.pid).map((p) => `<span class="dot" style="--c:${p.color}"></span>`).join("");
    const style = (owner ? `--c:${owner.color};` : lk ? `--c:${lk.color};` : "");
    return `<div class="cell ${owner ? "owned" : ""} ${lk ? "locked" : ""} ${mine ? "me-cursor" : ""}" style="${style}">
      <span class="stars">${"★".repeat(c.stars)}</span>${lk ? `<span class="lock">✎</span>` : ""}<span class="others">${others}</span></div>`;
  }).join("");
  $("rank").innerHTML = st.standings.map((r) => `<li class="${r.pid === S.pid ? "me" : ""}"><span class="chip" style="--c:${r.color}">${icon(r.character)}</span> ${escapeHtml(r.nickname)}${r.pid === S.pid ? " (나)" : ""}<span class="pts">${r.score}</span></li>`).join("");
  const mineRow = st.standings.find((r) => r.pid === S.pid);
  if (mineRow) { $("my-score").textContent = mineRow.score; $("my-cells").textContent = mineRow.cells; }
  lucide.createIcons();
}

setInterval(() => {
  const st = S.state; if (!st || st.state !== "playing") return;
  const left = Math.max(0, st.timeLeft - (performance.now() - S.recvAt) / 1000);
  $("g-time").textContent = `${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, "0")}`;
  if (S.me?.selected != null && S.me.selectLeft) {
    const l = Math.max(0, S.me.selectLeft - (performance.now() - S.meAt) / 1000);
    $("selbar").style.width = `${(l / 20) * 100}%`;
  }
}, 250);

/* ---------- 내 개인 영역: 입력 모드 ---------- */
function renderMe() {
  const m = S.me; const selecting = m && m.selected != null && m.command;
  $("cmdline").hidden = !selecting;
  $("hint").textContent = selecting ? "명령어를 그대로 입력하세요 · Esc: 취소" : "방향키로 이동 · Enter로 칸 선택";
  if (selecting) { $("typing").value = ""; paint(""); $("typing").focus(); }
  else $("typing").blur();
}
function paint(val) {
  const cmd = S.me?.command || "";
  let html = "";
  for (let i = 0; i < cmd.length; i++) {
    const ch = escapeHtml(cmd[i]);
    if (i < val.length) html += val[i] === cmd[i] ? `<span class="good">${ch}</span>` : `<span class="badc">${ch}</span>`;
    else html += `<span class="rest">${ch}</span>`;
  }
  $("cmdtext").innerHTML = html;
}
let submitting = false;
function submit(text) {
  if (submitting) return; submitting = true;
  sock.emit("submit", { text }, (r) => {
    submitting = false;
    if (!r.ok) return toast(r.error);
    if (r.result === "captured") toast(`점령 성공! +${r.gained}점`);
    else if (r.result === "wrong") toast("틀렸어요. 다시 입력하세요.");
    else if (r.result === "timeout") toast("시간 초과! 잠금이 풀렸어요.");
  });
}
$("typing").addEventListener("input", (e) => {
  const v = e.target.value; paint(v);
  if (/[ㄱ-ㅎㅏ-ㅣ가-힣]/.test(v)) toast("한/영 키를 확인하세요 (영문으로 입력)");
  if (S.me?.command && v.trim() === S.me.command) submit(v);
});
document.addEventListener("keydown", (e) => {
  if ($("v-game").hidden || S.role !== "player") return;
  const selecting = S.me && S.me.selected != null && S.me.command;
  if (selecting) {
    if (e.key === "Escape") { e.preventDefault(); sock.emit("cancel", {}); }
    else if (e.key === "Enter") { e.preventDefault(); submit($("typing").value); }
    else if (document.activeElement !== $("typing") && e.key.length === 1) $("typing").focus();
    return;
  }
  const dir = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] }[e.key];
  if (dir) { e.preventDefault(); sock.emit("move", { dx: dir[0], dy: dir[1] }); }
  else if (e.key === "Enter") { e.preventDefault(); sock.emit("select", {}, (r) => { if (!r.ok) toast(r.error); }); }
});

/* ---------- 시작 ---------- */
$("nick").value = randNick();
sock.emit("meta", {}, buildPickers);
show("v-entry");
