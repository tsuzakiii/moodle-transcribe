# moodle-transcribe

Moodle/HLS の動画を再生せずダウンロードして Whisper で日本語文字起こしし、
LLM が「どの講義の何回目か」を自動判断して所定フォルダに振り分けます。

## 機能

- **Moodleページ URL 直貼り** → Playwright が認証済みヘッドレスChromeで開いて m3u8 とタイトルを抽出
- **m3u8 URL / cURL コマンド全文** 直貼りも対応
- **音声/動画ファイル** D&D で文字起こし (mp3/m4a/mp4/wav 等)
- **自動振り分け**: LLM が冒頭+ヒント+既存講義一覧から `<講義>/<回>` を判定 (深い階層も提案可)
- **重複検出**: 既存回と冒頭が酷似してれば staging 破棄
- **複数Provider対応**: 文字起こしは local/OpenAI/Groq、ルーティングは Claude CLI/Anthropic/OpenAI

## クイックスタート (Windows / Mac / Linux 共通)

### 1. インストール

```bash
git clone <repo>
cd moodle-transcribe
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

# Local Whisperを使う場合 (GPU推奨):
pip install -e ".[gpu]"
playwright install chromium

# API経由の文字起こし/ルーティングを使う場合:
pip install -e ".[remote]"
```

### 2. 設定ファイル

```bash
# Windows: %APPDATA%\moodle-transcribe\config.toml
# Mac:     ~/Library/Application Support/moodle-transcribe/config.toml
# Linux:   ~/.config/moodle-transcribe/config.toml
```

`config.example.toml` をそのコピーすると初期値で動きます。
特に編集したいのは `output_dir`, `[transcribe].provider`, `[llm].provider`。

### 3. APIキー設定 (リモートProviderを使う場合のみ)

環境変数で:

```bash
# Bash/Zsh
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GROQ_API_KEY=gsk_...

# Windows PowerShell
$env:OPENAI_API_KEY = "sk-..."
```

### 4-A. Moodleクッキー (推奨: 自動更新)

ID/パスをOSキーリングに保存すれば、クッキー切れ時に自動ログインして cookies.txt を更新します。毎朝エクスポートし直さなくてOK。

**認証情報登録** (どちらかでOK):

*CLI*:
```bash
moodle-transcribe-cli set-credentials --username your-id@akane.waseda.jp
# Password: (入力、画面非表示)
```

*GUI*: 「**認証情報を登録…**」ボタンをクリック → ID/パス入力

**初回テスト** (ブラウザ可視でフロー確認):
```bash
moodle-transcribe-cli refresh-cookies --show-browser
```
SSOピッカー ("Waseda University Login" 等) → Microsoft ログイン → KMSI → Moodle、の流れが最後まで進めばOK。以降は透過的に走ります。

**登録内容を消す / 入れ直す**:
```bash
moodle-transcribe-cli forget-credentials
moodle-transcribe-cli set-credentials --username 正しいID
```

**保存先**: Windows Credential Manager / macOS Keychain / Linux SecretService (gnome-keyring/KWallet)。コード管理下のファイルには**書きません**。

**制限**: 2FA要求される環境では自動ログイン失敗 → 4-B の手動エクスポートにフォールバック。

**PATHに `moodle-transcribe-cli` が入らなかった場合** (pip install後に `command not found`):
```bash
# A. モジュール形式で直接叩く
py -3.14 -m moodle_transcribe.cli set-credentials --username ...

# B. PowerShell で一時的に PATH 追加
$env:Path += ";$env:APPDATA\Python\Python314\Scripts"
```

### 4-B. Moodleクッキー (手動エクスポート)

Chrome/Edgeに [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) を入れて、Moodle ログイン状態で `wsdmoodle.waseda.jp` (or your Moodle host) を Netscape format で書き出し → 設定ディレクトリの `moodle_cookies.txt` に保存。

### 5. 起動

```bash
# GUI
moodle-transcribe

# CLI
moodle-transcribe-cli url "https://wsdmoodle.waseda.jp/mod/millvi/view.php?id=..."
moodle-transcribe-cli audio /path/to/recording.m4a -c "授業名" -l "01_イントロ"
moodle-transcribe-cli list
moodle-transcribe-cli check-cookies
```

## Provider比較

### 文字起こし (30分動画あたり)

| Provider | コスト | 速度 (RTX 4090) | 備考 |
|---|---|---|---|
| `local` faster-whisper | 0円 | 4分程度 | GPU必須(無いとCPU動作で遅い) |
| `groq` whisper-large-v3-turbo | ~$0.06 | 30秒 | API、無料枠あり |
| `openai` whisper-1 | ~$0.18 | 1-2分 | API |

### LLMルーティング (1回あたり ~3000トークン)

| Provider | モデル | コスト |
|---|---|---|
| `claude_cli` | haiku | サブスク内なら追加0円 |
| `openai` | gpt-5-mini | ~$0.002 |
| `openai` | gpt-4o-mini | ~$0.0005 |
| `anthropic` | claude-haiku-4-5 | ~$0.005 |

## アーキテクチャ

```
moodle_transcribe/
├── pipeline.py        高レベルorchestration (process_url, process_audio)
├── moodle.py          Moodleページ → m3u8 + title (Playwright + curl_cffi)
├── download.py        HLS → mp4 (ffmpeg via imageio-ffmpeg)
├── routing.py         transcript → LLM prompt → JSON parse
├── transcribe/        Provider群 (local/openai/groq)
├── llm/               Provider群 (claude_cli/anthropic/openai)
├── config.py          TOML + env var 読み込み
├── platform_io.py     OS抽象 (paths, subprocess flags, open folder)
├── gui.py             tkinter GUI
└── cli.py             argparse CLI
```

## トラブルシューティング

- **`cublas64_12.dll not found`**: `pip install -e ".[gpu]"` を実行してCUDA DLLを入れる
- **Moodleで403**: `curl_cffi` がTLS指紋偽装するので requests/curl 単独より高い成功率。それでもダメならクッキー期限切れの可能性大 → 再エクスポート
- **D&Dが効かない**: `tkinterdnd2` が入ってないか、Mac/Linuxで Tk のバージョンが古い
- **Playwrightで `Browser executable not found`**: `playwright install chromium` を忘れてないか

## 移植 (他大Moodleで使う場合)

`config.toml` の `[moodle]` セクションを編集:

```toml
[moodle]
host = "moodle.your-uni.ac.jp"
login_check_url = "https://moodle.your-uni.ac.jp/my/"
```

ただし動画プレイヤーが Eviry 系でない場合 (Panopto / Kaltura / Stream)、
`moodle.py` の `resolve_video` は m3u8 抽出ロジックを書き換える必要があります。

## ライセンス

個人利用前提。Moodle の利用規約に従って使用してください。
