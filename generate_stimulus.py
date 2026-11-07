import csv
import json
from pathlib import Path
from urllib.parse import urlsplit

csv_path = Path("data_with_cloudflare.csv")
output_path = Path("stimuli_from_catalog.json")

videos = []

with csv_path.open(encoding="utf-8-sig", newline="") as csv_file:
    for row in csv.DictReader(csv_file):
        video_id = urlsplit(row["URL"]).path.rstrip("/").split("/")[-1]
        query_ranges = json.loads(row["Query Ranges"])

        videos.append({
            "id": video_id,
            "title": row["Title"].strip(),
            "video_url": row["Cloudflare URL"],
            "payoff_label": row["Payoff Label"].strip(),
            "probe_candidates": [
                {
                    "start_s": candidate["start_s"],
                    "end_s": candidate["end_s"],
                    "category": candidate["kind"],
                }
                for candidate in query_ranges
            ],
        })

with output_path.open("w", encoding="utf-8") as output_file:
    json.dump({"videos": videos}, output_file, indent=2, ensure_ascii=False)
    output_file.write("\n")

print(f"Wrote {len(videos)} videos to {output_path}")
