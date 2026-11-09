// Shared swipe player for the RQ3 demo and participant preview.
//
// Plays one clip at a time in a 9:16 frame and reports how the viewer left it:
// seconds actually watched (replays included, pauses excluded), the video time
// at the swipe, whether the end was reached, and whether they liked it.
//
//   swipe:  scroll down over the video column (one gesture = one swipe),
//           the down-arrow key, swiping up on a touchscreen, or the ↓ button
//   like:   the ♥ button, double-click, or L
//   pause:  click the video or Space
// Scrolling up does nothing: there is no going back.
//
// It also reports player events through `onEvent` (see rq3/storage.py
// EVENT_TYPES): first_frame, swipe, loop, like, unlike, pause, resume, stall,
// stall_end, hidden, visible, error.
"use strict";

const SERVER_DOWN = "Can't reach the server. Start it with `python -m rq3.demo`, then reload this page.";

async function postJSON(url, body) {
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
  return data;
}

// Collects player events and sends them in batches: every few seconds, inside each
// swipe request (`takeAll`), and with a final beacon when the page is hidden or
// closed, so leaving mid-video loses nothing.
function createEventLog(url, { flushEveryMs = 5000 } = {}) {
  let queue = [];

  function add(event) {
    queue.push(event);
  }

  function takeAll() {
    const events = queue;
    queue = [];
    return events;
  }

  async function flush() {
    if (!queue.length) return;
    const events = takeAll();
    try {
      await postJSON(url, { events });
    } catch {
      queue = events.concat(queue); // keep them for the next try
    }
  }

  function flushOnExit() {
    if (!queue.length) return;
    const blob = new Blob([JSON.stringify({ events: takeAll() })], { type: "application/json" });
    navigator.sendBeacon(url, blob);
  }

  setInterval(flush, flushEveryMs);
  // Deferred so the player's own "hidden" event is queued first.
  document.addEventListener("visibilitychange", () => { if (document.hidden) setTimeout(flushOnExit, 0); });
  window.addEventListener("pagehide", flushOnExit);
  return { add, takeAll, flush };
}

function createSwipePlayer({ phone, video, stage, likeButton, nextButton, caption, progressBar, status, onSwipe, onTick, onEvent }) {
  const WHEEL_THRESHOLD_PX = 60;
  const WHEEL_QUIET_MS = 300;

  let clip = null;
  let watchedS = 0;
  let lastTime = 0;
  let reachedEnd = false;
  let loops = 0;
  let liked = false;
  let busy = false;
  let loadStartedAt = 0;
  let firstFrameSeen = false;
  let stallStartedAt = null;

  function snapshot() {
    return { clip, watchedS, swipeS: video.currentTime, reachedEnd, liked, loops, time: video.currentTime };
  }

  function emit(eventType, details = {}) {
    if (!clip || !onEvent) return;
    onEvent({
      event_type: eventType,
      clip_id: clip.id,
      video_time: Number.isFinite(video.currentTime) ? Math.round(video.currentTime * 1000) / 1000 : null,
      client_wall_time: new Date().toISOString(),
      details,
    });
  }

  function showError(message) {
    status.textContent = message;
    status.classList.toggle("error", Boolean(message));
  }

  function setLoading(on) {
    phone.classList.toggle("loading", on);
    if (on) status.textContent = "Loading next video…";
  }

  function load(next, captionText) {
    clip = next;
    watchedS = 0;
    lastTime = 0;
    reachedEnd = false;
    loops = 0;
    liked = false;
    firstFrameSeen = false;
    stallStartedAt = null;
    loadStartedAt = performance.now();
    likeButton.classList.remove("liked");
    caption.textContent = captionText ?? next.title;
    progressBar.style.width = "0";
    video.src = next.url;
    video.play().catch(() => {
      status.textContent = "Click the video to start playback.";
    });
  }

  function clear() {
    clip = null;
    video.pause();
    video.removeAttribute("src");
    video.load();
    caption.textContent = "";
    progressBar.style.width = "0";
    setLoading(false);
  }

  async function swipe(source) {
    if (!clip || busy) return;
    busy = true;
    emit("swipe", { source, loops, watched_s: Math.round(watchedS * 1000) / 1000, liked });
    video.pause();
    setLoading(true);
    try {
      await onSwipe(snapshot());
      showError("");
    } catch (error) {
      setLoading(false);
      showError(error.message);
    } finally {
      busy = false;
    }
  }

  function toggleLike(source) {
    if (!clip) return;
    liked = !liked;
    likeButton.classList.toggle("liked", liked);
    emit(liked ? "like" : "unlike", { source });
    onTick?.(snapshot());
  }

  function togglePause() {
    if (!clip) return;
    if (video.paused) {
      video.play();
      emit("resume");
    } else {
      video.pause();
      emit("pause");
    }
  }

  // --- Playback events ---------------------------------------------------------------

  video.addEventListener("timeupdate", () => {
    const delta = video.currentTime - lastTime;
    if (!video.paused && delta > 0 && delta < 1.5) watchedS += delta;
    lastTime = video.currentTime;
    if (clip) {
      progressBar.style.width = `${(100 * video.currentTime) / clip.duration_s}%`;
      onTick?.(snapshot());
    }
  });

  video.addEventListener("ended", () => {
    // Loop like a short-video app, and remember that the end was reached.
    reachedEnd = true;
    loops += 1;
    emit("loop", { loops });
    lastTime = 0;
    video.currentTime = 0;
    video.play();
  });

  video.addEventListener("playing", () => {
    setLoading(false);
    if (!status.classList.contains("error")) status.textContent = "";
    if (!firstFrameSeen) {
      firstFrameSeen = true;
      emit("first_frame", { load_ms: Math.round(performance.now() - loadStartedAt) });
    }
    if (stallStartedAt !== null) {
      emit("stall_end", { stall_ms: Math.round(performance.now() - stallStartedAt) });
      stallStartedAt = null;
    }
  });

  video.addEventListener("waiting", () => {
    // Buffering after playback had started (not the initial load).
    if (firstFrameSeen && stallStartedAt === null && !busy) {
      stallStartedAt = performance.now();
      emit("stall");
    }
  });

  video.addEventListener("error", () => {
    emit("error", { code: video.error?.code ?? null, message: video.error?.message ?? "" });
  });

  document.addEventListener("visibilitychange", () => {
    emit(document.hidden ? "hidden" : "visible");
  });

  // --- Gestures ------------------------------------------------------------------------

  // One scroll gesture = one swipe. Mouse notches, trackpad flicks and smooth
  // scrolling all arrive as a stream of wheel events: add them up, swipe once the
  // total passes a threshold, then ignore the rest until the wheel goes quiet.
  let wheelTotal = 0;
  let wheelSpent = false;
  let wheelQuietTimer = null;
  stage.addEventListener("wheel", (event) => {
    event.preventDefault();
    const pixels = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaMode === 2 ? event.deltaY * 800 : event.deltaY;
    clearTimeout(wheelQuietTimer);
    wheelQuietTimer = setTimeout(() => { wheelTotal = 0; wheelSpent = false; }, WHEEL_QUIET_MS);
    if (wheelSpent) return;
    wheelTotal = Math.max(0, wheelTotal + pixels);
    if (wheelTotal >= WHEEL_THRESHOLD_PX) {
      wheelSpent = true;
      swipe("wheel");
    }
  }, { passive: false });

  let touchStartY = null;
  phone.addEventListener("touchstart", (event) => { touchStartY = event.touches[0].clientY; });
  phone.addEventListener("touchend", (event) => {
    if (touchStartY !== null && touchStartY - event.changedTouches[0].clientY > 60) swipe("touch");
    touchStartY = null;
  });

  let clickTimer = null;
  video.addEventListener("click", () => {
    // Wait briefly so a double-click (like) does not also pause.
    clearTimeout(clickTimer);
    clickTimer = setTimeout(togglePause, 250);
  });
  video.addEventListener("dblclick", () => {
    clearTimeout(clickTimer);
    if (!liked) toggleLike("double_click");
  });

  document.addEventListener("keydown", (event) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) return;
    if (event.key === "ArrowDown") { event.preventDefault(); swipe("key"); }
    if (event.key === "l" || event.key === "L") toggleLike("key");
    if (event.key === " ") { event.preventDefault(); togglePause(); }
  });

  likeButton.addEventListener("click", () => toggleLike("button"));
  nextButton.addEventListener("click", () => swipe("button"));

  return { load, clear, swipe, showError, snapshot, get clip() { return clip; } };
}
