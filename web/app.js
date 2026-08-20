const API = "/api";

// ---------- Navigation ----------
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`panel-${btn.dataset.panel}`).classList.add("active");
  });
});

// ---------- GW indicator ----------
// The dot reflects real state (see styles.css): gray while loading, green
// only once the fetch has actually succeeded -- not a decorative pulse.
fetch(`${API}/gw`)
  .then((r) => r.json())
  .then((d) => {
    const el = document.getElementById("gw-indicator");
    el.textContent = `GW${d.gw}`;
    el.classList.add("is-ready");
  })
  .catch(() => {
    document.getElementById("gw-indicator").textContent = "Offline";
  });

// ---------- Squad input widgets ----------
const template = document.getElementById("squad-input-template");

document.querySelectorAll(".squad-input").forEach((container) => {
  container.appendChild(template.content.cloneNode(true));

  const toggleBtns = container.querySelectorAll(".toggle-btn");
  const modeTeamId = container.querySelector(".squad-mode-team-id");
  const modePlayers = container.querySelector(".squad-mode-players");

  toggleBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      toggleBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const isTeamId = btn.dataset.mode === "team-id";
      modeTeamId.classList.toggle("hidden", !isTeamId);
      modePlayers.classList.toggle("hidden", isTeamId);
    });
  });
});

function readSquadInput(target) {
  const container = document.querySelector(`.squad-input[data-target="${target}"]`);
  const activeMode = container.querySelector(".toggle-btn.active").dataset.mode;

  if (activeMode === "team-id") {
    const teamId = container.querySelector(".input-team-id").value.trim();
    return teamId ? { team_id: parseInt(teamId, 10) } : {};
  }

  const raw = container.querySelector(".input-players").value.trim();
  const bank = container.querySelector(".input-bank").value.trim();
  if (!raw) return {};
  const players = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return { players, bank: bank ? parseFloat(bank) : 0 };
}

// ---------- Fetch helper ----------
async function callApi(path, body, method = "POST") {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${API}${path}`, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Something went wrong.");
  return data;
}

// Skeleton loaders shaped like the content that's about to arrive, instead
// of a generic spinner -- makes the wait feel considered, not just tolerated.
function renderSkeleton(el, cards = 1, lines = 4) {
  let html = "";
  for (let c = 0; c < cards; c++) {
    html += `<div class="skeleton-card" style="--i:${c}">
      <div class="skeleton-line title"></div>
      ${Array.from({ length: lines })
        .map(() => `<div class="skeleton-line"></div>`)
        .join("")}
    </div>`;
  }
  el.innerHTML = html;
}

function showError(resultsEl, err) {
  resultsEl.innerHTML = `<div class="error-msg">${err.message}</div>`;
}

function fmtXp(v) {
  return Number(v).toFixed(2);
}

function fmtMoney(tenths) {
  return `£${(tenths / 10).toFixed(1)}m`;
}

// Sequential --i counter so cascading elements (cards, then rows within
// them) stagger in one continuous rhythm down the page, not per-block.
function stagger() {
  let i = 0;
  return () => i++;
}

const PREFERS_REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Counts a headline number up from 0 rather than having it just appear --
// used sparingly, only on the single "hero number" per panel (the big-stat
// elements), not on every row, so it stays a moment of feedback rather than
// competing with the data itself for attention.
function countUp(el, target, decimals = 2, duration = 700) {
  if (PREFERS_REDUCED_MOTION) {
    el.textContent = target.toFixed(decimals);
    return;
  }
  const start = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3); // ease-out cubic
  function tick(now) {
    const progress = Math.min((now - start) / duration, 1);
    const value = target * ease(progress);
    el.textContent = value.toFixed(decimals);
    if (progress < 1) requestAnimationFrame(tick);
    else el.textContent = target.toFixed(decimals);
  }
  requestAnimationFrame(tick);
}

// Captain armband icon -- the one player this matters most for, marked with
// something more specific than a generic "(C)" text suffix.
// width/height are set directly on the <svg> (not just via CSS) so the icon
// can't balloon to the browser's default SVG size if styles.css is slow to
// load or briefly stale -- CSS still overrides these once it's applied.
function captainBadge() {
  return `<span class="captain-badge" title="Captain"><svg viewBox="0 0 24 24" width="11" height="11" fill="none"><path d="M4 6l8-3 8 3v6c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V6z" fill="currentColor"/></svg></span>`;
}

// ---------- Captain Pick ----------
document.getElementById("run-captain").addEventListener("click", async () => {
  const resultsEl = document.getElementById("results-captain");
  const btn = document.getElementById("run-captain");
  btn.disabled = true;
  renderSkeleton(resultsEl, 2, 5);
  try {
    const squad = readSquadInput("captain");
    const data = await callApi("/captain", squad);
    renderCaptain(resultsEl, data);
  } catch (err) {
    showError(resultsEl, err);
  } finally {
    btn.disabled = false;
  }
});

function renderCaptain(el, data) {
  const next = stagger();
  const captainCardIndex = next();

  const positions = Object.entries(data.by_position)
    .map(
      ([pos, players]) => `
      <div class="position-group" data-pos="${pos}">
        <div class="position-label" data-pos="${pos}">${pos}</div>
        ${players
          .map(
            (p) => `
          <div class="player-row" style="--i:${next()}">
            <div><span class="player-name">${p.name}</span><span class="player-meta">${p.team}</span></div>
            <span class="xp-value">${fmtXp(p.xp)} xP</span>
          </div>`
          )
          .join("")}
      </div>`
    )
    .join("");

  el.innerHTML = `
    <div class="card card-highlight" style="--i:${captainCardIndex}">
      <div class="card-title">Captain &middot; GW${data.gw}</div>
      <div class="player-row" style="--i:0"><div>${captainBadge()}<span class="player-name">${data.captain.name}</span><span class="player-meta">${data.captain.team}</span></div><span class="big-stat" id="captain-xp-value">0.00</span></div>
      <div class="player-row" style="--i:1"><div><span class="player-name">${data.vice.name}</span><span class="player-meta">Vice &middot; ${data.vice.team}</span></div><span class="xp-value">${fmtXp(data.vice.xp)}</span></div>
    </div>
    <div class="card" style="--i:1">
      <div class="card-title">Top Picks by Position</div>
      ${positions}
    </div>`;

  countUp(document.getElementById("captain-xp-value"), data.captain.xp);
}

// ---------- Team Planner ----------
// Fixed squad, no transfers: re-solves the best XI/captain for each
// gameweek as fixtures change, one step at a time (mirrors livefpl.net's
// planner). Transfer suggestions live in the separate Transfers/Horizon
// panels -- this view never changes who's in the 15.
let plannerOffset = 0;

document.getElementById("run-planner").addEventListener("click", () => {
  plannerOffset = 0;
  loadPlanner();
});
document.getElementById("planner-prev").addEventListener("click", () => {
  if (plannerOffset === 0) return;
  plannerOffset--;
  loadPlanner();
});
document.getElementById("planner-next").addEventListener("click", () => {
  plannerOffset++;
  loadPlanner();
});

async function loadPlanner() {
  const resultsEl = document.getElementById("results-planner");
  const stepper = document.getElementById("planner-stepper");
  const runBtn = document.getElementById("run-planner");
  const prevBtn = document.getElementById("planner-prev");
  const nextBtn = document.getElementById("planner-next");
  runBtn.disabled = true;
  prevBtn.disabled = true;
  nextBtn.disabled = true;
  renderSkeleton(resultsEl, 1, 8);
  try {
    const squad = readSquadInput("planner");
    const data = await callApi("/planner", { ...squad, week_offset: plannerOffset });
    stepper.classList.remove("hidden");
    document.getElementById("planner-gw-label").textContent = `GW${data.gw} · ${data.name}`;
    renderPlanner(resultsEl, data);
  } catch (err) {
    stepper.classList.add("hidden");
    showError(resultsEl, err);
  } finally {
    runBtn.disabled = false;
    prevBtn.disabled = plannerOffset === 0;
    nextBtn.disabled = false;
  }
}

function opponentTags(p) {
  if (!p.fixtures.length) return `<span class="pitch-chip-opp blank">Blank</span>`;
  return p.fixtures
    .map((f) => `<span class="pitch-chip-opp ${f.is_home ? "home" : "away"}">${f.opponent} ${f.is_home ? "(H)" : "(A)"}</span>`)
    .join("");
}

function pitchChip(p, data) {
  const isCaptain = p.id === data.captain.id;
  const isVice = p.id === data.vice.id;
  return `
    <div class="pitch-chip">
      <div class="pitch-chip-badge">${isCaptain ? captainBadge() : isVice ? `<span class="vice-badge" title="Vice-captain">V</span>` : ""}</div>
      <div class="pitch-chip-name">${p.web_name}</div>
      <div class="pitch-chip-opps">${opponentTags(p)}</div>
      <div class="pitch-chip-xp">${fmtXp(p.xp)}</div>
    </div>`;
}

function renderPlanner(el, data) {
  const byPos = { GKP: [], DEF: [], MID: [], FWD: [] };
  data.starters.forEach((p) => byPos[p.position].push(p));

  const rows = ["GKP", "DEF", "MID", "FWD"]
    .filter((pos) => byPos[pos].length)
    .map((pos) => `<div class="pitch-row">${byPos[pos].map((p) => pitchChip(p, data)).join("")}</div>`)
    .join("");

  const bench = data.bench.map((p) => pitchChip(p, data)).join("");

  el.innerHTML = `
    <div class="pitch">
      ${rows}
      <div class="pitch-row pitch-row-bench">${bench}</div>
    </div>
    <div class="card card-highlight" style="--i:0">
      <div class="player-row" style="--i:0"><div>Projected starting XI points</div><span class="big-stat" id="planner-total-value">0.00</span></div>
    </div>`;

  countUp(document.getElementById("planner-total-value"), data.total_points);
}

// ---------- Transfers ----------
document.getElementById("run-transfers").addEventListener("click", async () => {
  const resultsEl = document.getElementById("results-transfers");
  const btn = document.getElementById("run-transfers");
  btn.disabled = true;
  renderSkeleton(resultsEl, 2, 3);
  try {
    const squad = readSquadInput("transfers");
    const ft = document.getElementById("transfers-ft").value;
    const body = { ...squad, max_suggestions: 3 };
    if (ft) body.free_transfers = parseInt(ft, 10);
    const data = await callApi("/transfers", body);
    renderTransfers(resultsEl, data);
  } catch (err) {
    showError(resultsEl, err);
  } finally {
    btn.disabled = false;
  }
});

function renderTransfers(el, data) {
  if (!data.suggestions.length) {
    el.innerHTML = `<div class="card" style="--i:0">No transfer is worth making this week: your squad's projected points beat the available upgrades.</div>`;
    return;
  }
  const next = stagger();
  const rows = data.suggestions
    .map(
      (c) => `
    <div class="player-row" style="--i:${next()}">
      <div>
        <span class="player-name">${c.out.name}</span>
        <span class="transfer-arrow">&rarr;</span>
        <span class="player-name">${c.in.name}</span>
        ${c.hit ? `<span class="hit-tag">-${c.hit}</span>` : ""}
      </div>
      <span class="xp-value ${c.net_gain >= 0 ? "positive" : "negative"}">${c.net_gain >= 0 ? "+" : ""}${fmtXp(c.net_gain)}</span>
    </div>`
    )
    .join("");

  el.innerHTML = `
    <div class="card card-highlight" style="--i:0">
      <div class="card-title">GW${data.gw} &middot; ${fmtMoney(data.bank)} bank, ${data.free_transfers} FT</div>
      ${rows}
    </div>
    <div class="card" style="--i:1">
      <div class="player-row" style="--i:0"><div>Bank after transfers</div><span class="xp-value">${fmtMoney(data.remaining_bank)}</span></div>
    </div>`;
}

// ---------- Team Optimizer ----------
document.getElementById("run-optimizer").addEventListener("click", async () => {
  const resultsEl = document.getElementById("results-optimizer");
  const btn = document.getElementById("run-optimizer");
  btn.disabled = true;
  renderSkeleton(resultsEl, 2, 6);
  try {
    const budget = parseFloat(document.getElementById("optimizer-budget").value || "100");
    const data = await callApi("/optimize", { budget });
    renderOptimizer(resultsEl, data);
  } catch (err) {
    showError(resultsEl, err);
  } finally {
    btn.disabled = false;
  }
});

function renderOptimizer(el, data) {
  const byPos = {};
  data.starters.forEach((p) => {
    byPos[p.position] = byPos[p.position] || [];
    byPos[p.position].push(p);
  });

  const next = stagger();
  const posBlocks = Object.entries(byPos)
    .map(
      ([pos, players]) => `
    <div class="position-group" data-pos="${pos}">
      <div class="position-label" data-pos="${pos}">${pos}</div>
      ${players
        .map(
          (p) => `
        <div class="player-row" style="--i:${next()}">
          <div>${p.id === data.captain.id ? captainBadge() : ""}<span class="player-name">${p.name}</span><span class="player-meta">${p.team} &middot; ${fmtMoney(p.now_cost)}</span></div>
          <span class="xp-value">${fmtXp(p.xp)}</span>
        </div>`
        )
        .join("")}
    </div>`
    )
    .join("");

  const bench = data.bench
    .map(
      (p) => `
    <div class="player-row" style="--i:${next()}">
      <div><span class="player-name">${p.name}</span><span class="player-meta">${p.team} &middot; ${fmtMoney(p.now_cost)}</span></div>
      <span class="xp-value">${fmtXp(p.xp)}</span>
    </div>`
    )
    .join("");

  el.innerHTML = `
    <div class="card card-highlight" style="--i:0">
      <div class="card-title">GW${data.gw} &middot; ${fmtMoney(data.total_cost)} spent, ${data.starting_xp} pts projected</div>
      ${posBlocks}
    </div>
    <div class="card" style="--i:1">
      <div class="card-title">Bench</div>
      ${bench}
    </div>`;
}

// ---------- Price Tracker ----------
document.getElementById("run-prices").addEventListener("click", async () => {
  const resultsEl = document.getElementById("results-prices");
  const btn = document.getElementById("run-prices");
  btn.disabled = true;
  renderSkeleton(resultsEl, 2, 5);
  try {
    const data = await callApi("/prices", undefined, "GET");
    renderPrices(resultsEl, data);
  } catch (err) {
    showError(resultsEl, err);
  } finally {
    btn.disabled = false;
  }
});

function renderPrices(el, data) {
  if (data.message) {
    el.innerHTML = `<div class="card" style="--i:0">${data.message}</div>`;
    return;
  }
  const next = stagger();
  const rowsFor = (list, positive) =>
    list
      .map(
        (p) => `
    <div class="player-row" style="--i:${next()}">
      <div><span class="player-name">${p.name}</span><span class="player-meta">${p.team} &middot; ${p.ownership}% owned</span></div>
      <span class="xp-value ${positive ? "positive" : "negative"}">${p.net_transfers > 0 ? "+" : ""}${p.net_transfers.toLocaleString()}</span>
    </div>`
      )
      .join("");

  el.innerHTML = `
    <div class="card" style="--i:0">
      <div class="card-title">Likely Rises</div>
      ${rowsFor(data.risers, true)}
    </div>
    <div class="card" style="--i:1">
      <div class="card-title">Likely Falls</div>
      ${rowsFor(data.fallers, false)}
    </div>`;
}

// ---------- Horizon Planner ----------
document.getElementById("run-horizon").addEventListener("click", async () => {
  const resultsEl = document.getElementById("results-horizon");
  const btn = document.getElementById("run-horizon");
  btn.disabled = true;
  renderSkeleton(resultsEl, 3, 4);
  try {
    const squad = readSquadInput("horizon");
    const ft = document.getElementById("horizon-ft").value;
    const horizon = parseInt(document.getElementById("horizon-weeks").value || "3", 10);
    const body = { ...squad, horizon };
    if (ft) body.free_transfers = parseInt(ft, 10);
    const data = await callApi("/horizon", body);
    renderHorizon(resultsEl, data);
  } catch (err) {
    showError(resultsEl, err);
  } finally {
    btn.disabled = false;
  }
});

function renderHorizon(el, data) {
  const next = stagger();
  const weeks = data.weeks
    .map((w) => {
      const transfers = w.transfers_in.length
        ? w.transfers_out
            .map(
              (out, i) => `
        <div class="player-row" style="--i:${next()}">
          <div><span class="player-name">${out.name}</span><span class="transfer-arrow">&rarr;</span><span class="player-name">${w.transfers_in[i].name}</span></div>
        </div>`
            )
            .join("")
        : `<div class="player-row" style="--i:${next()}"><div>No transfers</div></div>`;

      return `
      <div class="week-block" style="--i:${next()}">
        <div class="week-block-header">
          GW${w.gw}
          <span class="week-meta">${w.free_transfers_available} FT &middot; ${fmtMoney(w.bank)}</span>
          ${w.hits ? `<span class="hit-tag">-${w.hits * 4} pts</span>` : ""}
        </div>
        ${transfers}
        <div class="player-row" style="--i:${next()}">
          <div>Captain: <span class="player-name">${w.captain.name}</span></div>
          <span class="xp-value">${fmtXp(w.points)}</span>
        </div>
      </div>`;
    })
    .join("");

  el.innerHTML = `
    <div class="exp-banner">Experimental: compounds an xP model that hasn't been validated against a live result yet.</div>
    ${weeks}
    <div class="card card-highlight" style="--i:${next()}">
      <div class="player-row" style="--i:0"><div>Total projected points (net of hits)</div><span class="big-stat" id="horizon-total-value">0.00</span></div>
    </div>`;

  countUp(document.getElementById("horizon-total-value"), data.total_points);
}

// ---------- Chat ----------
const chatWindow = document.getElementById("chat-window");
const chatInput = document.getElementById("chat-input");
const chatModeToggle = document.getElementById("chat-mode-toggle");

chatModeToggle.querySelectorAll(".toggle-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    chatModeToggle.querySelectorAll(".toggle-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
  });
});

function isConsensusMode() {
  return chatModeToggle.querySelector(".toggle-btn.active").dataset.mode === "consensus";
}

function appendChatMsg(text, role) {
  const examples = chatWindow.querySelector(".chat-examples");
  if (examples) examples.remove();
  const div = document.createElement("div");
  div.className = `chat-msg ${role} appear`;
  div.textContent = text;
  chatWindow.appendChild(div);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return div;
}

function appendTypingIndicator() {
  const examples = chatWindow.querySelector(".chat-examples");
  if (examples) examples.remove();
  const div = document.createElement("div");
  div.className = "chat-msg assistant appear";
  div.innerHTML = `<span class="typing-dots"><span></span><span></span><span></span></span>`;
  chatWindow.appendChild(div);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return div;
}

async function sendChat(message) {
  if (!message.trim()) return;
  const consensus = isConsensusMode();
  appendChatMsg(consensus ? `${message} (comparing sources)` : message, "user");
  chatInput.value = "";
  const placeholder = appendTypingIndicator();
  try {
    const data = await callApi("/chat", { message, consensus });
    placeholder.textContent = data.answer;
  } catch (err) {
    placeholder.textContent = `Error: ${err.message}`;
  }
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

document.getElementById("chat-send").addEventListener("click", () => sendChat(chatInput.value));
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat(chatInput.value);
});
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => sendChat(chip.textContent));
});
