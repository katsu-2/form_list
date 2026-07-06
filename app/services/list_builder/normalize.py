"""社名・URLの正規化ユーティリティ。

収集元によって表記がばらつくため、重複排除の前に正規化して比較キーを揃える。
"""
import re
import unicodedata
from urllib.parse import urlparse

# 法人格の表記ゆれ(正規化キー生成時に除去する)
_LEGAL_FORMS = [
    "株式会社",
    "(株)",
    "(株)",
    "有限会社",
    "(有)",
    "(有)",
    "合同会社",
    "合資会社",
    "合名会社",
    "一般社団法人",
    "一般財団法人",
    "公益社団法人",
    "公益財団法人",
    "特定非営利活動法人",
    "NPO法人",
]


def normalize_company_name(name: str) -> str:
    """表示用の正規化: 全角英数→半角、前後空白除去、空白の圧縮。"""
    name = unicodedata.normalize("NFKC", name).strip()
    return re.sub(r"\s+", " ", name)


def company_name_key(name: str) -> str:
    """重複判定用のキー: 法人格・空白・記号を除去して小文字化。"""
    key = normalize_company_name(name)
    for form in _LEGAL_FORMS:
        key = key.replace(form, "")
    key = re.sub(r"[\s・,、。.\-‐―ー]+", "", key)
    return key.lower()


def extract_domain(url_or_domain: str) -> str | None:
    """URLまたはドメイン文字列から登録用ドメイン(小文字、www.除去)を取り出す。"""
    value = url_or_domain.strip()
    if not value:
        return None
    if "://" not in value:
        value = "https://" + value
    host = urlparse(value).hostname
    if not host or "." not in host:
        return None
    host = host.lower()
    return host.removeprefix("www.")


def normalize_site_url(url: str) -> str | None:
    """サイトURLをスキーム付きに正規化する。ドメインが取れなければ None。"""
    value = url.strip()
    if not value:
        return None
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if not parsed.hostname or "." not in parsed.hostname:
        return None
    return value
