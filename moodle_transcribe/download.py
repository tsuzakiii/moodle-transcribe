"""HLS / direct-URL video download via ffmpeg."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import imageio_ffmpeg

from . import platform_io

Logger = Callable[[str], None]


def download_hls(url: str, dst_dir: Path, host: str, log: Logger) -> Path:
    """Download an HLS playlist to dst_dir/video.mp4 with stream-copy."""
    out = dst_dir / "video.mp4"
    if out.exists():
        log(f"  既存スキップ: {out.name}")
        return out
    headers = {
        "Origin": f"https://{host}",
        "Referer": f"https://{host}/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
    }
    hdr = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y",
        "-headers", hdr,
        "-i", url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        str(out),
    ]
    log("  ffmpeg DL中…")
    p = platform_io.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr[-500:]}")
    return out
