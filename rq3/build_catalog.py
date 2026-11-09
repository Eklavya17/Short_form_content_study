"""Build data/rq3_catalog.json from the annotated catalog CSV.

Usage:
    python -m rq3.build_catalog [--csv utils/data_with_cloudflare.csv]

The CSV's Annotation column holds stage spans such as "HOOK (0:00-0:04)" and the
Query Ranges column holds loop windows as JSON. Clips whose stage times cannot be
parsed are listed at the end so they can be marked by hand.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rq3.catalog import CATALOG_PATH, Clip, Loop, Stage

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "utils" / "data_with_cloudflare.csv"


def parse_timestamp(text: str) -> float:
    """Turn "1:05" or "0:07" into seconds."""
    raise NotImplementedError("Part 1, step 1: catalog")


def parse_stages(annotation: str, duration_s: float) -> tuple[Stage, ...]:
    """Extract codebook stage spans from an annotation string."""
    raise NotImplementedError("Part 1, step 1: catalog")


def parse_loops(query_ranges: str) -> tuple[Loop, ...]:
    """Extract loop windows from the Query Ranges JSON column."""
    raise NotImplementedError("Part 1, step 1: catalog")


def read_clips(csv_path: Path) -> tuple[list[Clip], list[str]]:
    """Return the hosted clips plus the titles of clips that need hand-marking."""
    raise NotImplementedError("Part 1, step 1: catalog")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()

    from rq3.catalog import write_catalog

    clips, needs_marking = read_clips(args.csv)
    write_catalog(clips, args.out)
    print(f"Wrote {len(clips)} clips to {args.out}")
    for title in needs_marking:
        print(f"  needs stage times: {title}")


if __name__ == "__main__":
    main()
