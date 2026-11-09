// RQ3 feed demo: a basic swipe player plus a debug panel showing how the real
// engine scores each swipe and picks the next video. Testing only.
"use strict";

const $ = (selector) => document.querySelector(selector);
const player = $("#player");
const status = $("#status");

// Playback of the current clip.
let clip = null;
let watchedS = 0; // seconds actually played, replays included, pauses excluded
let lastTime = 0;
let reachedEnd = false;
let loops = 0;
let liked = false;
let busy = false;

// --- Server calls -------------------------------------------------------------------

const SERVER_DOWN = "Can't reach the demo server. Start it with `python -m rq3.demo`, then reload this page.";

async function api(url, body) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    throw new Error(SERVER_DOWN);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed: ${response.status}`);
  showError("");
  return data;
}

function showError(message) {
  status.textContent = message;
  status.classList.toggle("error", Boolean(message));
}

function setLoading(on) {
  $("#phone").classList.toggle("loading", on);
  if (on) status.textContent = "Loading next video…";
}

function chosenFeed() {
  return document.querySelector("input[name=feed]:checked").value;
}

function ratings() {
  const values = {};
  document.querySelectorAll("input[data-topic]").forEach((input) => {
    values[input.dataset.topic] = Number(input.value);
  });
  return values;
}

async function startBlock() {
  try {
    const data = await api("/api/start", { feed: chosenFeed(), ratings: ratings() });
    $("#start-overlay").hidden = true;
    render(data);
  } catch (error) {
    showError(error.message);
  }
}

async function swipe() {
  if (!clip || busy) return;
  busy = true;
  player.pause();
  setLoading(true);
  try {
    const data = await api("/api/swipe", {
      watched_s: watchedS,
      swipe_s: player.currentTime,
      reached_end: reachedEnd,
      liked,
    });
    render(data);
  } catch (error) {
    setLoading(false);
    showError(error.message);
  } finally {
    busy = false;
  }
}

async function resetSession() {
  let data;
  try {
    data = await api("/api/reset");
  } catch (error) {
    showError(error.message);
    return;
  }
  clip = null;
  player.removeAttribute("src");
  player.load();
  $("#start-overlay").hidden = false;
  for (const id of ["#now-playing", "#scored", "#decision", "#summary"]) $(id).textContent = "";
  $("#timeline").innerHTML = "";
  $("#live-rule").textContent = "";
  $("#topic-scores").innerHTML = "";
  $("#history tbody").innerHTML = "";
  $("#pool-info").textContent = `All ${data.pool_size} clips available again.`;
}

// --- Playback -----------------------------------------------------------------------

function loadClip(next) {
  clip = next;
  watchedS = 0;
  lastTime = 0;
  reachedEnd = false;
  loops = 0;
  liked = false;
  $("#like-button").classList.remove("liked");
  $("#caption").textContent = `${next.topic} · ${next.title}`;
  player.src = next.url;
  player.play().catch(() => {
    status.textContent = "Click the video to start playback.";
  });
  drawTimeline();
}

player.addEventListener("timeupdate", () => {
  const delta = player.currentTime - lastTime;
  if (!player.paused && delta > 0 && delta < 1.5) watchedS += delta;
  lastTime = player.currentTime;
  if (clip) {
    $("#progress-bar").style.width = `${(100 * player.currentTime) / clip.duration_s}%`;
    updateLive();
  }
});

player.addEventListener("ended", () => {
  // Loop like a short-video app, and remember that the end was reached.
  reachedEnd = true;
  loops += 1;
  lastTime = 0;
  player.currentTime = 0;
  player.play();
});

player.addEventListener("playing", () => {
  setLoading(false);
  if (!status.classList.contains("error")) status.textContent = "";
});

function toggleLike() {
  if (!clip) return;
  liked = !liked;
  $("#like-button").classList.toggle("liked", liked);
  updateLive();
}

function togglePause() {
  if (!clip) return;
  if (player.paused) player.play();
  else player.pause();
}

// --- Gestures -----------------------------------------------------------------------

// One scroll gesture = one swipe. A mouse notch, a trackpad flick and smooth
// scrolling all arrive as a stream of wheel events, so add them up, swipe once
// the total passes a threshold, then ignore the rest of the gesture until the
// wheel has been quiet for a moment. Scrolling up does nothing (no going back).
const WHEEL_THRESHOLD_PX = 60;
const WHEEL_QUIET_MS = 300;
let wheelTotal = 0;
let wheelSpent = false;
let wheelQuietTimer = null;

$(".stage").addEventListener("wheel", (event) => {
  event.preventDefault();
  const pixels = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaMode === 2 ? event.deltaY * 800 : event.deltaY;
  clearTimeout(wheelQuietTimer);
  wheelQuietTimer = setTimeout(() => { wheelTotal = 0; wheelSpent = false; }, WHEEL_QUIET_MS);
  if (wheelSpent) return;
  wheelTotal = Math.max(0, wheelTotal + pixels);
  if (wheelTotal >= WHEEL_THRESHOLD_PX) {
    wheelSpent = true;
    swipe();
  }
}, { passive: false });

let touchStartY = null;
$("#phone").addEventListener("touchstart", (event) => { touchStartY = event.touches[0].clientY; });
$("#phone").addEventListener("touchend", (event) => {
  if (touchStartY !== null && touchStartY - event.changedTouches[0].clientY > 60) swipe();
  touchStartY = null;
});

let clickTimer = null;
player.addEventListener("click", () => {
  // Wait briefly so a double-click (like) does not also pause.
  clearTimeout(clickTimer);
  clickTimer = setTimeout(togglePause, 250);
});
player.addEventListener("dblclick", () => {
  clearTimeout(clickTimer);
  if (!liked) toggleLike();
});

document.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT") return;
  if (event.key === "ArrowDown") { event.preventDefault(); swipe(); }
  if (event.key === "l" || event.key === "L") toggleLike();
  if (event.key === " ") { event.preventDefault(); togglePause(); }
});

$("#like-button").addEventListener("click", toggleLike);
$("#next-button").addEventListener("click", swipe);
$("#start-button").addEventListener("click", startBlock);
$("#reset-button").addEventListener("click", resetSession);
$("#toggle-panel").addEventListener("click", (event) => {
  const hidden = document.querySelector(".layout").classList.toggle("panel-hidden");
  event.target.textContent = hidden ? "Show panel" : "Hide panel";
});
document.querySelectorAll("input[data-topic]").forEach((input) => {
  input.addEventListener("input", () => { input.nextElementSibling.textContent = input.value; });
});

// --- Panel ---------------------------------------------------------------------------

const fmt = (value, digits = 2) => (value === null || value === undefined ? "—" : Number(value).toFixed(digits));
const signed = (value) => (value === null || value === undefined ? "—" : `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}`);
const tone = (value) => (value > 0 ? "pos" : value < 0 ? "neg" : "");
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}${s % 1 ? (s % 1).toFixed(1).slice(1) : ""}`;
const RULE_NAMES = {
  reached_end: "#1 watched to the end",
  hook: "#2 hook",
  after_payoff: "#3 after the payoff",
  after_micro_payoff: "#4 just after a micro-payoff",
  buildup: "#5 buildup",
  setup: "#5 setup",
  development: "#5 development",
  mid_loop: "#6 mid-loop",
  unannotated: "#8 unannotated",
};

function facts(rows) {
  return `<dl class="facts">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

function render(data) {
  loadClip(data.clip);
  renderNowPlaying();
  renderScored(data.scored);
  renderDecision(data.decision);
  renderTopicScores(data.topic_scores, data.decision.topic);
  renderHistory(data.history, data.summary);
  $("#pool-info").textContent = `${data.seen_total} of ${data.pool_size} clips shown so far (no repeats until Reset).`;
}

function renderNowPlaying() {
  const review = clip.review.length ? `<br><span class="muted">Catalog note: ${clip.review.join("; ")}</span>` : "";
  $("#now-playing").innerHTML = `<b>${clip.title}</b><br>${clip.topic} · ${clip.structure} · ${mmss(clip.duration_s)}${review}`;
  $("#now-playing").classList.remove("muted");
}

function drawTimeline() {
  const pct = (s) => `${(100 * s) / clip.duration_s}%`;
  const stages = clip.stages.map((s) =>
    `<div class="stage-band band-${s.label}" style="left:${pct(s.start_s)};width:${pct(s.end_s - s.start_s)}" title="${s.label} ${mmss(s.start_s)}–${mmss(s.end_s)}">${s.label}</div>`);
  const loopBands = clip.loops.map((lp) =>
    `<div class="loop-band" style="left:${pct(lp.start_s)};width:${pct(lp.end_s - lp.start_s)}" title="loop ${lp.index}: micro-payoff at ${mmss(lp.end_s)}"></div>`);
  $("#timeline").innerHTML = stages.join("") + loopBands.join("") + `<div class="marker" id="marker"></div>`;
}

function updateLive() {
  const t = player.currentTime;
  const marker = $("#marker");
  if (marker) marker.style.left = `${(100 * t) / clip.duration_s}%`;
  let rule;
  if (reachedEnd) rule = { rule: "reached_end", g: 0.2 };
  else rule = clip.rule_timeline.find((seg) => t >= seg.start_s && t < seg.end_s) || clip.rule_timeline.at(-1);
  const extras = [`at ${mmss(t)}`, loops ? `looped ${loops}×` : "", liked ? "liked" : ""].filter(Boolean).join(" · ");
  $("#live-rule").innerHTML = `If you swipe now: <span class="${tone(rule.g)}">${RULE_NAMES[rule.rule]} → g = ${signed(rule.g)}</span> <span class="muted">(${extras})</span>`;
}

function renderScored(scored) {
  const el = $("#scored");
  if (!scored) {
    el.textContent = "First video of the block: nothing scored yet.";
    el.classList.add("muted");
    return;
  }
  el.classList.remove("muted");
  el.innerHTML = facts([
    ["Video", scored.clip_title],
    ["Swiped at", `${mmss(scored.swipe_s)} of ${mmss(scored.duration_s)}${scored.reached_end ? " (during a replay)" : ""}`],
    ["Rule matched", `${RULE_NAMES[scored.rule]} → g = <span class="${tone(scored.g)}">${signed(scored.g)}</span>`],
    ["w (fraction watched)", `${fmt(scored.w)} <span class="muted">(${fmt(scored.watched_s, 1)} s played, capped at 1)</span>`],
    ["w̄ (your average)", `${fmt(scored.w_bar)}${scored.warmup ? ' <span class="muted">(warm-up default for the first 3 videos)</span>' : ""}`],
    ["e = (w − w̄) + g", `<b class="${tone(scored.e)}">${signed(scored.e)}</b>`],
    ["Liked", scored.liked ? "yes" : "no"],
  ]);
}

function renderDecision(d) {
  const el = $("#decision");
  el.classList.remove("muted");
  const kind = { first: "FIRST VIDEO", stay: "STAY", switch: "SWITCH", forced_switch: "FORCED SWITCH" }[d.kind];
  const rows = [["Result", `<span class="verdict">${kind}</span> → ${d.topic}`]];

  if (d.feed === "A") {
    const counters = Object.entries(d.cooldowns).map(([t, n]) => `${t} ${n}`).join(", ");
    rows.push(["Cooldown counters", counters]);
    rows.push(["Picked at random from", d.candidates.join(", ")]);
  } else if (d.kind === "first") {
    rows.push(["p at the start of a run", fmt(d.p_now)]);
  } else {
    rows.push(["p before → after this video", `${fmt(d.p_before)} → <b>${fmt(d.p_used)}</b>`]);
    rows.push(["Random draw", fmt(d.draw)]);
    if (d.kind === "forced_switch") {
      rows.push(["Why forced", d.forced_reason === "run_cap" ? `run reached ${window.RQ3.runCap} videos` : "no unseen clips left in that topic"]);
    } else {
      rows.push(["Comparison", d.kind === "stay" ? `draw ${fmt(d.draw)} < p ${fmt(d.p_used)} → stay` : `draw ${fmt(d.draw)} ≥ p ${fmt(d.p_used)} → switch`]);
    }
    if (d.kind !== "stay") rows.push(["p reset to", fmt(d.p_now)]);
  }
  rows.push(["Run position", `${d.run_position}${d.run_position === 1 ? " (new run)" : ` in a row on ${d.topic}`}`]);
  rows.push(["Unseen clips left in this topic", d.unseen_in_topic]);

  let odds = "";
  if (d.topic_odds) {
    const chips = Object.entries(d.topic_odds)
      .sort((a, b) => b[1] - a[1])
      .map(([t, p]) => `<span class="${t === d.topic ? "picked" : ""}">${t} ${(100 * p).toFixed(0)}%</span>`);
    odds = `<div class="muted" style="margin-top:8px">Topic odds for this pick:</div><div class="odds">${chips.join("")}</div>`;
  }
  el.innerHTML = facts(rows) + odds;
}

function renderTopicScores(scores, current) {
  const limit = 1.5;
  $("#topic-scores").innerHTML = Object.entries(scores).map(([topic, value]) => {
    const clamped = Math.max(-limit, Math.min(limit, value));
    const width = (50 * Math.abs(clamped)) / limit;
    const left = clamped >= 0 ? 50 : 50 - width;
    const color = clamped >= 0 ? "var(--good)" : "var(--bad)";
    return `<div class="bar-row"><span>${topic === current ? "<b>" + topic + "</b>" : topic}</span>
      <div class="bar-track"><div class="zero"></div><div class="bar-fill" style="left:${left}%;width:${width}%;background:${color}"></div></div>
      <span>${signed(value)}</span></div>`;
  }).join("");
}

function renderHistory(history, summary) {
  $("#summary").textContent =
    `${summary.videos} videos · average run ${summary.average_run} · runs of 3+: ${summary.runs_three_plus} · forced switches: ${summary.forced_switches}`;
  $("#history tbody").innerHTML = history.map((row, i) => {
    const prev = row.scored_previous;
    return `<tr class="${row.kind}"><td>${i + 1}</td><td>${row.topic}</td><td>${row.kind.replace("_", " ")}</td>
      <td>${row.run_position}</td><td>${fmt(row.p_used)}</td><td>${fmt(row.draw)}</td>
      <td>${prev ? RULE_NAMES[prev.rule] : "—"}</td><td>${prev ? signed(prev.e) : "—"}</td></tr>`;
  }).reverse().join("");
}
