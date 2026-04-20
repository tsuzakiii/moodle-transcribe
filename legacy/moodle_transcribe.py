"""
Moodle (HLS m3u8) 動画を再生せずダウンロード → faster-whisper 日本語文字起こし。

出力構成:
    C:\\ClaudeCode\\moodle_out\\<course>\\<lecture>\\
        video.mp4
        transcript.txt
        transcript.srt
        meta.json

使い方:
    py -3.14 moodle_transcribe.py <m3u8 URL> -c <講義名> -l <回名>
    py -3.14 moodle_transcribe.py --list                       # 全講義一覧
    py -3.14 moodle_transcribe.py --list -c <講義名>           # 講義内の回一覧

例:
    py -3.14 moodle_transcribe.py "https://dc.miovp.com/.../index.m3u8?..." \\
        -c "データサイエンスとビジネスリサーチ" -l "01_イントロダクション1"

オプション:
    --no-download   既存 video.mp4 から文字起こしのみ再実行
    --no-transcribe ダウンロードのみ
    --model NAME    whisperモデル (default: large-v3)
    --cpu           GPUを使わない
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import importlib.util
_extra_paths = []
for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
    try:
        spec = importlib.util.find_spec(pkg)
        if spec and spec.submodule_search_locations:
            bin_dir = os.path.join(spec.submodule_search_locations[0], "bin")
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
                _extra_paths.append(bin_dir)
    except Exception:
        pass
if _extra_paths:
    os.environ["PATH"] = os.pathsep.join(_extra_paths) + os.pathsep + os.environ.get("PATH", "")

ROOT = Path(r"C:\ClaudeCode\moodle_out")

HEADERS = {
    "Origin": "https://wsdmoodle.waseda.jp",
    "Referer": "https://wsdmoodle.waseda.jp/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/147.0.0.0 Safari/537.36",
}

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def safe(name: str) -> str:
    s = _INVALID.sub("_", name).strip().strip(".")
    return s or "untitled"

def lecture_dir(course: str, lecture: str) -> Path:
    return ROOT / safe(course) / safe(lecture)

def list_all(course: str | None):
    if not ROOT.exists():
        print("(まだ何も保存されていません)"); return
    if course:
        cdir = ROOT / safe(course)
        if not cdir.exists():
            print(f"講義 '{course}' は未登録"); return
        print(f"# {course}")
        for d in sorted(p for p in cdir.iterdir() if p.is_dir()):
            meta = d / "meta.json"
            tag = ""
            if meta.exists():
                m = json.loads(meta.read_text(encoding="utf-8"))
                tag = f"  ({m.get('downloaded_at', '')})"
            done = "✓" if (d / "transcript.txt").exists() else " "
            print(f"  [{done}] {d.name}{tag}")
        return
    for cdir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        n = sum(1 for d in cdir.iterdir() if d.is_dir())
        print(f"[{n:>2}回] {cdir.name}")

def download(url: str, dst: Path) -> Path:
    out = dst / "video.mp4"
    if out.exists():
        print(f"[skip] {out.name} 既存")
        return out
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    hdr = "".join(f"{k}: {v}\r\n" for k, v in HEADERS.items())
    cmd = [
        ffmpeg, "-y", "-headers", hdr, "-i", url,
        "-c", "copy", "-bsf:a", "aac_adtstoasc", str(out),
    ]
    print(f"[ffmpeg] downloading → {out}")
    subprocess.run(cmd, check=True)
    return out

def _ts(s: float) -> str:
    h = int(s // 3600); s -= h * 3600
    m = int(s // 60);   s -= m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

def transcribe(media: Path, dst: Path, model_name: str, use_gpu: bool):
    from faster_whisper import WhisperModel
    txt_path = dst / "transcript.txt"
    srt_path = dst / "transcript.srt"

    if use_gpu:
        try:
            model = WhisperModel(model_name, device="cuda", compute_type="float16")
            print(f"[whisper] {model_name} on GPU")
        except Exception as e:
            print(f"  GPU失敗 ({e}) → CPU int8")
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
    else:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print(f"[whisper] {model_name} on CPU")

    print("[whisper] transcribing…")
    segments, info = model.transcribe(
        str(media), language="ja", vad_filter=True, beam_size=5,
    )
    with txt_path.open("w", encoding="utf-8") as ft, srt_path.open("w", encoding="utf-8") as fs:
        for i, seg in enumerate(segments, 1):
            line = seg.text.strip()
            print(f"[{seg.start:6.1f}s] {line}")
            ft.write(line + "\n")
            fs.write(f"{i}\n{_ts(seg.start)} --> {_ts(seg.end)}\n{line}\n\n")
    print(f"\n書き出し: {txt_path}\n         {srt_path}")

def write_meta(dst: Path, url: str, course: str, lecture: str):
    meta = dst / "meta.json"
    data = {}
    if meta.exists():
        data = json.loads(meta.read_text(encoding="utf-8"))
    data.update({
        "course": course,
        "lecture": lecture,
        "url": url,
        "downloaded_at": data.get("downloaded_at") or datetime.now().isoformat(timespec="seconds"),
        "last_run_at": datetime.now().isoformat(timespec="seconds"),
    })
    meta.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__)
    p.add_argument("url", nargs="?", help="m3u8 URL")
    p.add_argument("-c", "--course", help="講義名 (例: データサイエンスとビジネスリサーチ)")
    p.add_argument("-l", "--lecture", help="回の名前 (例: 01_イントロダクション1)")
    p.add_argument("--list", action="store_true", help="保存済み一覧を表示")
    p.add_argument("--no-download", action="store_true")
    p.add_argument("--no-transcribe", action="store_true")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--cpu", action="store_true")
    args = p.parse_args()

    if args.list:
        list_all(args.course); return

    if not (args.url and args.course and args.lecture):
        p.error("url, --course, --lecture が必要です (--list は別)")

    dst = lecture_dir(args.course, args.lecture)
    dst.mkdir(parents=True, exist_ok=True)
    print(f"[出力先] {dst}")

    media = dst / "video.mp4"
    if not args.no_download:
        media = download(args.url, dst)
    if not args.no_transcribe:
        if not media.exists():
            sys.exit(f"動画が見つかりません: {media}")
        transcribe(media, dst, args.model, use_gpu=not args.cpu)
    write_meta(dst, args.url, args.course, args.lecture)

if __name__ == "__main__":
    main()
