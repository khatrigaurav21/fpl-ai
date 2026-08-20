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
fetch(`${API}/gw`)
  .then((r) => r.json())
  .then((d) => {
    document.getElementById("gw-indicator").textContent = `GW${d.gw}`;
  })
  .catch(() => {});

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
      <div class="position-group">
        <div class="position-label">${pos}</div>
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
      <div class="player-row" style="--i:0"><div><span class="player-name">${data.captain.name}</span><span class="player-meta">${data.captain.team}</span></div><span class="big-stat">${fmtXp(data.captain.xp)}</span></div>
      <div class="player-row" style="--i:1"><div><span class="player-name">${data.vice.name}</span><span class="player-meta">Vice &middot; ${data.vice.team}</span></div><span class="xp-value">${fmtXp(data.vice.xp)}</span></div>
    </div>
    <div class="card" style="--i:1">
      <div class="card-title">Top Picks by Position</div>
      ${positions}
    </div>`;
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
    el.innerHTML = `<div class="card" style="--i:0">No transfer is worth making this week &mdash; your squad's projected points beat the available upgrades.</div>`;
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
      <div class="card-title">GW${data.gw} &middot; Bank ${fmtMoney(data.bank)} &middot; ${data.free_transfers} FT</div>
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
    <div class="position-group">
      <div class="position-label">${pos}</div>
      ${players
        .map(
          (p) => `
        <div class="player-row" style="--i:${next()}">
          <div><span class="player-name">${p.name}${p.id === data.captain.id ? " (C)" : ""}</span><span class="player-meta">${p.team} &middot; ${fmtMoney(p.now_cost)}</span></div>
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
      <div class="card-title">GW${data.gw} &middot; ${fmtMoney(data.total_cost)} spent &middot; Projected ${data.starting_xp} pts</div>
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
    <div class="exp-banner">Experimental &mdash; compounds an xP model that hasn't been validated against a live result yet.</div>
    ${weeks}
    <div class="card card-highlight" style="--i:${next()}">
      <div class="player-row" style="--i:0"><div>Total projected points (net of hits)</div><span class="big-stat">${data.total_points}</span></div>
    </div>`;
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
