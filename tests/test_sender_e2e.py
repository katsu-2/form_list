"""Playwright送信エンジンのE2Eテスト(ローカル擬似サイト)。

確認画面を挟む2段階送信フローと、CAPTCHA検出時の手動キュー行きを検証する。
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.models import SenderProfile
from app.services.sender.engine import send_via_form

FORM_PAGE = """
<html><body>
<form action="/confirm" method="post">
  <p><label for="c">会社名</label><input id="c" type="text" name="company" required></p>
  <p><label for="n">お名前</label><input id="n" type="text" name="name" required></p>
  <p><label for="e">メールアドレス</label><input id="e" type="email" name="email" required></p>
  <p><label for="m">お問い合わせ内容</label><textarea id="m" name="message" required></textarea></p>
  <input type="submit" value="確認画面へ">
</form>
</body></html>
"""

CONFIRM_PAGE = """
<html><body>
<p>以下の内容で送信します。</p>
<form action="/submit" method="post">
  <input type="hidden" name="confirmed" value="1">
  <button type="submit">送信する</button>
</form>
</body></html>
"""

THANKS_PAGE = "<html><body><p>お問い合わせの送信が完了しました。ありがとうございました。</p></body></html>"

CAPTCHA_PAGE = """
<html><body>
<form action="/confirm" method="post">
  <input type="email" name="email">
  <textarea name="message"></textarea>
  <div class="g-recaptcha" data-sitekey="x"></div>
</form>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _respond(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/captcha"):
            self._respond(CAPTCHA_PAGE)
        else:
            self._respond(FORM_PAGE)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(length).decode("utf-8")
        if self.path == "/confirm":
            self.server.submissions.append(("confirm", payload))
            self._respond(CONFIRM_PAGE)
        elif self.path == "/submit":
            self.server.submissions.append(("submit", payload))
            self._respond(THANKS_PAGE)
        else:
            self._respond(FORM_PAGE)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.submissions = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


@pytest.fixture
def profile():
    return SenderProfile(
        company_name="自社株式会社",
        person_name="山田太郎",
        email="taro@example.com",
    )


MAPPING = {
    "company_name": "company",
    "person_name": "name",
    "email": "email",
    "body": "message",
}


async def test_send_two_step_flow(fake_site, profile, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.sender.engine.SCREENSHOT_DIR", str(tmp_path))
    port = fake_site.server_address[1]
    outcome = await send_via_form(
        f"http://127.0.0.1:{port}/contact",
        MAPPING,
        profile,
        "テスト本文です。",
        None,
    )
    assert outcome.status == "sent", outcome.detail
    steps = [s for s, _ in fake_site.submissions]
    assert steps == ["confirm", "submit"]
    confirm_payload = fake_site.submissions[0][1]
    assert "company" in confirm_payload
    assert outcome.screenshot_path is not None


async def test_dry_run_does_not_submit(fake_site, profile, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.sender.engine.SCREENSHOT_DIR", str(tmp_path))
    port = fake_site.server_address[1]
    outcome = await send_via_form(
        f"http://127.0.0.1:{port}/contact",
        MAPPING,
        profile,
        "テスト本文です。",
        None,
        dry_run=True,
    )
    assert outcome.status == "dry_run"
    assert fake_site.submissions == []


async def test_captcha_goes_to_manual(fake_site, profile, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.sender.engine.SCREENSHOT_DIR", str(tmp_path))
    port = fake_site.server_address[1]
    outcome = await send_via_form(
        f"http://127.0.0.1:{port}/captcha",
        MAPPING,
        profile,
        "テスト本文です。",
        None,
    )
    assert outcome.status == "manual"
    assert fake_site.submissions == []
