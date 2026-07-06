from app.models import SenderProfile
from app.services.sender.values import (
    choose_select_option,
    missing_profile_fields,
    resolve_field_value,
)


def make_profile() -> SenderProfile:
    return SenderProfile(
        company_name="自社株式会社",
        person_name="山田太郎",
        email="taro@example.com",
        phone="03-0000-0000",
    )


def test_resolve_profile_roles():
    profile = make_profile()
    assert resolve_field_value("company_name", profile, "body", None) == "自社株式会社"
    assert resolve_field_value("email", profile, "body", None) == "taro@example.com"
    assert resolve_field_value("email_confirm", profile, "body", None) == "taro@example.com"


def test_resolve_body_subject_agree():
    profile = make_profile()
    assert resolve_field_value("body", profile, "本文です", "件名") == "本文です"
    assert resolve_field_value("subject", profile, "本文です", "件名") == "件名"
    assert resolve_field_value("privacy_agree", profile, "b", None) is True


def test_resolve_empty_profile_field_returns_none():
    profile = make_profile()
    assert resolve_field_value("address", profile, "b", None) is None


def test_choose_select_option():
    assert choose_select_option(["選択してください", "製品について", "その他"]) == "その他"
    assert choose_select_option(["--- select ---", "A", "B"]) == "B"
    assert choose_select_option(["選択してください"]) is None


def test_missing_profile_fields():
    profile = make_profile()
    mapping = {"company_name": "c", "address": "a", "body": "m"}
    assert missing_profile_fields(profile, mapping) == ["address"]
