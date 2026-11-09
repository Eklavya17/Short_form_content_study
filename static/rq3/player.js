// RQ3 player (Part 2): a full-screen, TikTok-style scroller.
//
// Behaviour (RQ3 Build Plan, Step 5):
//   - full-height 9:16 video, caption and buttons overlaid bottom right
//   - swipe up on phones; scroll wheel, trackpad or down arrow on laptops
//   - loops until the viewer swipes; tap to pause and resume
//   - heart button and double-tap to like; thin progress bar, no seeking
//   - preloads both candidates the server sends, so swipe -> first frame < 300 ms
//
// The player never decides what to show. It reports each swipe to
// POST /rq3/api/swipe and plays whatever comes back.

"use strict";

// Must match rq3/storage.py EVENT_TYPES.
const EVENT_TYPES = Object.freeze([
  "first_frame",
  "swipe",
  "loop",
  "like",
  "unlike",
  "pause",
  "resume",
  "stall",
  "stall_end",
  "hidden",
  "visible",
  "error",
]);

/** Fetch the current video and a preload candidate, then start playback. */
async function startBlock() {
  throw new Error("Part 2, step 9: player");
}

/** Send one player event for the current impression. */
async function logEvent(type, details = {}) {
  throw new Error("Part 2, step 2: event logging");
}

/** Report the swipe, receive the next video, and switch to it. */
async function handleSwipe() {
  throw new Error("Part 2, step 4: swipe route");
}

/** Attach swipe, wheel, arrow-key, tap and double-tap handlers. */
function bindGestures() {
  throw new Error("Part 2, step 9: player");
}

/** Load candidates into hidden <video> elements so the next swipe is instant. */
function preload(candidates) {
  throw new Error("Part 2, step 5: preloading");
}
