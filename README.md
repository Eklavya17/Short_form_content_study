# RQ1 Short-Video Study

This pilot measures when viewers continue or skip short videos, both at annotated pause points and during uninterrupted playback.

## Open the hosted pilot

[Open the video study](https://short-video-user-study.onrender.com/) in a fresh incognito or private window, then click **Start study**. The browser cookie identifies the session, so refreshing the page keeps the same assignment. To start another run, close all private windows before opening a new one.

## Run locally

Clone the pilot branch if you need a checkout.

```bash
git clone --branch new-changes --single-branch https://github.com/adas2125/short-video-user-study.git
cd short-video-user-study
```

From the repository root, use these settings for the shared dummy pilot.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

export DATABASE_URL='postgresql://rq1_study_user:6BnAq7xSwG8PZSZDTeRsqSfK59NIg1L5@dpg-dbf8msg473hc73c8jbo0-a.ohio-postgres.render.com/rq1_study'
export ADMIN_PASSWORD='password'

flask --app app init-db
flask --app app run --debug
```

| Page | What to do |
| --- | --- |
| [Participant view](http://127.0.0.1:5000/) | Open in a private window for a fresh run. |
| [Admin summary](http://127.0.0.1:5000/admin/summary) | Sign in as `admin` with password `password`. The page returns JSON. |

### Reset pilot data

**This clears all sessions, trials, responses, and events in the database selected by `DATABASE_URL`.** If the hosted pilot uses that database, its records are cleared too. Run this from a terminal with the virtual environment active and `DATABASE_URL` set.

```bash
python - <<'PY'
import os

import psycopg

with psycopg.connect(os.environ["DATABASE_URL"]) as db:
    db.execute(
        "TRUNCATE TABLE events, responses, trials, sessions RESTART IDENTITY CASCADE"
    )

print("Pilot data cleared.")
PY
```

After a reset, open a fresh private session so the browser drops its old session cookie.

## How each session is assigned

The catalog contains 44 clips across eight topics. The app samples 12 distinct clips per session, with six from each payoff group. Topic mix varies by session.

| Catalog label | Structure | Feed group |
| --- | --- | --- |
| `loops_only` | Repeated setups and payoffs, such as a funny-moments compilation | `L` |
| `hybrid_loops_to_terminal` | Smaller payoffs that build toward a final one, such as increasingly difficult tricks | `L` |
| `terminal_primary` | Development leading to one main payoff, such as a recipe reveal | `T` |

The sampler favors randomized orders that fill gaps in the four adjacent transitions (`L → L`, `L → T`, `T → L`, and `T → T`).

The app randomly assigns six clips to each interaction mode.

| Mode | Viewer experience |
| --- | --- |
| **Free swipe** | No probes. The viewer can click **Next video** during playback. |
| **Fixed probe** | Playback pauses at sampled timestamps. The viewer chooses **Continue watching** or **Move to next video**. Terminal clips get up to two probes, one in early development and one in late buildup or development. Loop-based clips get up to three probes sampled from annotated loop windows. |

## What we record and measure

The admin summary contains assigned video orders (`sessions`), probe choices (`responses`), and voluntary skip times (`voluntary_swipes`). The database also stores each trial's probe plan and playback events, including probe displays, video ends, and player errors. Use the session ID and trial ID to join the records.

- **Within a clip.** Among viewers who finish one payoff loop, what fraction finish the next loop or reach the final payoff? Among viewers who watch through the first third of development, what fraction reach the final payoff?
- **At a probe.** How often do viewers choose to continue at a given stage, such as early development, late buildup, or a payoff loop?
- **Across clips.** Does watch time or completion on the next clip vary by the assigned payoff transition?

## Files to edit

| File | Role |
| --- | --- |
| [`utils/data_with_cloudflare.csv`](utils/data_with_cloudflare.csv) | Catalog annotations, payoff labels, query windows, and hosted MP4 URLs. |
| [`stimuli_from_catalog.json`](stimuli_from_catalog.json) | Runtime catalog loaded by Flask. Regenerate it when the CSV changes. |
| [`utils/parse_data.py`](utils/parse_data.py) | Matches catalog rows to local MP4 filenames to build Cloudflare URLs and previews feed sampling. |
| [`feed.py`](feed.py) | Feed assignment, transition scoring, and probe timing. |
| [`app.py`](app.py) | Study routes, event logging, and admin summary. |

To rebuild the runtime catalog from the CSV, run this from the repository root.

```bash
(cd utils && python generate_stimulus.py && mv stimuli_from_catalog.json ..)
```
