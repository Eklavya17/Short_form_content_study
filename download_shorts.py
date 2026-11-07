import pandas as pd
import yt_dlp
from pathlib import Path

def download_shorts(link_list, output_dir):
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    ydl_opts = {
    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "outtmpl": str(Path(output_dir) / "%(title)s.%(ext)s"),
    "cookiesfrombrowser": ("chrome",),
    "quiet": False,
    "ignoreerrors": True,
}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for link in link_list:
            try:
                ydl.download([link])
            except yt_dlp.utils.DownloadError as e:
                print(f"yt-dlp failed on {link}: {e}")
            except Exception as e:
                print(f"An unexpected error occurred on {link}: {e}")

if __name__ == "__main__":
    videos = pd.read_csv("data.csv")
    urls = videos["URL"].tolist()
    download_shorts(urls, "short_videos")