"""問い合わせフォームのHTML解析。

- ルールベースのフィールドマッピング(name/id/placeholder/label の日英キーワード辞書)
- CAPTCHA 検出(検出時は自動送信対象から外し手動対応キューへ回すための情報)
- 営業お断り文言の検出(検出時は送信対象から除外する)
"""
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

# フィールドの役割 → 判定キーワード(name/id/placeholder/label テキストに対して部分一致)
FIELD_KEYWORDS: dict[str, list[str]] = {
    "company_name": ["会社名", "企業名", "貴社名", "御社名", "法人名", "company", "corporate"],
    "person_name": ["氏名", "名前", "担当者", "your-name", "fullname", "full_name", "お名前"],
    "person_name_kana": ["フリガナ", "ふりがな", "カナ", "kana", "furigana"],
    "email": ["メール", "mail", "email", "e-mail"],
    "email_confirm": ["確認のため", "メール確認", "mail_confirm", "email_confirm", "confirm_mail"],
    "phone": ["電話", "tel", "phone", "denwa"],
    "postal_code": ["郵便", "zip", "postal"],
    "address": ["住所", "所在地", "address"],
    "department": ["部署", "部門", "department", "division"],
    "position": ["役職", "position", "title"],
    "subject": ["件名", "題名", "subject", "用件"],
    "body": ["問い合わせ内容", "お問い合わせ", "内容", "本文", "メッセージ", "message", "inquiry", "詳細", "ご相談"],
    "inquiry_type": ["種別", "種類", "カテゴリ", "category", "type"],
    "privacy_agree": ["同意", "個人情報", "プライバシー", "privacy", "agree", "consent"],
}

# 役割の優先順(bodyのような広いキーワードは後で判定する)
_ROLE_PRIORITY = [
    "email_confirm",
    "email",
    "company_name",
    "person_name_kana",
    "person_name",
    "phone",
    "postal_code",
    "address",
    "department",
    "position",
    "subject",
    "inquiry_type",
    "privacy_agree",
    "body",
]

CAPTCHA_MARKERS = [
    "g-recaptcha",
    "grecaptcha",
    "recaptcha",
    "h-captcha",
    "hcaptcha",
    "cf-turnstile",
    "turnstile",
    "captcha",
]

# 営業お断りの典型文言
SALES_PROHIBITED_PHRASES = [
    "営業目的の",
    "営業のご連絡はご遠慮",
    "営業・勧誘",
    "営業活動を目的",
    "セールスの目的",
    "売り込み",
    "勧誘はお断り",
    "勧誘目的",
    "営業目的でのお問い合わせはお断り",
    "営業メールはお断り",
    "営業に関するお問い合わせはお断り",
]


@dataclass
class FormField:
    tag: str                    # input / textarea / select
    input_type: str | None      # text / email / tel / checkbox / radio / hidden ...
    name: str | None
    field_id: str | None
    label: str | None
    placeholder: str | None
    required: bool
    role: str | None = None    # FIELD_KEYWORDS のキー。判定できなければ None
    options: list[str] = field(default_factory=list)  # select/radio の選択肢


@dataclass
class ParsedForm:
    action: str | None
    method: str
    fields: list[FormField]
    has_captcha: bool
    sales_prohibited: bool
    prohibited_phrase: str | None = None

    @property
    def field_mapping(self) -> dict[str, str]:
        """role → フィールドname のマッピング(DB保存用)。"""
        mapping: dict[str, str] = {}
        for f in self.fields:
            if f.role and f.name and f.role not in mapping:
                mapping[f.role] = f.name
        return mapping

    @property
    def unmapped_required_fields(self) -> list[str]:
        """必須なのに役割を判定できなかったフィールド(LLM補完 or 手動対応の対象)。"""
        return [f.name or f.field_id or "?" for f in self.fields if f.required and f.role is None]


def _label_text(soup: BeautifulSoup, element: Tag) -> str | None:
    field_id = element.get("id")
    if field_id:
        label = soup.find("label", attrs={"for": field_id})
        if label:
            return label.get_text(" ", strip=True)
    parent_label = element.find_parent("label")
    if parent_label:
        return parent_label.get_text(" ", strip=True)
    # テーブルレイアウトのフォーム(th=項目名, td=入力欄)に対応
    parent_cell = element.find_parent("td")
    if parent_cell:
        row = parent_cell.find_parent("tr")
        if row:
            header = row.find("th")
            if header:
                return header.get_text(" ", strip=True)
    return None


def _guess_role(input_type: str | None, *texts: str | None) -> str | None:
    # type属性そのものが役割を示すケースを先に判定
    if input_type == "email":
        return "email"
    if input_type == "tel":
        return "phone"
    haystack = " ".join(t for t in texts if t).lower()
    if not haystack:
        return None
    for role in _ROLE_PRIORITY:
        if any(kw.lower() in haystack for kw in FIELD_KEYWORDS[role]):
            return role
    return None


def detect_captcha(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in CAPTCHA_MARKERS)


def detect_sales_prohibited(page_text: str) -> str | None:
    """営業お断り文言を検出したらその文言を返す。"""
    normalized = " ".join(page_text.split())
    for phrase in SALES_PROHIBITED_PHRASES:
        if phrase in normalized:
            return phrase
    return None


def parse_form_page(html: str) -> list[ParsedForm]:
    """ページ内の送信フォームを解析する(検索ボックス等の小さなフォームは除外)。"""
    soup = BeautifulSoup(html, "lxml")
    page_text = soup.get_text(" ", strip=True)
    has_captcha = detect_captcha(html)
    prohibited_phrase = detect_sales_prohibited(page_text)

    parsed: list[ParsedForm] = []
    for form in soup.find_all("form"):
        fields: list[FormField] = []
        for element in form.find_all(["input", "textarea", "select"]):
            input_type = element.get("type", "text").lower() if element.name == "input" else None
            if input_type in ("submit", "button", "image", "reset"):
                continue

            label = _label_text(soup, element)
            placeholder = element.get("placeholder")
            name = element.get("name")
            field_id = element.get("id")

            role = None
            if input_type != "hidden":
                role = _guess_role(input_type, name, field_id, placeholder, label)
                if element.name == "textarea" and role is None:
                    role = "body"  # 問い合わせフォームのtextareaはほぼ本文欄

            options: list[str] = []
            if element.name == "select":
                options = [o.get_text(strip=True) for o in element.find_all("option")]

            fields.append(
                FormField(
                    tag=element.name,
                    input_type=input_type,
                    name=name,
                    field_id=field_id,
                    label=label,
                    placeholder=placeholder,
                    required=element.has_attr("required"),
                    role=role,
                    options=options,
                )
            )

        visible = [f for f in fields if f.input_type != "hidden"]
        # 本文欄(textarea)かメール欄がないフォームは問い合わせフォームとみなさない
        is_contact_form = any(f.tag == "textarea" for f in visible) or any(
            f.role == "email" for f in visible
        )
        if not is_contact_form:
            continue

        parsed.append(
            ParsedForm(
                action=form.get("action"),
                method=(form.get("method") or "get").lower(),
                fields=fields,
                has_captcha=has_captcha,
                sales_prohibited=prohibited_phrase is not None,
                prohibited_phrase=prohibited_phrase,
            )
        )
    return parsed
