"""フォームフィールドの役割(role)→ 入力値の解決。

form_parser が推定した役割ごとに、差出人情報(SenderProfile)と
送信タスクの本文・件名から実際に入力する値を決める。
"""
from app.models import SenderProfile

# SenderProfile の属性をそのまま使う役割
_PROFILE_ROLES = {
    "company_name": "company_name",
    "person_name": "person_name",
    "person_name_kana": "person_name_kana",
    "email": "email",
    "email_confirm": "email",
    "phone": "phone",
    "postal_code": "postal_code",
    "address": "address",
    "department": "department",
    "position": "position",
}


def resolve_field_value(
    role: str,
    profile: SenderProfile,
    body: str,
    subject: str | None,
) -> str | bool | None:
    """役割に対する入力値を返す。None は「入力しない」、bool はチェックボックス用。"""
    if role in _PROFILE_ROLES:
        return getattr(profile, _PROFILE_ROLES[role]) or None
    if role == "body":
        return body
    if role == "subject":
        return subject or ""
    if role == "privacy_agree":
        return True
    if role == "inquiry_type":
        return None  # select の選択は選択肢を見て決めるためエンジン側で処理
    return None


def choose_select_option(options: list[str]) -> str | None:
    """select の選択肢から妥当なものを選ぶ(「その他」優先、プレースホルダは除外)。"""
    cleaned = [o for o in options if o and not _is_placeholder(o)]
    if not cleaned:
        return None
    for o in cleaned:
        if "その他" in o or o.lower() == "other":
            return o
    return cleaned[-1]


def _is_placeholder(option: str) -> bool:
    lowered = option.lower()
    return any(kw in lowered for kw in ["選択", "select", "choose", "---", "please"])


def missing_profile_fields(profile: SenderProfile, mapping: dict[str, str]) -> list[str]:
    """フォームが要求する役割のうち、差出人情報が未入力のものを返す。"""
    missing = []
    for role in mapping:
        attr = _PROFILE_ROLES.get(role)
        if attr and not getattr(profile, attr):
            missing.append(role)
    return missing
