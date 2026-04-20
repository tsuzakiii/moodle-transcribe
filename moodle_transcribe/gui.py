"""tkinter GUI: paste URL or drag-and-drop audio, queued processing."""
from __future__ import annotations

import queue
import re
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND = True
except Exception:
    TkinterDnD = None  # type: ignore
    DND_FILES = None  # type: ignore
    _DND = False

from . import config as config_mod
from . import moodle as moodle_mod
from . import logging_setup, pipeline, platform_io, selfcheck


class App:
    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        root.title("Moodle 文字起こし")
        root.geometry("720x640")
        self.q: queue.Queue = queue.Queue()

        # URL row
        urlf = ttk.LabelFrame(root, text="Moodleページ URL or m3u8 URL を貼り付け (cURL全体でもOK)")
        urlf.pack(fill="x", padx=8, pady=6)
        self.url_entry = ttk.Entry(urlf)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        ttk.Button(urlf, text="処理", command=self.add_url).pack(side="right", padx=4)

        # D&D zone
        ddf = ttk.LabelFrame(root, text="音声/動画ファイル (mp3/m4a/mp4/wav 等)")
        ddf.pack(fill="x", padx=8, pady=6)
        text = "↓ ここにファイルをドラッグ&ドロップ ↓" if _DND else "(D&D無効: tkinterdnd2 未インストール)"
        self.dd_label = tk.Label(ddf, text=text, bg="#f0f0f0", height=4, relief="ridge")
        self.dd_label.pack(fill="x", padx=4, pady=4)
        if _DND:
            self.dd_label.drop_target_register(DND_FILES)
            self.dd_label.dnd_bind("<<Drop>>", self.on_drop)

        # Override row
        ovf = ttk.LabelFrame(root, text="講義名/回名/ヒント (空欄ならLLMが自動判断)")
        ovf.pack(fill="x", padx=8, pady=6)
        ttk.Label(ovf, text="講義").grid(row=0, column=0, sticky="w", padx=4)
        self.course_var = tk.StringVar()
        self.course_cb = ttk.Combobox(ovf, textvariable=self.course_var,
                                      values=pipeline.list_courses(cfg), width=40)
        self.course_cb.grid(row=0, column=1, sticky="we", padx=4)
        ttk.Label(ovf, text="回名").grid(row=1, column=0, sticky="w", padx=4)
        self.lecture_var = tk.StringVar()
        ttk.Entry(ovf, textvariable=self.lecture_var).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Label(ovf, text="ヒント").grid(row=2, column=0, sticky="w", padx=4)
        self.hint_var = tk.StringVar()
        ttk.Entry(ovf, textvariable=self.hint_var).grid(row=2, column=1, sticky="we", padx=4)
        ttk.Button(ovf, text="講義一覧更新", command=self.refresh_courses).grid(row=0, column=2, padx=4)
        ttk.Button(ovf, text="出力フォルダを開く",
                   command=lambda: platform_io.open_folder(cfg.output_dir)).grid(row=1, column=2, padx=4)
        ttk.Button(ovf, text="クッキー有効性チェック",
                   command=self.check_cookies).grid(row=2, column=2, padx=4)
        ovf.columnconfigure(1, weight=1)

        # Log + status
        logf = ttk.LabelFrame(root, text="ログ")
        logf.pack(fill="both", expand=True, padx=8, pady=6)
        self.log_box = scrolledtext.ScrolledText(logf, height=15, font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)
        self.status = tk.StringVar(value=f"待機中 (transcribe={cfg.transcribe_provider}, llm={cfg.llm_provider})")
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x", side="bottom")

        # Persistent file logger fed by GUI sink
        self.log = logging_setup.make_logger(self._gui_log_sink)

        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=lambda: selfcheck.run(self.cfg, self.log), daemon=True).start()

    def _gui_log_sink(self, line: str) -> None:
        """Receives already-timestamped lines from logging_setup; forward to UI.
        After the Tk root is destroyed, .after() raises — silently swallow."""
        def _append():
            try:
                self.log_box.insert("end", line + "\n")
                self.log_box.see("end")
            except tk.TclError:
                pass
        try:
            self.root.after(0, _append)
        except (RuntimeError, tk.TclError):
            pass

    def refresh_courses(self) -> None:
        self.course_cb["values"] = pipeline.list_courses(self.cfg)

    def check_cookies(self) -> None:
        def _run():
            self.log("[クッキーチェック]")
            ok = moodle_mod.check_cookies_valid(
                self.cfg.cookies_file, self.cfg.moodle["login_check_url"], self.log)
            if ok:
                self.log("  ✓ 有効、ログイン状態維持")
        threading.Thread(target=_run, daemon=True).start()

    def add_url(self) -> None:
        raw = self.url_entry.get().strip()
        m = re.search(r"""curl\s+['"]([^'"]+)['"]""", raw)
        if m:
            url = m.group(1)
        elif self.cfg.moodle["host"] in raw:
            m2 = re.search(rf"https?://{re.escape(self.cfg.moodle['host'])}/\S+", raw)
            url = m2.group(0) if m2 else raw
        else:
            m2 = re.search(r"https?://[^\s'\"]+\.m3u8[^\s'\"]*", raw)
            url = m2.group(0) if m2 else raw
        if not url.startswith("http"):
            self.log("URLが不正です (httpで始まる必要)")
            return
        self.url_entry.delete(0, "end")
        self._enqueue("url", url)

    def on_drop(self, event) -> None:
        files = self.root.tk.splitlist(event.data)
        for f in files:
            p = Path(f)
            if p.exists():
                self._enqueue("audio", str(p))
                self.log(f"キュー追加: {p.name}")

    def _enqueue(self, kind: str, target: str) -> None:
        self.q.put((kind, target,
                    self.course_var.get().strip() or None,
                    self.lecture_var.get().strip() or None,
                    self.hint_var.get().strip()))

    def _worker(self) -> None:
        while True:
            kind, target, course, lecture, hint = self.q.get()
            self.root.after(0, lambda: self.status.set("処理中…"))
            try:
                if kind == "url":
                    pipeline.process_url(self.cfg, target, self.log, course, lecture, hint)
                else:
                    pipeline.process_audio(self.cfg, Path(target), self.log, course, lecture, hint)
                self.root.after(0, self.refresh_courses)
            except Exception as e:
                self.log(f"[エラー] {e}")
                self.log(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self.status.set(
                    f"待機中  (キュー残: {self.q.qsize()})"))


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cfg = config_mod.load()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    root = TkinterDnD.Tk() if _DND else tk.Tk()
    App(root, cfg)
    root.mainloop()


if __name__ == "__main__":
    main()
