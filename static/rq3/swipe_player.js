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

function createSwipePlayer({ phone, video, stage, likeButton, nextButton, caption, progressBar, status, onSwipe, onTick }) {
  const WHEEL_THRESHOLD_PX = 60;
  const WHEEL_QUIET_MS = 300;

  let clip = null;
  let watchedS = 0;
  let lastTime = 0;
  let reachedEnd = false;
  let loops = 0;
  let liked = false;
  let busy = false;

  function snapshot() {
    return { clip, watchedS, swipeS: video.currentTime, reachedEnd, liked, loops, time: video.currentTime };
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

  async function swipe() {
    if (!clip || busy) return;
    busy = true;
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

  function toggleLike() {
    if (!clip) return;
    liked = !liked;
    likeButton.classList.toggle("liked", liked);
    onTick?.(snapshot());
  }

  function togglePause() {
    if (!clip) return;
    if (video.paused) video.play();
    else video.pause();
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
    lastTime = 0;
    video.currentTime = 0;
    video.play();
  });

  video.addEventListener("playing", () => {
    setLoading(false);
    if (!status.classList.contains("error")) status.textContent = "";
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
      swipe();
    }
  }, { passive: false });

  let touchStartY = null;
  phone.addEventListener("touchstart", (event) => { touchStartY = event.touches[0].clientY; });
  phone.addEventListener("touchend", (event) => {
    if (touchStartY !== null && touchStartY - event.changedTouches[0].clientY > 60) swipe();
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
    if (!liked) toggleLike();
  });

  document.addEventListener("keydown", (event) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) return;
    if (event.key === "ArrowDown") { event.preventDefault(); swipe(); }
    if (event.key === "l" || event.key === "L") toggleLike();
    if (event.key === " ") { event.preventDefault(); togglePause(); }
  });

  likeButton.addEventListener("click", toggleLike);
  nextButton.addEventListener("click", swipe);

  return { load, clear, swipe, showError, snapshot, get clip() { return clip; } };
}
