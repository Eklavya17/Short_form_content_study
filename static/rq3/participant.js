// RQ3 participant preview: ID and topic interest, then three parts (one feed each,
// in an order the server chooses), with a break screen where the Qualtrics survey
// will go. The server decides every video; this page only plays them and reports
// what happened (outcomes on each swipe, player events in batches).
//
// A participant link carries the ID: /participant?pid=P001. Opening it resumes
// that participant, or starts them at the welcome screen with the ID filled in.
"use strict";

const $ = (selector) => document.querySelector(selector);
const SCREENS = ["welcome", "ready", "watching", "break", "done"];
const LINK_PID = new URLSearchParams(location.search).get("pid");
let current = null; // last status from the server

const eventLog = createEventLog("/participant/api/events");

const player = createSwipePlayer({
  phone: $("#phone"),
  video: $("#player"),
  stage: $("#screen-watching"),
  likeButton: $("#like-button"),
  nextButton: $("#next-button"),
  caption: $("#caption"),
  progressBar: $("#progress-bar"),
  status: $("#status"),
  onEvent: eventLog.add,
  onSwipe: async (s) => {
    const status = await postJSON("/participant/api/swipe", {
      clip_id: s.clip.id,
      watched_s: s.watchedS,
      swipe_s: s.swipeS,
      reached_end: s.reachedEnd,
      liked: s.liked,
      events: eventLog.takeAll(), // includes this swipe's own event
    });
    show(status);
  },
});

function showScreen(name) {
  for (const screen of SCREENS) $(`#screen-${screen}`).hidden = screen !== name;
}

// Render whatever stage the server says this participant is at.
function show(status) {
  current = status;
  const total = status.parts_total ?? 3;
  const done = status.parts_done ?? 0;
  $("#part-label").textContent = status.stage === "watching" ? `Part ${done + 1} of ${total}` : "";

  if (status.stage === "welcome") {
    player.clear();
    const fromLink = Boolean(LINK_PID);
    $("#participant-id").value = fromLink ? LINK_PID : "";
    $("#participant-id").readOnly = fromLink;
    showScreen("welcome");
  } else if (status.stage === "ready") {
    $("#ready-title").textContent = `Part ${done + 1} of ${total}`;
    showScreen("ready");
  } else if (status.stage === "watching") {
    showScreen("watching");
    if (player.clip?.id !== status.clip.id) player.load(status.clip);
  } else if (status.stage === "break") {
    player.clear();
    $("#break-title").textContent = `Part ${done} of ${total} complete`;
    $("#survey-note").textContent = `The Qualtrics survey about part ${done} will open here.`;
    $("#continue-button").textContent = `Continue to part ${done + 1}`;
    showScreen("break");
  } else if (status.stage === "done") {
    player.clear();
    $("#done-info").textContent = `Participant ${status.participant_id}: ${total} parts of ${status.videos_per_part} videos.`;
    showScreen("done");
  }
}

function setWelcomeError(message) {
  const el = $("#welcome-status");
  el.textContent = message;
  el.classList.toggle("error", Boolean(message));
}

async function begin() {
  const ratings = {};
  document.querySelectorAll(".rating").forEach((set) => {
    ratings[set.dataset.topic] = Number(set.querySelector("input:checked").value);
  });
  try {
    const status = await postJSON("/participant/api/begin", {
      participant_id: $("#participant-id").value,
      ratings,
      videos_per_part: Number($("#videos-per-part").value),
    });
    setWelcomeError("");
    show(status);
  } catch (error) {
    setWelcomeError(error.message);
  }
}

async function startNextPart() {
  try {
    show(await postJSON("/participant/api/next-part"));
  } catch (error) {
    alert(error.message);
  }
}

async function newParticipant() {
  await postJSON("/participant/api/new");
  location.href = "/participant"; // drop any ?pid= from the address
}

$("#begin-button").addEventListener("click", begin);
$("#participant-id").addEventListener("keydown", (event) => { if (event.key === "Enter") begin(); });
$("#start-part-button").addEventListener("click", startNextPart);
$("#continue-button").addEventListener("click", () => {
  // Between parts the participant would fill in the survey; here we go straight on.
  showScreen("ready");
  $("#ready-title").textContent = `Part ${current.parts_done + 1} of ${current.parts_total}`;
});
$("#new-button").addEventListener("click", newParticipant);

// Opening a participant link resumes that participant; otherwise resume whoever
// this browser was last (after a refresh, for example).
(LINK_PID
  ? postJSON("/participant/api/arrive", { participant_id: LINK_PID })
  : fetch("/participant/api/status").then((response) => response.json()))
  .then(show)
  .catch((error) => { showScreen("welcome"); setWelcomeError(error.message); });
