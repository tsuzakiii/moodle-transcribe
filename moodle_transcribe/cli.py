"""Command-line interface."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as config_mod
from . import moodle as moodle_mod
from . import pipeline, selfcheck


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="moodle-transcribe-cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    pu = sub.add_parser("url", help="Process a Moodle page or m3u8 URL")
    pu.add_argument("url")
    pu.add_argument("-c", "--course")
    pu.add_argument("-l", "--lecture")
    pu.add_argument("--hint", default="")

    pa = sub.add_parser("audio", help="Process a local audio/video file")
    pa.add_argument("path", type=Path)
    pa.add_argument("-c", "--course")
    pa.add_argument("-l", "--lecture")
    pa.add_argument("--hint", default="")

    sub.add_parser("list", help="List existing courses")
    sub.add_parser("check-cookies", help="Verify Moodle cookies are still valid")
    sub.add_parser("selfcheck", help="Validate config / providers / API keys / cookies")

    args = p.parse_args()
    cfg = config_mod.load()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    if args.cmd == "list":
        for c in pipeline.list_courses(cfg):
            print(c)
        return
    if args.cmd == "check-cookies":
        ok = moodle_mod.check_cookies_valid(cfg.cookies_file, cfg.moodle["login_check_url"], print)
        sys.exit(0 if ok else 1)
    if args.cmd == "selfcheck":
        ok = selfcheck.run(cfg, print)
        sys.exit(0 if ok else 1)
    if args.cmd == "url":
        pipeline.process_url(cfg, args.url, print, args.course, args.lecture, args.hint)
    elif args.cmd == "audio":
        pipeline.process_audio(cfg, args.path, print, args.course, args.lecture, args.hint)


if __name__ == "__main__":
    main()
