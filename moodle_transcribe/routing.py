"""Build the prompt + parse the LLM response that decides where a new
lecture transcript should be filed."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import llm as llm_mod

PROMPT_TEMPLATE = """新しい大学講義動画の文字起こし冒頭が来ました。これを既存講義フォルダのどこに配置すべきか、また既存回の重複でないかを判断してください。

# 既存講義フォルダと各回 (フォルダ構造 + 冒頭300文字)
{existing}
{hint_block}
# 新しい文字起こし冒頭 (最大3000文字)
{transcript_head}

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
- 不明な場合は ["00_unknown"]
"""


def list_existing(root: Path) -> dict[str, list[tuple[str, str]]]:
    """Walk root and return {course: [(relpath_under_course, transcript_head300), ...]}."""
    out: dict[str, list[tuple[str, str]]] = {}
    if not root.exists():
        return out
    for cdir in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        items: list[tuple[str, str]] = []
        for txt in sorted(cdir.rglob("transcript.txt")):
            rel = txt.parent.relative_to(cdir).as_posix()
            head = txt.read_text(encoding="utf-8", errors="ignore")[:300]
            items.append((rel, head))
        if items:
            out[cdir.name] = items
        else:
            out[cdir.name] = []  # course exists but no transcripts yet
    return out


def build_prompt(transcript_head: str, existing: dict[str, list[tuple[str, str]]],
                 hint: str = "") -> str:
    if existing:
        ex_lines: list[str] = []
        for c, items in existing.items():
            ex_lines.append(f"\n## {c}")
            for relpath, head in items:
                snippet = head.replace("\n", " ")[:300]
                ex_lines.append(f"- {relpath}\n  冒頭: {snippet}")
        existing_str = "\n".join(ex_lines)
    else:
        existing_str = "\n(なし)"
    hint_block = f"\n# ユーザーからのヒント\n{hint.strip()}\n" if hint and hint.strip() else ""
    return PROMPT_TEMPLATE.format(
        existing=existing_str, hint_block=hint_block,
        transcript_head=transcript_head[:3000],
    )


def parse_response(text: str) -> dict:
    """Extract first JSON object from `text`, falling back to a synthetic one."""
    m = re.search(r'\{.*"course".*\}', text, re.DOTALL)
    if not m:
        return {"course": "_unsorted",
                "path": [datetime.now().strftime("%Y%m%d_%H%M%S")],
                "is_new_course": True, "is_duplicate": False,
                "reason": "LLM response had no JSON"}
    try:
        data = json.loads(m.group(0))
    except Exception as e:
        return {"course": "_unsorted",
                "path": [datetime.now().strftime("%Y%m%d_%H%M%S")],
                "is_new_course": True, "is_duplicate": False,
                "reason": f"JSON parse failed: {e}"}
    if "path" not in data and "lecture" in data:
        data["path"] = [data["lecture"]]
    if not data.get("path"):
        data["path"] = ["00_unknown"]
    return data


def route(transcript_path: Path, root: Path, llm_provider: str, llm_settings: dict,
          log, hint: str = "") -> dict:
    """End-to-end: read transcript, list existing, ask LLM, parse."""
    text = transcript_path.read_text(encoding="utf-8")[:3000]
    existing = list_existing(root)
    prompt = build_prompt(text, existing, hint=hint)
    log(f"  ルーティング判定中 ({llm_provider})…")
    resp = llm_mod.get(llm_provider, llm_settings).complete(prompt, log)
    data = parse_response(resp)
    log(f"  → {data['course']}/{'/'.join(data['path'])}  ({data.get('reason', '')})")
    return data
