"""Startup self-check: configured providers / API keys / cookies / claude CLI."""
from __future__ import annotations

import shutil
from typing import Callable

from . import config as config_mod
from . import moodle as moodle_mod
from .config import Config

Logger = Callable[[str], None]


def run(cfg: Config, log: Logger, *, check_cookies: bool = True) -> bool:
    """Print warnings for any misconfiguration; return True if everything looks OK."""
    log("[セルフチェック]")
    ok = True

    # output dir
    try:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        log(f"  ✓ 出力先: {cfg.output_dir}")
    except Exception as e:
        log(f"  ❌ 出力先作成失敗: {e}")
        ok = False

    # transcribe provider
    tp = cfg.transcribe_provider
    if tp == "local":
        try:
            import faster_whisper  # noqa: F401
            log("  ✓ 文字起こし: local (faster-whisper)")
        except ImportError:
            log("  ❌ faster-whisper 未インストール → pip install faster-whisper")
            ok = False
    elif tp in ("openai", "groq"):
        if not config_mod.get_api_key(tp):
            log(f"  ❌ {tp.upper()}_API_KEY 未設定 (env var で設定してください)")
            ok = False
        else:
            log(f"  ✓ 文字起こし: {tp} (APIキー設定済み)")
    else:
        log(f"  ❌ 未知のtranscribe.provider: {tp}")
        ok = False

    # llm provider
    lp = cfg.llm_provider
    if lp == "claude_cli":
        if shutil.which("claude") is None:
            log("  ❌ claude CLI が PATH に無い → Claude Code をインストールするか、")
            log("     config.toml で [llm] provider を 'openai' / 'anthropic' に変更してください")
            ok = False
        else:
            log(f"  ✓ ルーティング: claude_cli ({cfg.llm['claude_cli']['model']})")
    elif lp == "anthropic":
        if not config_mod.get_api_key("anthropic"):
            log("  ❌ ANTHROPIC_API_KEY 未設定")
            ok = False
        else:
            log(f"  ✓ ルーティング: anthropic ({cfg.llm['anthropic']['model']})")
    elif lp == "openai":
        if not config_mod.get_api_key("openai"):
            log("  ❌ OPENAI_API_KEY 未設定")
            ok = False
        else:
            log(f"  ✓ ルーティング: openai ({cfg.llm['openai']['model']})")
    else:
        log(f"  ❌ 未知のllm.provider: {lp}")
        ok = False

    # cookies (optional — only if user plans to use Moodle URLs)
    if check_cookies:
        if not cfg.cookies_file.exists():
            log(f"  ⚠ クッキーファイル無し: {cfg.cookies_file}")
            log("     (Moodle URL機能を使わないなら無視可、使うなら拡張からエクスポートを)")
        else:
            valid = moodle_mod.check_cookies_valid(
                cfg.cookies_file, cfg.moodle["login_check_url"], log)
            if valid:
                log("  ✓ Moodleクッキー有効")
            else:
                log("  ⚠ Moodleクッキー期限切れ — 再エクスポートしてください")

    log(f"[セルフチェック結果] {'OK' if ok else '要対応あり'}")
    return ok
