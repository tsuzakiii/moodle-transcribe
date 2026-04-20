"""High-level processing pipeline used by the GUI and CLI."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import download, moodle, routing, transcribe
from .config import Config

Logger = Callable[[str], None]
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe(name: str) -> str:
    return _INVALID.sub("_", name).strip().strip(".") or "untitled"


def _write_meta(dst: Path, **fields) -> None:
    meta = dst / "meta.json"
    data = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    data.update(fields)
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    meta.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _staging_dir(cfg: Config) -> Path:
    p = cfg.output_dir / "_staging" / datetime.now().strftime("%Y%m%d_%H%M%S")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _finalize(staging: Path, cfg: Config, course: str, path_segs: list[str],
              log: Logger, source: dict, routing_reason: str = "",
              is_duplicate: bool = False) -> Path:
    final = cfg.output_dir.joinpath(_safe(course), *(_safe(s) for s in path_segs))
    if is_duplicate:
        log(f"  ⚠️ 既存回の重複と判定 → staging破棄 ({final.relative_to(cfg.output_dir)})")
        shutil.rmtree(staging, ignore_errors=True)
        return final
    if final.exists():
        final = final.with_name(final.name + "_dup_" + datetime.now().strftime("%H%M%S"))
        log(f"  既存フォルダあり、_dup付与: {final.name}")
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(final))
    _write_meta(final, course=course, path=path_segs, routing_reason=routing_reason, **source)
    log(f"[完了] {final}")
    return final


def _do_transcribe(media: Path, dst: Path, cfg: Config, log: Logger) -> Path:
    txt = dst / "transcript.txt"
    if txt.exists():
        log(f"  既存スキップ: {txt.name}")
        return txt
    provider = cfg.transcribe_provider
    settings = cfg.transcribe.get(provider, {})
    tr = transcribe.get(provider, settings)
    segments = tr.transcribe(media, log)
    txt, srt = transcribe.write_outputs(segments, dst)
    log(f"  書き出し: {txt.name} / {srt.name}")
    return txt


def _route_or_use(transcript: Path, cfg: Config, course: str | None,
                  lecture: str | None, hint: str, log: Logger) -> tuple[str, list[str], str, bool]:
    if course and lecture:
        return course, [lecture], "ユーザー指定", False
    llm_p = cfg.llm_provider
    settings = cfg.llm.get(llm_p, {})
    routed = routing.route(transcript, cfg.output_dir, llm_p, settings, log, hint=hint)
    final_course = course or routed["course"]
    path_segs = [lecture] if lecture else routed["path"]
    return final_course, path_segs, routed.get("reason", ""), bool(routed.get("is_duplicate"))


def process_url(cfg: Config, url: str, log: Logger,
                course: str | None = None, lecture: str | None = None, hint: str = "") -> Path:
    log(f"[URL] {url[:80]}…")
    auto_hint = ""
    if cfg.moodle["host"] in url:
        if not moodle.check_cookies_valid(cfg.cookies_file, cfg.moodle["login_check_url"], log):
            raise RuntimeError("Moodleクッキーが無効/期限切れ")
        m3u8, title = moodle.resolve_video(url, cfg.cookies_file, log,
                                           headless=cfg.gui.get("playwright_headless", True))
        url = m3u8
        auto_hint = f"Moodleページタイトル: {moodle.clean_page_title(title)}"
    combined_hint = (hint + ("\n" + auto_hint if auto_hint else "")).strip()

    staging = _staging_dir(cfg)
    media = download.download_hls(url, staging, cfg.moodle["host"], log)
    transcript = _do_transcribe(media, staging, cfg, log)
    final_course, path_segs, reason, is_dup = _route_or_use(transcript, cfg, course, lecture, combined_hint, log)
    return _finalize(staging, cfg, final_course, path_segs, log,
                     source={"source_url": url, "hint": combined_hint},
                     routing_reason=reason, is_duplicate=is_dup)


def process_audio(cfg: Config, audio_path: Path, log: Logger,
                  course: str | None = None, lecture: str | None = None, hint: str = "") -> Path:
    log(f"[音声] {audio_path.name}")
    staging = _staging_dir(cfg)
    dst_audio = staging / ("audio" + audio_path.suffix.lower())
    shutil.copy2(audio_path, dst_audio)
    transcript = _do_transcribe(dst_audio, staging, cfg, log)
    final_course, path_segs, reason, is_dup = _route_or_use(transcript, cfg, course, lecture, hint, log)
    return _finalize(staging, cfg, final_course, path_segs, log,
                     source={"source_file": str(audio_path), "hint": hint},
                     routing_reason=reason, is_duplicate=is_dup)


def list_courses(cfg: Config) -> list[str]:
    if not cfg.output_dir.exists():
        return []
    return sorted(p.name for p in cfg.output_dir.iterdir()
                  if p.is_dir() and not p.name.startswith("_"))
