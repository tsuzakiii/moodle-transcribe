"""
Moodle / 録音ファイル → 文字起こし → Haikuで自動振り分け GUI

起動: pythonw -3.14 C:/ClaudeCode/moodle_gui.py
"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# CUDA DLL setup (same as moodle_transcribe.py)
import importlib.util
for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
    try:
        spec = importlib.util.find_spec(pkg)
        if spec and spec.submodule_search_locations:
            bin_dir = os.path.join(spec.submodule_search_locations[0], "bin")
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
                _ext = bin_dir
                os.environ["PATH"] = _ext + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, scrolledtext
from tkinterdnd2 import TkinterDnD, DND_FILES

ROOT = Path(r"C:\ClaudeCode\moodle_out")
ROOT.mkdir(exist_ok=True)
SCRATCH = Path.home() / ".claude" / "_routing_scratch"
SCRATCH.mkdir(parents=True, exist_ok=True)
COOKIES_FILE = Path(r"C:\ClaudeCode\moodle_cookies.txt")

HEADERS = {
    "Origin": "https://wsdmoodle.waseda.jp",
    "Referer": "https://wsdmoodle.waseda.jp/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/147.0.0.0 Safari/537.36",
}

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW (Windows)

def safe(name: str) -> str:
    return _INVALID.sub("_", name).strip().strip(".") or "untitled"

# ---------------- core processing ----------------

def check_cookies_valid(log) -> bool:
    """クッキーで /my/ にアクセスしてログイン維持されてるか確認。"""
    from http.cookiejar import MozillaCookieJar
    from curl_cffi import requests as cr
    if not COOKIES_FILE.exists():
        log(f"  ❌ クッキーファイルなし: {COOKIES_FILE}")
        return False
    cj = MozillaCookieJar()
    cj.load(str(COOKIES_FILE), ignore_discard=True, ignore_expires=True)
    cookies = {c.name: c.value for c in cj}
    try:
        r = cr.get("https://wsdmoodle.waseda.jp/my/", cookies=cookies,
                   impersonate="chrome", allow_redirects=False, timeout=15)
    except Exception as e:
        log(f"  ❌ クッキー確認の通信失敗: {e}")
        return False
    if r.status_code == 200:
        return True
    loc = r.headers.get("Location", "")
    log(f"  ❌ クッキー期限切れ (status={r.status_code}, redirect→{loc[:80]})")
    log(f"     → Chrome拡張 'Get cookies.txt LOCALLY' で wsdmoodle.waseda.jp を再エクスポートし、")
    log(f"        {COOKIES_FILE} に上書き保存してください")
    return False

def resolve_moodle_url(moodle_url: str, log) -> tuple[str, str]:
    """Moodleページから (m3u8 URL, page title) を抽出。Playwrightでヘッドレスブラウザ実行。"""
    import asyncio
    from http.cookiejar import MozillaCookieJar
    from playwright.async_api import async_playwright
    if not COOKIES_FILE.exists():
        raise RuntimeError(f"クッキーファイルがありません: {COOKIES_FILE}\nChromeで wsdmoodle にログイン状態で 'Get cookies.txt LOCALLY' 拡張から書き出してください")
    if not check_cookies_valid(log):
        raise RuntimeError("Moodleクッキーが無効/期限切れです。再エクスポート後にやり直してください")

    async def _run():
        cj = MozillaCookieJar(); cj.load(str(COOKIES_FILE), ignore_discard=True, ignore_expires=True)
        cookies = []
        for c in cj:
            cookies.append({
                "name": c.name, "value": c.value, "domain": c.domain,
                "path": c.path, "secure": bool(c.secure), "httpOnly": False,
                "expires": c.expires if c.expires else -1,
            })
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            urls = []
            page.on("request", lambda req: urls.append(req.url) if "m3u8" in req.url else None)
            await page.goto(moodle_url, wait_until="networkidle", timeout=30000)
            title = await page.title()
            await asyncio.sleep(3)
            await browser.close()
            return title, urls

    log("  Moodleページを読み込み中 (Playwright)…")
    title, urls = asyncio.run(_run())
    masters = [u for u in urls if "/index.m3u8" in u]
    if not masters:
        raise RuntimeError(f"m3u8が見つかりません。取得URL: {urls}")
    m3u8 = masters[0]
    log(f"  ページタイトル: {title}")
    log(f"  m3u8 取得OK")
    return m3u8, title

def list_courses() -> list[str]:
    if not ROOT.exists():
        return []
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith("_"))

def download_hls(url: str, dst_dir: Path, log) -> Path:
    import imageio_ffmpeg
    out = dst_dir / "video.mp4"
    if out.exists():
        log(f"  既存スキップ: {out.name}")
        return out
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    hdr = "".join(f"{k}: {v}\r\n" for k, v in HEADERS.items())
    cmd = [ffmpeg, "-y", "-headers", hdr, "-i", url, "-c", "copy",
           "-bsf:a", "aac_adtstoasc", str(out)]
    log(f"  ffmpeg DL中…")
    p = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg失敗: {p.stderr[-500:]}")
    return out

def _ts(s: float) -> str:
    h = int(s // 3600); s -= h * 3600
    m = int(s // 60);   s -= m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

_model_cache = {"m": None}

def get_model():
    if _model_cache["m"] is None:
        from faster_whisper import WhisperModel
        try:
            _model_cache["m"] = WhisperModel("large-v3", device="cuda", compute_type="float16")
        except Exception:
            _model_cache["m"] = WhisperModel("large-v3", device="cpu", compute_type="int8")
    return _model_cache["m"]

def transcribe(media: Path, dst_dir: Path, log) -> Path:
    model = get_model()
    txt = dst_dir / "transcript.txt"
    srt = dst_dir / "transcript.srt"
    if txt.exists():
        log(f"  既存スキップ: {txt.name}")
        return txt
    log("  whisper large-v3 で文字起こし中…")
    segments, _ = model.transcribe(str(media), language="ja", vad_filter=True, beam_size=5)
    n = 0
    with txt.open("w", encoding="utf-8") as ft, srt.open("w", encoding="utf-8") as fs:
        for i, seg in enumerate(segments, 1):
            line = seg.text.strip()
            ft.write(line + "\n")
            fs.write(f"{i}\n{_ts(seg.start)} --> {_ts(seg.end)}\n{line}\n\n")
            n += 1
    log(f"  完了 ({n} セグメント)")
    return txt

def list_existing_lectures() -> dict[str, list[tuple[str, str]]]:
    """{course: [(lecture_name, transcript_head), ...]} 既存講義+各回の冒頭500文字"""
    result = {}
    for c in list_courses():
        cdir = ROOT / c
        items = []
        for ldir in sorted(p for p in cdir.iterdir() if p.is_dir()):
            txt = ldir / "transcript.txt"
            head = ""
            if txt.exists():
                head = txt.read_text(encoding="utf-8", errors="ignore")[:500]
            items.append((ldir.name, head))
        result[c] = items
    return result

def route_with_haiku(transcript_path: Path, log, hint: str = "") -> dict:
    """Haikuに講義/回を判定。既存回との重複も検出。
    返り値: {course, path (list of segments), is_new_course, is_duplicate, reason}"""
    text = transcript_path.read_text(encoding="utf-8")[:3000]
    existing = list_existing_lectures()
    if existing:
        ex_str = ""
        for c, items in existing.items():
            ex_str += f"\n## {c}\n"
            for name, head in items:
                ex_str += f"- {name}\n  冒頭: {head[:300].replace(chr(10), ' ')}\n"
    else:
        ex_str = "\n(なし)"
    hint_block = f"\n# ユーザーからのヒント\n{hint.strip()}\n" if hint and hint.strip() else ""
    prompt = f"""新しい大学講義動画の文字起こし冒頭が来ました。これを既存講義フォルダのどこに配置すべきか、また既存回の重複でないかを判断してください。

# 既存講義フォルダと各回 (フォルダ構造 + 冒頭300文字)
{ex_str}
{hint_block}
# 新しい文字起こし冒頭 (最大3000文字)
{text}

# 出力形式
以下のJSONのみを出力。説明文・コードブロック・前置きは一切不要。

{{"course": "<講義名>", "path": ["<segment1>", "<segment2>", ...], "is_new_course": <true/false>, "is_duplicate": <true/false>, "reason": "<判断理由を1行で>"}}

ルール:
- **重複判定優先**: 既存回の冒頭文と新しい冒頭文が酷似している (同じ授業の再録/別画質含む) なら is_duplicate=true。このとき course と path は **既存リストにある構造そのまま** を出力 (改名・改造提案は禁止)
- 既存講義の新しい回なら is_new_course=false、is_duplicate=false で既存講義名 + 新パスを提案
- 該当する既存講義がなければ is_new_course=true で新規講義名を提案
- **path は階層リスト**: 1階層なら ["01_イントロダクション"]、第N回内に複数動画ある場合は ["第1回", "01_イントロダクション1"] のように深くしてOK
- 既存講義に既に深い階層構造があれば、それに合わせて新動画も同じ深さで配置 (一貫性重視)
- ユーザーヒントがあればそれを優先的に使う (回番号、サブタイトル等)
- 各セグメントは "01_短い名前" 形式が好ましい (数字2桁プレフィックスで並び順固定)
- 回番号が冒頭/ヒントで明示されていれば必ず反映 ("第3回" → "03_xxx" or ["第3回", ...])
- 不明な場合は ["00_unknown"] """
    log("  Haikuで振り分け判定中…")
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", prompt],
            cwd=str(SCRATCH), capture_output=True, text=True,
            encoding="utf-8", timeout=120, creationflags=NO_WINDOW,
        )
        out = result.stdout.strip()
    finally:
        for f in SCRATCH.rglob("*.jsonl"):
            try: f.unlink()
            except Exception: pass
    m = re.search(r'\{.*"course".*\}', out, re.DOTALL)
    if not m:
        log(f"  Haiku応答パース失敗: {out[:200]}")
        return {"course": "_unsorted", "path": [datetime.now().strftime("%Y%m%d_%H%M%S")],
                "is_new_course": True, "is_duplicate": False, "reason": "Haiku応答パース失敗"}
    try:
        data = json.loads(m.group(0))
    except Exception as e:
        log(f"  JSON parse失敗 ({e}): {out[:200]}")
        return {"course": "_unsorted", "path": [datetime.now().strftime("%Y%m%d_%H%M%S")],
                "is_new_course": True, "is_duplicate": False, "reason": "JSON parse失敗"}
    # 後方互換: lecture (str) しか返ってこない場合は path に変換
    if "path" not in data and "lecture" in data:
        data["path"] = [data["lecture"]]
    if not data.get("path"):
        data["path"] = ["00_unknown"]
    log(f"  → {data['course']}/{'/'.join(data['path'])}  ({data.get('reason','')})")
    return data

def write_meta(dst: Path, **fields):
    meta = dst / "meta.json"
    data = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    data.update(fields)
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    meta.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def process_url(url: str, log, course: str | None = None, lecture: str | None = None, hint: str = ""):
    log(f"[URL] {url[:80]}…")
    auto_hint = ""
    # Moodleページなら m3u8 + タイトル抽出
    if "wsdmoodle.waseda.jp" in url:
        m3u8, title = resolve_moodle_url(url, log)
        url = m3u8
        # タイトル末尾の " | Waseda Moodle" などを削る
        clean_title = re.sub(r'\s*[|｜]\s*Waseda Moodle\s*$', '', title).strip()
        auto_hint = f"Moodleページタイトル: {clean_title}"
    combined_hint = (hint + ("\n" + auto_hint if auto_hint else "")).strip()
    staging = ROOT / "_staging" / datetime.now().strftime("%Y%m%d_%H%M%S")
    staging.mkdir(parents=True, exist_ok=True)
    media = download_hls(url, staging, log)
    transcript = transcribe(media, staging, log)
    if not (course and lecture):
        routed = route_with_haiku(transcript, log, hint=combined_hint)
        course = course or routed["course"]
        path_segs = routed["path"] if not lecture else [lecture]
        reason = routed.get("reason", "")
        if routed.get("is_duplicate"):
            existing = ROOT.joinpath(safe(course), *(safe(s) for s in path_segs))
            log(f"  ⚠️ 既存回の重複と判定 → staging破棄 ({existing.relative_to(ROOT)})")
            shutil.rmtree(staging, ignore_errors=True)
            return existing
    else:
        path_segs = [lecture]
        reason = "ユーザー指定"
    final = ROOT.joinpath(safe(course), *(safe(s) for s in path_segs))
    if final.exists():
        log(f"  既存フォルダあり、_dup付与: {final.name}")
        final = final.with_name(final.name + "_dup_" + datetime.now().strftime("%H%M%S"))
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(final))
    write_meta(final, course=course, lecture=lecture, source_url=url, hint=combined_hint, routing_reason=reason)
    log(f"[完了] {final}")
    return final

def process_audio(path: Path, log, course: str | None = None, lecture: str | None = None, hint: str = ""):
    log(f"[音声] {path.name}")
    staging = ROOT / "_staging" / datetime.now().strftime("%Y%m%d_%H%M%S")
    staging.mkdir(parents=True, exist_ok=True)
    dst_audio = staging / ("audio" + path.suffix.lower())
    shutil.copy2(path, dst_audio)
    transcript = transcribe(dst_audio, staging, log)
    if not (course and lecture):
        routed = route_with_haiku(transcript, log)
        course = course or routed["course"]
        lecture = lecture or routed["lecture"]
        reason = routed.get("reason", "")
    else:
        reason = "ユーザー指定"
    final = ROOT / safe(course) / safe(lecture)
    if final.exists():
        final = final.with_name(final.name + "_dup_" + datetime.now().strftime("%H%M%S"))
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(final))
    write_meta(final, course=course, lecture=lecture, source_file=str(path), routing_reason=reason)
    log(f"[完了] {final}")
    return final

# ---------------- GUI ----------------

class App:
    def __init__(self, root):
        self.root = root
        root.title("Moodle 文字起こし")
        root.geometry("700x600")
        self.q = queue.Queue()
        self.busy = False

        # URL row
        urlf = ttk.LabelFrame(root, text="Moodleページ URL or m3u8 URL を貼り付け (cURLでもOK)")
        urlf.pack(fill="x", padx=8, pady=6)
        self.url_entry = ttk.Entry(urlf)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        ttk.Button(urlf, text="処理", command=self.add_url).pack(side="right", padx=4)

        # D&D zone
        ddf = ttk.LabelFrame(root, text="音声/動画ファイル (mp3/m4a/mp4/wav 等) をここにドロップ")
        ddf.pack(fill="x", padx=8, pady=6)
        self.dd_label = tk.Label(ddf, text="↓ ここにファイルをドラッグ&ドロップ ↓",
                                  bg="#f0f0f0", height=4, relief="ridge")
        self.dd_label.pack(fill="x", padx=4, pady=4)
        self.dd_label.drop_target_register(DND_FILES)
        self.dd_label.dnd_bind("<<Drop>>", self.on_drop)

        # Override (optional)
        ovf = ttk.LabelFrame(root, text="講義名/回名を手動指定 (空欄ならHaikuが自動判断)")
        ovf.pack(fill="x", padx=8, pady=6)
        ttk.Label(ovf, text="講義").grid(row=0, column=0, sticky="w", padx=4)
        self.course_var = tk.StringVar()
        self.course_cb = ttk.Combobox(ovf, textvariable=self.course_var, values=list_courses(), width=40)
        self.course_cb.grid(row=0, column=1, sticky="we", padx=4)
        ttk.Label(ovf, text="回名").grid(row=1, column=0, sticky="w", padx=4)
        self.lecture_var = tk.StringVar()
        ttk.Entry(ovf, textvariable=self.lecture_var).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Label(ovf, text="ヒント").grid(row=2, column=0, sticky="w", padx=4)
        self.hint_var = tk.StringVar()
        hint_entry = ttk.Entry(ovf, textvariable=self.hint_var)
        hint_entry.grid(row=2, column=1, sticky="we", padx=4)
        ttk.Button(ovf, text="講義一覧更新", command=self.refresh_courses).grid(row=0, column=2, padx=4)
        ttk.Button(ovf, text="出力フォルダを開く", command=lambda: os.startfile(ROOT)).grid(row=1, column=2, padx=4)
        ttk.Button(ovf, text="クッキー有効性チェック", command=self.check_cookies).grid(row=2, column=2, padx=4)
        # ヒント例ラベル
        ttk.Label(ovf, text="例: 第1回の3本のうち1本目 / 講義タイトル「データの可視化」 等",
                  foreground="gray").grid(row=3, column=1, sticky="w", padx=4)
        ovf.columnconfigure(1, weight=1)

        # Log
        logf = ttk.LabelFrame(root, text="ログ")
        logf.pack(fill="both", expand=True, padx=8, pady=6)
        self.log_box = scrolledtext.ScrolledText(logf, height=15, font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)

        # Status
        self.status = tk.StringVar(value="待機中")
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x", side="bottom")

        threading.Thread(target=self._worker, daemon=True).start()

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.root.after(0, lambda: (
            self.log_box.insert("end", f"{ts}  {msg}\n"),
            self.log_box.see("end"),
        ))

    def refresh_courses(self):
        self.course_cb["values"] = list_courses()

    def check_cookies(self):
        def _run():
            self.log("[クッキーチェック]")
            ok = check_cookies_valid(self.log)
            if ok:
                self.log("  ✓ 有効、ログイン状態維持")
        threading.Thread(target=_run, daemon=True).start()

    def add_url(self):
        raw = self.url_entry.get().strip()
        # cURLコマンドからURL抽出 (curl '...' -H ... or curl "..." -H ...)
        m = re.search(r"""curl\s+['"]([^'"]+)['"]""", raw)
        if m:
            url = m.group(1)
        elif "wsdmoodle.waseda.jp" in raw:
            m2 = re.search(r"https?://wsdmoodle\.waseda\.jp/\S+", raw)
            url = m2.group(0) if m2 else raw
        else:
            # m3u8っぽいURLを直接抽出
            m2 = re.search(r"https?://[^\s'\"]+\.m3u8[^\s'\"]*", raw)
            url = m2.group(0) if m2 else raw
        if not url.startswith("http"):
            self.log("URLが不正です (httpで始まる必要)")
            return
        self.url_entry.delete(0, "end")
        self.q.put(("url", url, self.course_var.get().strip() or None,
                    self.lecture_var.get().strip() or None,
                    self.hint_var.get().strip()))
        self.log(f"キュー追加: URL")

    def on_drop(self, event):
        # event.data may contain multiple files (space-separated, with {} around paths with spaces)
        files = self.root.tk.splitlist(event.data)
        for f in files:
            p = Path(f)
            if p.exists():
                self.q.put(("audio", str(p), self.course_var.get().strip() or None,
                            self.lecture_var.get().strip() or None,
                            self.hint_var.get().strip()))
                self.log(f"キュー追加: {p.name}")

    def _worker(self):
        while True:
            kind, target, course, lecture, hint = self.q.get()
            self.busy = True
            self.root.after(0, lambda: self.status.set("処理中…"))
            try:
                if kind == "url":
                    process_url(target, self.log, course, lecture, hint)
                else:
                    process_audio(Path(target), self.log, course, lecture, hint)
                self.root.after(0, self.refresh_courses)
            except Exception as e:
                import traceback
                self.log(f"[エラー] {e}")
                self.log(traceback.format_exc())
            finally:
                self.busy = False
                self.root.after(0, lambda: self.status.set(
                    f"待機中  (キュー残: {self.q.qsize()})"))

if __name__ == "__main__":
    root = TkinterDnD.Tk()
    App(root)
    root.mainloop()
