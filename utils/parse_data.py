import argparse
from collections import Counter
from urllib.parse import quote
from pathlib import Path
from random import Random
from unicodedata import normalize
import pandas as pd

COLUMN_NAMES = {
    "URL": "url",
    "Title": "title",
    "Payoff Balance Class": "payoff_class",
    "Standardized Topic Category": "topic",
    "Narrative Structure": "narrative_structure",
    "Annotation": "annotation",
    "Pause Times": "pause_times",
}

# treat loops_only and hybrid_loops_to_terminal as the same "L" label
CLASS_LABELS = {"loops_only": "L", "hybrid_loops_to_terminal": "L", "terminal_primary": "T"}
CLIPS_PER_LABEL = {"L": 6, "T": 6}
TARGET_TRANSITIONS = [("L", "L"), ("T", "L"), ("L", "T"), ("T", "T")]
CLOUDFLARE_BASE_URL = "https://pub-ac0b745d1d8e43f28f455b068d4b59a0.r2.dev"
CLOUDFLARE_COLUMN = "Cloudflare URL"

def title_key(title):
    """Normalize punctuation width and spacing for matching only."""
    return " ".join(normalize("NFKC", title).casefold().split())

def save_cloudflare_csv(raw_catalog, videos_dir, output_path):
    """Export the source rows with a URL for each matching local MP4 filename."""
    title_columns = [column for column in raw_catalog if column.strip() == "Title"]
    if len(title_columns) != 1:
        raise ValueError("The CSV must have exactly one Title column.")
    if CLOUDFLARE_COLUMN in raw_catalog:
        raise ValueError(f"The input already has a {CLOUDFLARE_COLUMN!r} column.")

    videos = [
        (title_key(path.stem), path.name)
        for path in sorted(videos_dir.iterdir())
        if path.is_file() and path.suffix.lower() == ".mp4"
    ]
    if not videos:
        raise ValueError(f"No MP4 files found in {videos_dir}.")

    urls = []
    problems = []
    for title in raw_catalog[title_columns[0]]:
        key = title_key(title)
        matches = [name for stem, name in videos if stem == key]
        if key and not matches:
            # Some uploaded filenames append hashtags or a short description.
            matches = [
                name for stem, name in videos
                if stem.startswith(key) and stem[len(key):].lstrip().startswith(("#", ","))
            ]
        if len(matches) != 1:
            problem = ", ".join(matches) if matches else "no matching MP4"
            problems.append(f"{title!r}: {problem}")
            continue
        urls.append(f"{CLOUDFLARE_BASE_URL}/{quote(matches[0], safe='')}")

    if problems:
        raise ValueError("Could not match every title to one MP4:\n  " + "\n  ".join(problems))

    raw_catalog.assign(**{CLOUDFLARE_COLUMN: urls}).to_csv(
        output_path, index=False, encoding="utf-8-sig"
    )


def load_catalog(raw_catalog):
    df = raw_catalog.rename(columns=lambda c: c.strip()).rename(columns=COLUMN_NAMES)
    # Load and clean headers
    # df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig").fillna("")
    # df = df.rename(columns=lambda c: c.strip()).rename(columns=COLUMN_NAMES)

    required = ["url", "title", "payoff_class"]
    if missing := [c for c in required if c not in df.columns]:
        raise ValueError(f"Missing required columns: {missing}")

    # Strip whitespace, drop completely empty rows, and ensure required fields are present
    df = df.apply(lambda col: col.str.strip()).replace("", pd.NA).dropna(how="all").fillna("")
    if (df[required] == "").any(axis=None):
        raise ValueError("Every catalog row must have a URL, title, and payoff class.")

    # Normalize payoff classes and map to labels
    df["payoff_class"] = df["payoff_class"].str.lower().str.replace(r"[\s-]+", "_", regex=True)
    df["label"] = df["payoff_class"].map(CLASS_LABELS)
    
    unknown = df.loc[df["label"].isna(), "payoff_class"].unique()
    if unknown.size:
        raise ValueError(f"Unknown payoff classes: {unknown}")

    # Deduplicate
    df = df.drop_duplicates(subset=["url"])
        
    return df.reset_index(drop=True)


def assign_order(assigned_counts, goals, rng, candidate_count=50):
    """Choose a shuffled L/T order and update the assigned pair totals."""
    labels = [label for label, count in CLIPS_PER_LABEL.items() for _ in range(count)]
    best_candidates, best_score = [], -1

    for _ in range(candidate_count):
        rng.shuffle(labels)
        pairs = Counter(zip(labels, labels[1:]))
        
        # Score based on how many needed transitions this shuffle provides
        score = sum(min(pairs[p], max(0, goals[p] - assigned_counts.get(p, 0))) for p in goals)
        
        if score > best_score:
            best_score = score
            best_candidates = [(labels[:], pairs)]
        elif score == best_score:
            best_candidates.append((labels[:], pairs))

    # Pick randomly among the tied best scores
    order, pairs = rng.choice(best_candidates)
    assigned_counts.update(pairs)
    return order


def select_clips(order, pools, rng):
    """Draw clips uniformly without replacement within each label pool."""
    selected = {
        label: iter(rng.sample(pools[label], count))
        for label, count in Counter(order).items()
    }
    return [next(selected[label]) for label in order]


def main():
    parser = argparse.ArgumentParser(description="Assign sequence of video clips to participants.")
    parser.add_argument("csv_path", nargs="?", type=Path, default=Path("video_catalog_with_query_ranges (1).csv"))
    parser.add_argument("videos_dir", type=Path, default=Path("short_videos"), help="Directory containing local MP4 videos")
    parser.add_argument("output_path", type=Path, help="Path to save the updated CSV with Cloudflare URLs")
    parser.add_argument("--goal", type=int, default=15, help="Desired count per target pair")
    parser.add_argument("--candidates", type=int, default=50000, help="Shuffles per assignment")
    args = parser.parse_args()

    if args.csv_path.resolve() == args.output_path.resolve():
        parser.error("Choose a different path for the output CSV.")

    if args.candidates < 1 or args.goal < 0:
        parser.error("Candidates must be positive; goal must be nonnegative.")

    try:
        # catalog = load_catalog(args.csv_path)
        raw_catalog = pd.read_csv(
            args.csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig"
        )
        catalog = load_catalog(raw_catalog)
        pools = {label: rows.to_dict("records") for label, rows in catalog.groupby("label")}
        
        for label, required in CLIPS_PER_LABEL.items():
            if len(pools.get(label, [])) < required:
                raise ValueError(f"Need {required} {label} clips, but catalog has {len(pools.get(label, []))}.")

        save_cloudflare_csv(raw_catalog, args.videos_dir, args.output_path)
                
    except (OSError, ValueError) as error:
        parser.error(str(error))

    # Initialize rng without a seed so it produces different results every run
    rng = Random()
    assigned_counts = Counter()
    goals = {pair: args.goal for pair in TARGET_TRANSITIONS}
    
    pool_summary = ", ".join(f"{lbl}={len(pools[lbl])}" for lbl in CLIPS_PER_LABEL)
    print(f"Loaded {len(catalog)} clips: {pool_summary}\n")

    # Generate sequence for a single participant
    order = assign_order(assigned_counts, goals, rng, args.candidates)
    print(f"Sequence: {' '.join(order)}")
    
    for i, clip in enumerate(select_clips(order, pools, rng), 1):
        print(f"  {i:>2}. {clip['label']}  {clip['title']} [{clip['topic']}]")

    print("\nAssigned transitions (row = previous, column = next)")
    print("      " + "".join(f"{lbl:>5}" for lbl in CLIPS_PER_LABEL))
    for prev_lbl in CLIPS_PER_LABEL:
        counts = "".join(f"{assigned_counts[prev_lbl, next_lbl]:>5}" for next_lbl in CLIPS_PER_LABEL)
        print(f"{prev_lbl:>4}  {counts}")

if __name__ == "__main__":
    main()
    