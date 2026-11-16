// RQ3 participant flow: consent, ID and topic interest, then three parts (one feed
// each, in an order the server chooses), with a survey after each part.
// The server decides every video; this page only plays them and reports
// what happened (outcomes on each swipe, player events in batches).
//
// A participant link carries the ID: /participant?pid=P001. Opening it resumes
// that participant, or starts them at the welcome screen with the ID filled in.
"use strict";

const $ = (selector) => document.querySelector(selector);
const SCREENS = ["welcome", "ready", "watching", "survey", "done"];
const LINK_PID = new URLSearchParams(location.search).get("pid");
// Set by the server when RQ3_SURVEY_URL points at an external (Qualtrics) questionnaire.
const QUESTIONNAIRE = document.body.dataset.questionnaire === "on";
const QUESTIONNAIRE_DELAY_S = 3;
let current = null; // last status from the server
let questionnaireTimer = null;

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
    const events = eventLog.takeAll(); // includes this swipe's own event
    let status;
    try {
      status = await postJSON("/participant/api/swipe", {
        clip_id: s.clip.id,
        watched_s: s.watchedS,
        swipe_s: s.swipeS,
        reached_end: s.reachedEnd,
        liked: s.liked,
        events,
      });
    } catch (error) {
      eventLog.putBack(events); // sent again with the next request, not lost
      if (error.message === SERVER_DOWN) {
        throw new Error("Connection problem. Please check your internet connection and press ↓ again.");
      }
      throw error;
    }
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

  if (status.stage === "welcome") {
    player.clear();
    const fromLink = Boolean(LINK_PID);
    $("#participant-id").value = fromLink ? LINK_PID : (status.participant_id ?? "");
    $("#participant-id").readOnly = fromLink;
    $("#consent").checked = false;
    $("#begin-button").disabled = true;
    showScreen("welcome");
  } else if (status.stage === "ready") {
    $("#ready-title").textContent = `Part ${done + 1} of ${total}`;
    showScreen("ready");
  } else if (status.stage === "watching") {
    showScreen("watching");
    if (player.clip?.id !== status.clip.id) player.load(status.clip);
  } else if (status.stage === "survey") {
    player.clear();
    $("#survey-title").textContent = `Part ${status.survey_part} of ${total} complete`;
    $("#survey-form").reset();
    $("#survey-status").textContent = "";
    $("#survey-submit").textContent = status.survey_part === total ? "Submit and finish" : "Submit and continue";
    showScreen("survey");
  } else if (status.stage === "done") {
    player.clear();
    if ($("#done-info")) $("#done-info").textContent = `Participant ${status.participant_id}: ${total} parts of ${status.videos_per_part} videos.`;
    const goToQuestionnaire = QUESTIONNAIRE && !status.questionnaire_done;
    $("#done-questionnaire").hidden = !goToQuestionnaire;
    $("#done-thanks").hidden = goToQuestionnaire;
    showScreen("done");
    if (goToQuestionnaire) startQuestionnaireCountdown();
  }
}

// Move on to the questionnaire by itself after a few seconds; the button works too.
function startQuestionnaireCountdown() {
  clearInterval(questionnaireTimer);
  let left = QUESTIONNAIRE_DELAY_S;
  const tick = () => {
    if (left <= 0) {
      clearInterval(questionnaireTimer);
      location.href = $("#questionnaire-link").href;
      return;
    }
    $("#questionnaire-countdown").textContent = `Opening in ${left} second${left === 1 ? "" : "s"}...`;
    left -= 1;
  };
  tick();
  questionnaireTimer = setInterval(tick, 1000);
}

function setWelcomeError(message) {
  const el = $("#welcome-status");
  el.textContent = message;
  el.classList.toggle("error", Boolean(message));
}

async function begin() {
  if (!$("#consent").checked) {
    setWelcomeError("Please read the study information and agree to participate before continuing.");
    return;
  }
  const ratings = {};
  document.querySelectorAll(".rating").forEach((set) => {
    ratings[set.dataset.topic] = Number(set.querySelector("input:checked").value);
  });
  try {
    const status = await postJSON("/participant/api/begin", {
      participant_id: $("#participant-id").value,
      ratings,
      videos_per_part: $("#videos-per-part") ? Number($("#videos-per-part").value) : null, // null = the study default
      consented: $("#consent").checked,
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

async function submitSurvey(event) {
  event.preventDefault();
  const answers = Object.fromEntries(
    Array.from(new FormData($("#survey-form")), ([name, value]) => [name, Number(value)])
  );
  $("#survey-submit").disabled = true;
  $("#survey-status").textContent = "";
  try {
    show(await postJSON("/participant/api/survey", { part: current.survey_part, answers }));
  } catch (error) {
    $("#survey-status").textContent = error.message;
  } finally {
    $("#survey-submit").disabled = false;
  }
}

$("#consent").addEventListener("change", () => {
  $("#begin-button").disabled = !$("#consent").checked;
});
$("#begin-button").addEventListener("click", begin);
$("#participant-id").addEventListener("keydown", (event) => { if (event.key === "Enter") begin(); });
$("#start-part-button").addEventListener("click", startNextPart);
$("#survey-form").addEventListener("submit", submitSurvey);
$("#new-button")?.addEventListener("click", newParticipant); // only with the testing panels

// Opening a participant link resumes that participant; otherwise resume whoever
// this browser was last (after a refresh, for example).
(LINK_PID
  ? postJSON("/participant/api/arrive", { participant_id: LINK_PID })
  : fetch("/participant/api/status").then((response) => response.json()))
  .then(show)
  .catch((error) => { showScreen("welcome"); setWelcomeError(error.message); });
