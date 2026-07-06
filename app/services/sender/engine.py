"""Playwright によるフォーム送信エンジン。

安全設計:
- 送信直前にも CAPTCHA・営業お断り文言を再チェックし、該当したら送信しない
- 送信ボタンクリック後に完了文言を確認できた場合のみ「送信成功」とする。
  確認できない場合は重複送信を避けるため「手動確認」扱いにする
- dry_run=True なら入力まで行い送信ボタンは押さない(動作確認用)
- 全ての結果でスクリーンショットを保存する
"""
import glob
import os
import re
from dataclasses import dataclass
from datetime import datetime

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeout, async_playwright

from app.models import SenderProfile
from app.services.form_parser.parser import CAPTCHA_MARKERS, SALES_PROHIBITED_PHRASES
from app.services.sender.values import choose_select_option, resolve_field_value

SCREENSHOT_DIR = os.environ.get("SCREENSHOT_DIR", "screenshots")

SUBMIT_BUTTON_PATTERN = re.compile(r"送信|確認|submit|send|この内容で", re.IGNORECASE)
FINAL_SUBMIT_PATTERN = re.compile(r"送信|submit|send", re.IGNORECASE)
SUCCESS_TEXT_PATTERN = re.compile(
    r"送信(が|を)?完了|送信いたしました|送信しました|受け付けました|受付けました|"
    r"ありがとうございま|お問い合わせを承りました|thank you",
    re.IGNORECASE,
)
SUCCESS_URL_PATTERN = re.compile(r"thanks|thank-you|complete|kanryo|finish", re.IGNORECASE)

NAV_TIMEOUT_MS = 20_000


@dataclass
class SendOutcome:
    status: str  # sent / manual / skipped / failed / dry_run
    detail: str | None = None
    screenshot_path: str | None = None


def _find_chromium_executable() -> str | None:
    """環境にPlaywright管理のChromiumが無い場合に備え、既知の場所を探す。"""
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    for pattern in (
        os.path.join(browsers_path, "chromium-*/chrome-linux/chrome"),
        os.path.join(browsers_path, "chromium"),
    ):
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


async def _screenshot(page: Page, prefix: str) -> str | None:
    try:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = os.path.join(
            SCREENSHOT_DIR, f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        await page.screenshot(path=path, full_page=True)
        return path
    except Exception:
        return None


async def _fill_field(page: Page, name: str, value: str | bool) -> bool:
    """name属性でフィールドを特定して入力する。成功したらTrue。"""
    locator = page.locator(f'[name="{name}"]').first
    if await locator.count() == 0:
        return False
    tag = await locator.evaluate("el => el.tagName.toLowerCase()")
    if tag == "select":
        text = value if isinstance(value, str) else ""
        options = await locator.locator("option").all_text_contents()
        choice = text if text in options else choose_select_option(options)
        if choice:
            await locator.select_option(label=choice)
        return True
    input_type = (await locator.get_attribute("type") or "text").lower()
    if input_type in ("checkbox", "radio"):
        if value:
            await locator.check()
        return True
    if isinstance(value, str):
        await locator.fill(value)
        return True
    return False


async def _click_submit(page: Page, pattern: re.Pattern) -> bool:
    """フォーム内の送信ボタンらしき要素をクリックする。"""
    candidates: list[Locator] = []
    for selector in ("input[type=submit]", "button[type=submit]", "button", "input[type=button]"):
        for loc in await page.locator(selector).all():
            label = (await loc.get_attribute("value")) or (await loc.text_content()) or ""
            if pattern.search(label.strip()):
                candidates.append(loc)
    if not candidates:
        return False
    try:
        await candidates[0].click()
        await page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)
    except PlaywrightTimeout:
        pass  # SPA等で遷移イベントが起きないケースは後段の文言判定に任せる
    await page.wait_for_timeout(1500)
    return True


async def _page_has_success(page: Page) -> bool:
    if SUCCESS_URL_PATTERN.search(page.url):
        return True
    text = await page.evaluate("() => document.body ? document.body.innerText : ''")
    return bool(SUCCESS_TEXT_PATTERN.search(text))


async def send_via_form(
    form_url: str,
    field_mapping: dict[str, str],
    profile: SenderProfile,
    body: str,
    subject: str | None,
    *,
    dry_run: bool = False,
    task_id: int | str = "test",
) -> SendOutcome:
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception:
            executable = _find_chromium_executable()
            if not executable:
                return SendOutcome(status="failed", detail="Chromiumを起動できませんでした")
            browser = await p.chromium.launch(headless=True, executable_path=executable)

        try:
            page = await browser.new_page()
            try:
                await page.goto(form_url, timeout=NAV_TIMEOUT_MS, wait_until="load")
            except PlaywrightTimeout:
                return SendOutcome(status="failed", detail="フォームページの読み込みがタイムアウトしました")

            content = (await page.content()).lower()
            if any(marker in content for marker in CAPTCHA_MARKERS):
                shot = await _screenshot(page, f"task{task_id}_captcha")
                return SendOutcome(
                    status="manual", detail="CAPTCHAを検出したため手動対応が必要です",
                    screenshot_path=shot,
                )
            page_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            normalized = " ".join(page_text.split())
            for phrase in SALES_PROHIBITED_PHRASES:
                if phrase in normalized:
                    shot = await _screenshot(page, f"task{task_id}_prohibited")
                    return SendOutcome(
                        status="skipped", detail=f"営業お断り文言を検出: {phrase}",
                        screenshot_path=shot,
                    )

            filled, not_found = [], []
            for role, name in field_mapping.items():
                value = resolve_field_value(role, profile, body, subject)
                if value is None and role != "inquiry_type":
                    continue
                ok = await _fill_field(page, name, value if value is not None else "")
                (filled if ok else not_found).append(role)

            if "body" not in filled:
                shot = await _screenshot(page, f"task{task_id}_nobody")
                return SendOutcome(
                    status="failed", detail="本文フィールドに入力できませんでした",
                    screenshot_path=shot,
                )

            if dry_run:
                shot = await _screenshot(page, f"task{task_id}_dryrun")
                detail = f"dry-run: 入力のみ実行(入力済み: {', '.join(filled)}"
                if not_found:
                    detail += f" / 見つからず: {', '.join(not_found)}"
                return SendOutcome(status="dry_run", detail=detail + ")", screenshot_path=shot)

            if not await _click_submit(page, SUBMIT_BUTTON_PATTERN):
                shot = await _screenshot(page, f"task{task_id}_nosubmit")
                return SendOutcome(
                    status="failed", detail="送信ボタンが見つかりませんでした",
                    screenshot_path=shot,
                )

            # 確認画面パターン: 完了になっておらず送信ボタンがまだあれば、もう一度だけ押す
            if not await _page_has_success(page):
                await _click_submit(page, FINAL_SUBMIT_PATTERN)

            shot = await _screenshot(page, f"task{task_id}_result")
            if await _page_has_success(page):
                return SendOutcome(status="sent", detail=None, screenshot_path=shot)
            return SendOutcome(
                status="manual",
                detail=(
                    "送信後に完了文言を確認できませんでした。"
                    "重複送信を避けるためスクリーンショットを確認してください"
                ),
                screenshot_path=shot,
            )
        except Exception as exc:  # ネットワーク断など想定外の失敗
            return SendOutcome(status="failed", detail=f"予期しないエラー: {exc}")
        finally:
            await browser.close()
