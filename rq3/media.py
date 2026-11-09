"""Read an MP4's duration and layout from its header, without downloading the video.

An MP4 is a sequence of boxes. `moov` holds the index, including the `mvhd` box
with the duration; `mdat` holds the video data. When `moov` comes before `mdat`
("faststart"), a browser can start playing before the whole file arrives, which
matters for the RQ3 target of under 300 ms from swipe to first frame.

Only box headers and the start of `moov` are fetched, using HTTP range requests.
"""

from __future__ import annotations

import struct
import urllib.request
from dataclasses import dataclass

USER_AGENT = "rq3-catalog-builder"
HEADER_BYTES = 16  # box size (4) + type (4) + optional 64-bit size (8)
MOOV_PREFIX_BYTES = 4096  # mvhd is the first box inside moov in practice
MAX_BOXES = 64  # stop walking a malformed file


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float
    faststart: bool


def probe_mp4(url: str, timeout_s: float = 20) -> MediaInfo:
    """Duration and faststart flag of the MP4 at `url`."""
    offset = 0
    mdat_seen = False
    for _ in range(MAX_BOXES):
        header = _read_range(url, offset, HEADER_BYTES, timeout_s)
        if len(header) < 8:
            break
        size, box_type = _parse_box_header(header)
        if box_type == b"moov":
            moov = _read_range(url, offset, min(size, MOOV_PREFIX_BYTES), timeout_s)
            return MediaInfo(duration_s=parse_mvhd(moov), faststart=not mdat_seen)
        if box_type == b"mdat":
            mdat_seen = True
        if size == 0:  # box runs to the end of the file
            break
        offset += size
    raise ValueError(f"No moov box found in {url}")


def parse_mvhd(data: bytes) -> float:
    """Duration in seconds from bytes that contain an `mvhd` box."""
    start = data.find(b"mvhd")
    if start < 4:
        raise ValueError("mvhd box not found")
    body = start + 4  # first byte after the box type
    version = data[body]
    if version == 0:
        timescale, duration = struct.unpack(">II", data[body + 12 : body + 20])
    else:
        timescale, duration = struct.unpack(">IQ", data[body + 20 : body + 32])
    if timescale == 0:
        raise ValueError("mvhd timescale is 0")
    return round(duration / timescale, 3)


def _parse_box_header(header: bytes) -> tuple[int, bytes]:
    size, box_type = struct.unpack(">I4s", header[:8])
    if size == 1:  # 64-bit size follows the type
        (size,) = struct.unpack(">Q", header[8:16])
    return size, box_type


def _read_range(url: str, start: int, length: int, timeout_s: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Range": f"bytes={start}-{start + length - 1}", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        if start > 0 and response.status != 206:
            raise ValueError(f"Server ignored the byte range for {url}")
        return response.read(length)  # never more, even if the server ignores Range
