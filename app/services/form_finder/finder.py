"""問い合わせフォームURLの探索。

探索手順:
1. robots.txt を確認し、許可されていないパスは探索しない
2. 典型パス(/contact, /inquiry 等)を順に試す
3. 見つからなければトップページのリンクテキスト(「お問い合わせ」等)を解析して辿る
4. 候補ページにフォーム(textarea or email欄あり)が存在すれば確定

MVPでは httpx + BeautifulSoup の静的取得のみ。JSレンダリングが必要なサイトは
Phase 2 以降で Playwright にフォールバックする。
"""
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from bs4 import BeautifulSoup

from app.services.form_parser.parser import ParsedForm, parse_form_page

USER_AGENT = "form-sales-tools/0.1 (contact form finder)"

TYPICAL_PATHS = [
    "/contact",
    "/contact/",
    "/contact.html",
    "/contact.php",
    "/inquiry",
    "/inquiry/",
    "/inquiry.html",
    "/contactus",
    "/contact-us",
    "/form",
    "/otoiawase",
    "/toiawase",
]

LINK_TEXT_KEYWORDS = [
    "お問い合わせ",
    "お問合せ",
    "お問合わせ",
    "問い合わせ",
    "コンタクト",
    "contact",
    "inquiry",
    "ご相談",
    "資料請求",
]

REQUEST_TIMEOUT = 10.0


@dataclass
class FormFindResult:
    form_url: str | None
    forms: list[ParsedForm]
    checked_urls: list[str]
    error: str | None = None

    @property
    def found(self) -> bool:
        return self.form_url is not None


def _robots_allowed(client: httpx.Client, base_url: str, path: str) -> bool:
    parser = urllib.robotparser.RobotFileParser()
    try:
        resp = client.get(urljoin(base_url, "/robots.txt"))
        if resp.status_code != 200:
            return True
        parser.parse(resp.text.splitlines())
    except httpx.HTTPError:
        return True
    return parser.can_fetch(USER_AGENT, urljoin(base_url, path))


def _fetch(client: httpx.Client, url: str) -> str | None:
    try:
        resp = client.get(url)
        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
            return resp.text
    except httpx.HTTPError:
        pass
    return None


def _contact_links_from_top(html: str, base_url: str) -> list[str]:
    """トップページから問い合わせらしいリンクを抽出する(同一ドメインのみ)。"""
    soup = BeautifulSoup(html, "lxml")
    base_host = urlparse(base_url).hostname
    candidates: list[str] = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        href = a["href"]
        if any(kw.lower() in text or kw.lower() in href.lower() for kw in LINK_TEXT_KEYWORDS):
            absolute = urljoin(base_url, href)
            if urlparse(absolute).hostname == base_host and absolute not in candidates:
                candidates.append(absolute)
    return candidates


def find_contact_form(site_url: str) -> FormFindResult:
    """サイトURLから問い合わせフォームのURLを探し、見つかればフォームを解析して返す。"""
    checked: list[str] = []
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as client:
        parsed = urlparse(site_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        def try_url(url: str) -> FormFindResult | None:
            if url in checked:
                return None
            checked.append(url)
            if not _robots_allowed(client, base_url, urlparse(url).path or "/"):
                return None
            html = _fetch(client, url)
            if html is None:
                return None
            forms = parse_form_page(html)
            if forms:
                return FormFindResult(form_url=url, forms=forms, checked_urls=checked)
            return None

        # 1. 典型パス
        for path in TYPICAL_PATHS:
            result = try_url(urljoin(base_url, path))
            if result:
                return result

        # 2. トップページのリンク解析
        top_html = _fetch(client, site_url)
        if top_html is None:
            return FormFindResult(
                form_url=None, forms=[], checked_urls=checked,
                error="トップページを取得できませんでした",
            )
        for link in _contact_links_from_top(top_html, site_url)[:5]:
            result = try_url(link)
            if result:
                return result
            # 問い合わせページが「フォームへ」の中間ページである場合に1階層だけ辿る
            html = _fetch(client, link)
            if html:
                for sub_link in _contact_links_from_top(html, link)[:3]:
                    result = try_url(sub_link)
                    if result:
                        return result

        # 3. トップページ自体にフォームが埋まっているケース
        forms = parse_form_page(top_html)
        if forms:
            return FormFindResult(form_url=site_url, forms=forms, checked_urls=checked)

    return FormFindResult(form_url=None, forms=[], checked_urls=checked)
