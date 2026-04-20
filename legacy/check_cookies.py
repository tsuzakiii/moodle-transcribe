"""Moodleクッキーの有効性を確認 (実際にページを取りに行ってログイン状態か判定)"""
import sys
from http.cookiejar import MozillaCookieJar
from curl_cffi import requests as cr

COOKIES = r"C:\ClaudeCode\moodle_cookies.txt"
TEST_URL = "https://wsdmoodle.waseda.jp/my/"

cj = MozillaCookieJar()
cj.load(COOKIES, ignore_discard=True, ignore_expires=True)
cookies = {c.name: c.value for c in cj}
r = cr.get(TEST_URL, cookies=cookies, impersonate="chrome", allow_redirects=False)

if r.status_code == 200:
    print("OK: クッキー有効、ログイン状態維持")
    sys.exit(0)
elif r.status_code in (301, 302, 303) and "login" in r.headers.get("Location", "").lower():
    print(f"NG: ログイン切れ (→{r.headers.get('Location','')})")
    print("  Chrome拡張で moodle_cookies.txt を再エクスポートしてください")
    sys.exit(1)
else:
    print(f"判定不能: status={r.status_code}, location={r.headers.get('Location','')}")
    sys.exit(2)
