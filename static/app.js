/* 얇은 화면 계층: 서버 상태를 그리고 입력을 서버로 보낸다. 판정·정답은 모두 서버가 한다. */
const $ = (id) => document.getElementById(id);
const sock = io();
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  del(k) { try { localStorage.removeItem(k); } catch {} },
};
const clearSession = () => ["code", "token", "role"].forEach(store.del);

const ADJ = ["빠른", "용감한", "졸린", "똑똑한", "수줍은", "씩씩한", "느긋한", "반짝이는"];
const NOUN = ["고양이", "코더", "거북이", "토끼", "로봇", "여우", "펭귄", "다람쥐"];
const randNick = () => ADJ[Math.floor(Math.random() * ADJ.length)] + NOUN[Math.floor(Math.random() * NOUN.length)] + Math.floor(Math.random() * 90 + 10);
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (name) => `<i data-lucide="${name}"></i>`;
const fmt = (sec) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
const isHangul = (s) => /[ㄱ-ㅎㅏ-ㅣ가-힣]/.test(s);
function fgFor(hex) {
  const n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
  return (0.299 * r + 0.587 * g + 0.114 * b) > 140 ? "#111" : "#fff";
}

const S = { role: null, pid: null, state: null, me: null, recvAt: 0, meAt: 0, meta: null, char: null, color: null, result: null, resultAt: 0 };

function show(id) {
  for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== id;
  lucide.createIcons();
}
let toastTimer;
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}
let bannerTimer;
function banner(msg) {
  const b = $("banner"); b.textContent = msg; b.hidden = false;
  clearTimeout(bannerTimer); bannerTimer = setTimeout(() => (b.hidden = true), 3500);
}

/* ================= 입장 화면 ================= */
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
$("chars").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.char = b.dataset.c; for (const x of $("chars").children) x.classList.toggle("sel", x === b); updatePreview(); });
$("colors").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; S.color = b.dataset.col; for (const x of $("colors").children) x.classList.toggle("sel", x === b); updatePreview(); });
$("nick").addEventListener("input", updatePreview);
$("reroll").onclick = () => { $("nick").value = randNick(); updatePreview(); };
function setTab(t) {
  $("tab-join").classList.toggle("active", t === "join"); $("tab-host").classList.toggle("active", t === "host");
  $("entry-card").hidden = t === "host"; $("host-card").hidden = t !== "host";
  if (t === "host") refreshHostForm();
}
$("tab-join").onclick = () => setTab("join");
$("tab-host").onclick = () => setTab("host");
$("h-back").onclick = () => setTab("join");

$("join-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sock.emit("join_room", { code: $("code").value.trim().toUpperCase(), nickname: $("nick").value, character: S.char, color: S.color }, (r) => {
    if (!r.ok) return toast(r.error);
    S.role = "player"; S.pid = r.pid;
    store.set("code", r.code); store.set("token", r.token); store.set("role", "player");
    show("v-lobby"); render();
  });
});

/* ================= 방 만들기 (교사) ================= */
function hostSettings() {
  const f = $("host-form");
  const mode = f.elements.mode.value;
  const dur = Number($("h-dur").value);
  const item = $("h-item").value;
  return {
    mode, map: $("h-map").value,
    tags: [...document.querySelectorAll("#h-tags input:checked")].map((i) => i.value),
    max_players: Number($("h-max").value), duration: dur,
    item_start: item === "" ? null : Number(item),
    hide_last_minute: $("h-hide").checked && dur >= S.meta.hideMinDuration,
  };
}
function refreshHostForm() {
  const m = S.meta; if (!m) return;
  if (!$("h-map").options.length) {
    $("h-map").innerHTML = m.maps.map((x) => `<option value="${x.id}">${x.label}</option>`).join("");
    $("h-dur").innerHTML = [3, 4, 5, 6, 7, 8, 9, 10].map((x) => `<option value="${x * 60}" ${x === 5 ? "selected" : ""}>${x}분</option>`).join("");
  }
  const map = $("h-map").value, dur = Number($("h-dur").value);
  const checked = new Set([...document.querySelectorAll("#h-tags input:checked")].map((i) => i.value));
  $("h-tags").innerHTML = m.tags.map((t) => {
    const n = (m.tagCounts[map] || {})[t] || 0, off = n < m.minQuestions;
    return `<label class="tag ${off ? "off" : ""}"><input type="checkbox" value="${t}" ${off ? "disabled" : ""} ${checked.has(t) && !off ? "checked" : ""}> ${t} <small>${n}문제${off ? " · 선택 불가" : ""}</small></label>`;
  }).join("");
  const prevItem = $("h-item").value;
  const opts = (m.itemStartOptions[String(dur)] || []);
  $("h-item").innerHTML = `<option value="">아이템 없음</option>` + opts.map((s) => `<option value="${s}">${fmt(s)}부터</option>`).join("");
  if ([...$("h-item").options].some((o) => o.value === prevItem)) $("h-item").value = prevItem;
  $("h-hide").disabled = dur < m.hideMinDuration;
  if ($("h-hide").disabled) $("h-hide").checked = false;
  const solo = $("host-form").elements.mode.value === "solo";
  $("h-max").min = solo ? 2 : 4; $("h-max").max = solo ? 9 : 36;
  if (solo && Number($("h-max").value) > 9) $("h-max").value = 9;
  if (!solo && Number($("h-max").value) < 4) $("h-max").value = 36;
  const mp = m.maps.find((x) => x.id === map);
  $("h-preview-map").innerHTML = mp.rows.map((n) => `<div class="mini-row">${'<span class="mini-cell"></span>'.repeat(n)}</div>`).join("");
  const s = hostSettings();
  $("h-summary").innerHTML = [solo ? "개인전" : "팀전 (4인 1팀)", mp.label, `${dur / 60}분`, s.item_start == null ? "아이템 없음" : `아이템 ${fmt(s.item_start)}부터`, s.hide_last_minute ? "마지막 1분 점수 비공개" : ""].filter(Boolean).map((x) => `<li>${x}</li>`).join("");
}
$("host-form").addEventListener("change", refreshHostForm);
$("host-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sock.emit("create_room", hostSettings(), (r) => {
    if (!r.ok) return toast(r.error);
    S.role = "host";
    store.set("code", r.code); store.set("token", r.hostToken); store.set("role", "host");
    show("v-lobby"); render();
  });
});

/* ================= 소켓 이벤트 ================= */
sock.on("state", (st) => { S.state = st; S.recvAt = performance.now(); render(); });
sock.on("me", (m) => { S.me = m; S.meAt = performance.now(); renderMe(true); });
sock.on("cursor", (c) => {
  const p = S.state?.players.find((x) => x.pid === c.pid);
  if (p) { p.cursor = c.cursor; updateCursors(); }
});
sock.on("kicked", () => { clearSession(); toast("진행자가 내보냈어요."); setTimeout(() => location.reload(), 900); });
sock.on("notice", (n) => {
  const st = S.state;
  const myName = (n.attacker_side && st) ? null : null;
  switch (n.type) {
    case "item_spawn": banner("✨ 아이템이 등장했습니다!"); break;
    case "hit": toast(`🌀 방해! ${n.item} 효과를 받았어요 (${n.seconds}초)`); break;
    case "blocked": toast("🛡 막혔습니다. 상대가 면역 상태였어요. 아이템은 소모됐어요."); break;
    case "defended": toast(`🛡 방해를 막았습니다! (${n.item})`); break;
    case "stolen": if (st && S.me && (n.attacker_side === S.me.side || n.victim_side === S.me.side)) toast(n.attacker_side === S.me.side ? "땅을 뺏었어요!" : `${n.attacker}님이 우리 땅을 뺏었어요! 복수 기회!`); break;
    case "quiz_timeout": showResult({ ok: true, ...n }); break;
  }
});
sock.on("connect", () => {
  const code = store.get("code"), token = store.get("token");
  if (!code || !token) return;
  sock.emit("rejoin", { code, token }, (r) => {
    if (!r.ok) { clearSession(); return; }
    S.role = r.role; S.pid = r.pid || null;
    show("v-lobby"); render();
  });
});

/* ================= 화면 그리기 ================= */
function sideIndexOf(st, sideId) {
  if (!sideId) return 0;
  if (sideId.startsWith("t")) return parseInt(sideId.slice(1), 10) - 1;
  return Math.max(0, st.players.findIndex((p) => p.pid === sideId));
}
function pidToSide(st) {
  const m = {};
  for (const s of st.sides) for (const x of s.members) m[x.pid] = s.id;
  return m;
}
const modeLabel = (s) => s.mode === "solo" ? "개인전" : "팀전";
const durLabel = (s) => `${s.duration / 60}분`;

function render() {
  const st = S.state; if (!st || !S.role) return;
  if (st.state === "lobby") renderLobby(st);
  else if (st.state === "playing") {
    if ($("v-game").hidden) { show("v-game"); S.board = null; }
    renderGame(st);
  } else if (st.state === "ended") {
    if ($("v-end").hidden) show("v-end");
    renderEnd(st);
  }
}

function renderLobby(st) {
  if ($("v-lobby").hidden) show("v-lobby");
  const s = st.settings, host = S.role === "host";
  const mapLabel = (S.meta?.maps.find((m) => m.id === s.map) || {}).label || s.map;
  $("lobby-code").textContent = st.code;
  $("lobby-summary").innerHTML = [modeLabel(s), mapLabel, durLabel(s), `태그: ${s.tags.join(", ")}`, s.itemStart == null ? "아이템 없음" : `아이템 ${fmt(s.itemStart)}부터`, s.hideLastMinute ? "마지막 1분 점수 비공개" : "", `${st.players.length}/${s.maxPlayers}명`].filter(Boolean).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
  const team = s.mode === "team";
  $("lobby-solo").hidden = team; $("lobby-team").hidden = !team;
  $("assign").hidden = !host;
  if (!team) {
    $("lobby-list").innerHTML = st.players.map((p) => `<li class="chip" style="--c:${p.color}">${icon(p.character)} ${escapeHtml(p.nickname)}${p.pid === S.pid ? " (나)" : ""}${p.connected ? "" : " (끊김)"}${host ? ` <button class="ghost kick" data-pid="${p.pid}" title="내보내기">✕</button>` : ""}</li>`).join("") || '<li class="muted">아직 아무도 없어요</li>';
  } else {
    const colors = S.meta.colors;
    const teams = {};
    for (const p of st.players) (teams[p.team == null ? "x" : p.team] ||= []).push(p);
    const ids = [...new Set([...Object.keys(teams).filter((k) => k !== "x").map(Number), 0, 1])].sort((a, b) => a - b);
    const opts = (cur) => `<option value="" ${cur == null ? "selected" : ""}>미배정</option>` + Array.from({ length: 9 }, (_, i) => `<option value="${i}" ${cur === i ? "selected" : ""}>${i + 1}팀</option>`).join("");
    const memberRow = (p) => `<div class="member"><span class="chip" style="--c:${p.color}">${icon(p.character)} ${escapeHtml(p.nickname)}${p.pid === S.pid ? " (나)" : ""}</span>${host ? `<select data-pid="${p.pid}" class="teamsel" aria-label="${escapeHtml(p.nickname)} 팀 이동">${opts(p.team)}</select><button class="ghost kick" data-pid="${p.pid}" title="내보내기">✕</button>` : ""}</div>`;
    let html = ids.map((t) => `<div class="team-box" style="--c:${colors[t]}"><h4><span>${t + 1}팀</span><span class="muted">${(teams[t] || []).length}/4</span></h4>${(teams[t] || []).map(memberRow).join("")}</div>`).join("");
    if (teams.x) html += `<div class="team-box" style="--c:#888"><h4><span>미배정</span><span class="muted">${teams.x.length}</span></h4>${teams.x.map(memberRow).join("")}</div>`;
    $("teams").innerHTML = html;
  }
  $("lobby-problem").textContent = host && st.startProblem ? st.startProblem : "";
  $("start").hidden = !host; $("start").disabled = !!st.startProblem;
  $("lobby-wait").hidden = host;
  lucide.createIcons();
}
$("assign").onclick = () => sock.emit("assign_teams", {}, (r) => { if (!r.ok) toast(r.error); });
$("start").onclick = () => sock.emit("start_game", {}, (r) => { if (!r.ok) toast(r.error); });
document.addEventListener("change", (e) => {
  if (e.target.classList?.contains("teamsel")) sock.emit("set_team", { pid: e.target.dataset.pid, team: e.target.value }, (r) => { if (!r.ok) toast(r.error); });
});
document.addEventListener("click", (e) => {
  const k = e.target.closest(".kick");
  if (k && confirm("내보낼까요?")) sock.emit("kick", { pid: k.dataset.pid }, (r) => { if (!r.ok) toast(r.error); });
});
$("endgame").onclick = () => { if (confirm("게임을 지금 종료할까요?")) sock.emit("end_game", {}, (r) => { if (!r.ok) toast(r.error); }); };
$("reduce").checked = store.get("reduce") === "1";
const applyReduce = () => document.body.classList.toggle("reduce", $("reduce").checked);
$("reduce").onchange = () => { store.set("reduce", $("reduce").checked ? "1" : "0"); applyReduce(); };
applyReduce();

/* ---------- 게임 화면 ---------- */
let cellEls = [];
function buildBoard(rows) {
  const sig = rows.join(",");
  if (S.board === sig) return;
  S.board = sig;
  const b = $("board"); b.innerHTML = ""; cellEls = [];
  for (const n of rows) {
    const row = document.createElement("div"); row.className = "brow";
    for (let c = 0; c < n; c++) { const el = document.createElement("div"); el.className = "cell"; row.appendChild(el); cellEls.push(el); }
    b.appendChild(row);
  }
  fitBoard();
}
function fitBoard() {
  const st = S.state; if (!st) return;
  const area = $("board-area"), rows = st.rows, gap = 3;
  const w = area.clientWidth, h = area.clientHeight;
  const cs = Math.max(18, Math.floor(Math.min((w - gap * (Math.max(...rows) - 1)) / Math.max(...rows), (h - gap * (rows.length - 1)) / rows.length)));
  $("board").style.setProperty("--cs", cs + "px"); $("board").style.setProperty("--gap", gap + "px");
}
new ResizeObserver(fitBoard).observe($("board-area"));

function renderGame(st) {
  buildBoard(st.rows);
  const host = S.role === "host";
  $("g-code").textContent = st.code;
  $("g-info").textContent = `${modeLabel(st.settings)} · ${(S.meta?.maps.find((m) => m.id === st.settings.map) || {}).label || ""}`;
  $("endgame").hidden = !host;
  $("me").hidden = host;
  const byPid = Object.fromEntries(st.players.map((p) => [p.pid, p]));
  const sideOf = pidToSide(st);
  const sideById = Object.fromEntries(st.sides.map((s) => [s.id, s]));
  st.cells.forEach((c, i) => {
    const el = cellEls[i]; if (!el) return;
    const owner = c.owner && sideById[c.owner];
    const lk = c.lockedBy && byPid[c.lockedBy];
    const pat = owner ? sideIndexOf(st, owner.id) : -1;
    let cls = "cell";
    if (owner) cls += ` owned pat-${pat}`;
    if (lk) cls += " locked";
    el.className = cls;
    if (owner) { el.style.setProperty("--c", owner.color); el.style.setProperty("--fg", fgFor(owner.color)); }
    if (lk) el.style.setProperty("--lc", lk.color);
    el.innerHTML = `<span class="stars">${"★".repeat(c.stars)}</span>${lk ? '<span class="lock">✎</span>' : ""}${c.item ? '<span class="item">?</span>' : ""}<span class="others"></span>`;
  });
  updateCursors();
  // 공격 중 표시
  const atk = [];
  st.cells.forEach((c) => {
    if (c.owner && c.lockedBy && sideOf[c.lockedBy] && sideOf[c.lockedBy] !== c.owner) {
      const a = byPid[c.lockedBy], v = sideById[c.owner];
      atk.push(`<span class="attack">⚔ ${escapeHtml(a.nickname)}${st.settings.mode === "team" ? ` (${escapeHtml(sideById[sideOf[a.pid]].name)})` : ""}님이 ${escapeHtml(v.name)}의 땅을 공격 중!</span>`);
    }
  });
  $("attacks").innerHTML = atk.slice(0, 4).join("");
  renderCards(st, sideOf);
  const mine = S.me && st.sides.find((s) => s.id === S.me.side);
  if (mine) {
    $("my-score").textContent = st.settings.mode === "team" ? `${mine.score ?? "?"} (평균 ${mine.avg ?? "?"})` : (mine.score ?? "?");
    $("my-rank").textContent = mine.rank ?? "?";
  }
  lucide.createIcons();
}
function updateCursors() {
  const st = S.state; if (!st || !cellEls.length) return;
  const at = {};
  for (const p of st.players) (at[p.cursor] ||= []).push(p);
  cellEls.forEach((el, i) => {
    const list = at[i] || [];
    el.classList.toggle("me-cursor", list.some((p) => p.pid === S.pid));
    const o = el.querySelector(".others");
    if (o) o.innerHTML = list.filter((p) => p.pid !== S.pid).map((p) => `<span class="dot" style="--c:${p.color}"></span>`).join("");
  });
}

function renderCards(st, sideOf) {
  const team = st.settings.mode === "team";
  const myside = S.pid ? sideOf[S.pid] : null;
  const ordered = [...st.sides].sort((a, b) => sideIndexOf(st, a.id) - sideIndexOf(st, b.id));
  const card = (s) => {
    const p = !team ? st.players.find((x) => x.pid === s.id) : null;
    const me = s.id === myside;
    const idx = sideIndexOf(st, s.id);
    const immune = team ? [] : (p && p.immuneLeft > 0 ? [p] : []);
    const shield = st.players.filter((x) => sideOf[x.pid] === s.id && x.immuneLeft > 0);
    const nums = team
      ? `<span>땅 ${s.cells}</span><span>합계 ${s.score ?? "?"}</span><span>평균 ${s.avg ?? "?"}</span>`
      : `<span>땅 ${s.cells}</span><span>점수 ${s.score ?? "?"}</span>`;
    const mem = team ? `<div class="mem">${s.members.map((m) => `<span class="${m.pid === S.pid ? "you" : ""}">${icon(m.character)} ${escapeHtml(m.nickname)}${m.pid === S.pid ? " (나)" : ""} · ${m.captures}칸 ${m.quizCorrect}정답 ${m.score ?? "?"}점</span>`).join("")}</div>` : "";
    const title = team ? escapeHtml(s.name) : `${icon(s.members[0]?.character || "cat")} ${escapeHtml(s.name)}`;
    return `<div class="card-win ${me ? "me" : ""}" style="--c:${s.color}"><div class="head"><span class="sw pat-${idx}"></span>${title}${shield.length ? ` <span class="shield" title="면역">🛡${Math.ceil(Math.max(...shield.map((x) => x.immuneLeft)))}</span>` : ""}<span class="me-label">${me ? (team ? "내 팀" : "나") : ""}</span></div><div class="nums"><span>#${s.rank ?? "?"}</span>${nums}</div>${mem}</div>`;
  };
  const half = Math.ceil(ordered.length / 2);
  $("col-left").innerHTML = ordered.slice(0, half).map(card).join("");
  $("col-right").innerHTML = ordered.slice(half).map(card).join("");
}

/* ---------- 내 개인 영역 ---------- */
function renderMe(fromServer) {
  const m = S.me; if (!m || S.role !== "player") return;
  const phase = m.phase;
  $("cmdline").hidden = phase !== "typing";
  $("quiz").hidden = phase !== "quiz";
  $("timebar").hidden = !phase;
  if (fromServer) {
    S.lastPhase !== phase && onPhaseChange(phase, m);
    S.lastPhase = phase;
    if (phase === "typing" && S.lastCmd !== m.command) { S.lastCmd = m.command; $("typing").value = ""; paint(""); $("typing").focus(); }
    if (phase !== "typing") S.lastCmd = null;
    if (phase === "quiz") renderQuiz(m.quiz);
  }
  $("slots").innerHTML = [0, 1].map((i) => `<div class="slot ${m.items[i] ? "full" : ""}">${m.items[i] ? escapeHtml(m.items[i]) : "빈 칸"}</div>`).join("");
  renderFx();
}
function onPhaseChange(phase, m) {
  if (phase === "typing") $("result").hidden = true;
  if (phase === null) { $("typing").blur(); $("typing").value = ""; }
}
function renderFx() {
  const m = S.me; if (!m) return;
  const el = (performance.now() - S.meAt) / 1000;
  const left = (v) => Math.max(0, v - el);
  const f = [];
  if (left(m.sleepLeft) > 0) f.push(`<span class="atk">😴 sleep ${Math.ceil(left(m.sleepLeft))}초 입력 금지</span>`);
  if (left(m.blurLeft) > 0) f.push(`<span class="atk">🌫 blur ${Math.ceil(left(m.blurLeft))}초</span>`);
  if (left(m.x2Left) > 0) f.push(`<span>✖2 ${Math.ceil(left(m.x2Left))}초</span>`);
  if (left(m.immuneLeft) > 0) f.push(`<span class="def">🛡 private ${Math.ceil(left(m.immuneLeft))}초</span>`);
  else if (left(m.privateCd) > 0) f.push(`<span>private 쿨타임 ${Math.ceil(left(m.privateCd))}초</span>`);
  if (m.hint) f.push(`<span>💡 hint: 다음 퀴즈 보기 2개 제거</span>`);
  if (m.revenge && left(m.revenge.left) > 0) f.push(`<span class="atk">⚔ 복수 기회: ${escapeHtml(m.revenge.name)} (${Math.ceil(left(m.revenge.left))}초)</span>`);
  $("me-fx").innerHTML = f.join("");
  $("me").classList.toggle("blur", left(m.blurLeft) > 0);
  const sleeping = left(m.sleepLeft) > 0;
  $("me").classList.toggle("sleeping", sleeping);
  $("typing").disabled = sleeping; $("itemInput").disabled = sleeping;
  const phase = m.phase;
  $("hint").textContent = sleeping ? "sleep! 잠시 입력할 수 없어요."
    : phase === "typing" ? "명령어를 그대로 입력하세요 (Enter 제출 · Esc 취소)"
    : phase === "quiz" ? "숫자 키 1~4로 답을 고르세요."
    : "방향키 이동 · Enter 칸 선택 · 글자를 치면 아이템 이름 입력 (예: bonus())";
  // 남은 시간 바
  if (phase === "typing") $("selbar").style.width = `${(left(m.selectLeft) / 20) * 100}%`;
  if (phase === "quiz" && m.quiz) $("selbar").style.width = `${(left(m.quiz.left) / 15) * 100}%`;
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
function renderQuiz(q) {
  if (!q) return;
  $("qtype").textContent = `퀴즈 · ${q.type}`;
  $("qtext").textContent = q.question;
  $("qchoices").innerHTML = q.choices.map((c, i) => `<li data-n="${i + 1}" class="${c.off ? "off" : ""}"><b>${i + 1}</b><span>${escapeHtml(c.text)}</span></li>`).join("");
}
$("qchoices").addEventListener("click", (e) => { const li = e.target.closest("li"); if (li && !li.classList.contains("off")) answer(Number(li.dataset.n)); });

function showResult(r) {
  const box = $("result");
  let html = "", cls = "bad";
  if (r.result === "captured") { cls = "good"; html = `✅ 점령 성공! +${r.gained}점${r.extra ? ` (x2 보너스 +${r.extra})` : ""}${r.item ? `<br>🎁 아이템 획득: <b>${escapeHtml(r.item)}</b>${r.replaced ? ` (${escapeHtml(r.replaced)}가 ${escapeHtml(r.item)}로 대체되었습니다)` : ""}` : ""}`; }
  else if (r.result === "stolen") { cls = "good"; html = `⚔ 땅을 뺏었어요! +${r.gained}점${r.extra ? ` (x2 보너스 +${r.extra})` : ""}<br>정답 ${r.correct}번 · ${escapeHtml(r.explanation || "")}`; }
  else if (r.result === "wrong" && r.explanation) html = `❌ 오답! 정답은 ${r.correct}번 · ${escapeHtml(r.explanation)}<br>같은 칸은 ${r.cooldown}초 뒤에 다시 도전할 수 있어요.`;
  else if (r.result === "timeout" && r.explanation) html = `⏰ 시간 초과! 정답은 ${r.correct}번 · ${escapeHtml(r.explanation)}<br>같은 칸은 ${r.cooldown}초 뒤에 다시 도전할 수 있어요.`;
  else if (r.result === "protected") html = "🛡 그 사이 보호 상태가 되어 뺏을 수 없어요.";
  else return;
  box.className = `result ${cls}`; box.innerHTML = html; box.hidden = false;
  S.resultAt = performance.now();
}

/* ---------- 입력 처리 ---------- */
let busy = false;
function act(event, data, cb) {
  if (busy) return; busy = true;
  sock.emit(event, data, (r) => { busy = false; if (!r.ok) toast(r.error); else cb && cb(r); });
}
function submitCmd(text) { act("submit", { text }, (r) => {
  if (r.result === "wrong") toast("틀렸어요. 다시 입력하세요.");
  else if (r.result === "timeout") toast("시간 초과! 잠금이 풀렸어요.");
  else showResult(r);
}); }
function answer(n) { act("answer", { n }, showResult); }
function useItem(name) {
  act("use_item", { name }, (r) => {
    if (r.result === "typo") return toast("아이템 이름이 달라요. 다시 입력하세요.");
    if (r.result === "missing") return toast("아이템이 없습니다.");
    if (r.blocked) return toast("막혔습니다. 아이템은 소모됐어요.");
    const msg = { "bonus()": `보너스 +${r.gained}점!`, x2: `x2 ${r.seconds}초 시작!`, "hint()": "다음 퀴즈에서 오답 2개가 사라져요.", private: `private! ${r.seconds}초간 방해 면역`, "try/except": `try/except! 최근 점령한 땅을 ${r.seconds}초간 보호`, "sleep(5)": `${r.target}님에게 sleep(5)!`, "blur()": `${r.target}님에게 blur()!` }[r.item];
    toast(msg || "아이템 사용!");
  });
}
$("typing").addEventListener("input", (e) => {
  const v = e.target.value; paint(v);
  if (isHangul(v)) toast("한/영 키를 확인하세요 (영문으로 입력)");
  if (S.me?.command && v.trim() === S.me.command) submitCmd(v);
});
$("itemInput").addEventListener("input", (e) => { if (isHangul(e.target.value)) toast("한/영 키를 확인하세요 (영문으로 입력)"); });
document.addEventListener("keydown", (e) => {
  if ($("v-game").hidden || S.role !== "player" || !S.me || e.ctrlKey || e.metaKey || e.altKey) return;
  const phase = S.me.phase;
  const inItem = document.activeElement === $("itemInput");
  if (inItem) {
    if (e.key === "Enter") { e.preventDefault(); const v = $("itemInput").value; $("itemInput").value = ""; $("itemInput").blur(); if (v.trim()) useItem(v); }
    else if (e.key === "Escape") { $("itemInput").value = ""; $("itemInput").blur(); }
    return;
  }
  if (phase === "quiz") {
    if (/^[1-4]$/.test(e.key)) { e.preventDefault(); answer(Number(e.key)); }
    return;
  }
  if (phase === "typing") {
    if (e.key === "Escape") { e.preventDefault(); act("cancel", {}); }
    else if (e.key === "Enter") { e.preventDefault(); submitCmd($("typing").value); }
    else if (document.activeElement !== $("typing") && e.key.length === 1) $("typing").focus();
    return;
  }
  const dir = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] }[e.key];
  if (dir) { e.preventDefault(); sock.emit("move", { dx: dir[0], dy: dir[1] }); }
  else if (e.key === "Enter") { e.preventDefault(); act("select", {}); }
  else if (e.key.length === 1) { e.preventDefault(); $("itemInput").value = e.key; $("itemInput").focus(); }
});

setInterval(() => {
  const st = S.state; if (!st || st.state !== "playing") return;
  const left = Math.max(0, st.timeLeft - (performance.now() - S.recvAt) / 1000);
  $("g-time").textContent = fmt(left);
  document.querySelector(".timer").classList.toggle("low", left <= 30);
  if (st.nextItemIn != null) $("g-items-next").textContent = `다음 아이템 ${fmt(Math.max(0, st.nextItemIn - (performance.now() - S.recvAt) / 1000))}`;
  else $("g-items-next").textContent = st.settings.itemStart == null ? "아이템 없음" : "아이템 가득";
  if (st.scoresHidden) $("g-info").textContent = "마지막 1분: 다른 사람 점수 비공개";
  renderFx();
  if (!$("result").hidden && performance.now() - S.resultAt > 9000) $("result").hidden = true;
}, 250);

/* ================= 종료 화면 ================= */
function renderEnd(st) {
  const team = st.settings.mode === "team";
  $("end-note").textContent = team ? "팀 순위는 팀원 수로 나눈 평균 점수 기준이에요." : "점수 → 보유 칸 수 → 먼저 득점한 순서로 순위를 정해요.";
  $("final").innerHTML = st.sides.map((s) => {
    const idx = sideIndexOf(st, s.id);
    const me = S.me && S.me.side === s.id;
    const title = team ? escapeHtml(s.name) : `${icon(s.members[0]?.character || "cat")} ${escapeHtml(s.name)}`;
    const table = team ? `<table class="mtable"><tr><th>이름</th><th>점령</th><th>퀴즈 정답</th><th>개인 점수</th></tr>${s.members.map((m) => `<tr><td>${escapeHtml(m.nickname)}</td><td>${m.captures}</td><td>${m.quizCorrect}</td><td>${m.score}</td></tr>`).join("")}</table>` : "";
    return `<div class="final-row ${me ? "me" : ""}" style="--c:${s.color}"><div class="rk">${s.rank}위</div><div style="flex:1"><b>${title}</b> <span class="muted">${s.cells}칸 (영토 ${s.territory} + 보너스 ${s.bonus})</span>${table}</div><div class="pts">${team ? `평균 ${s.avg}<br><small class="muted">합계 ${s.score}</small>` : `${s.score}점`}</div></div>`;
  }).join("");
  lucide.createIcons();
}
$("again").onclick = () => { clearSession(); location.reload(); };

/* ================= 시작 ================= */
$("nick").value = randNick();
sock.emit("meta", {}, (meta) => { S.meta = meta; buildPickers(meta); });
show("v-entry");
