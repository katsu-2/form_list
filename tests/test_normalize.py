from app.services.list_builder.normalize import (
    company_name_key,
    extract_domain,
    normalize_company_name,
    normalize_site_url,
)


def test_normalize_company_name_zenkaku():
    assert normalize_company_name("株式会社ABC") == "株式会社ABC"
    assert normalize_company_name("  テスト  商事 ") == "テスト 商事"


def test_company_name_key_ignores_legal_form():
    assert company_name_key("株式会社テスト") == company_name_key("(株)テスト")
    assert company_name_key("株式会社テスト") == company_name_key("テスト")
    assert company_name_key("ABC Inc") == company_name_key("abc inc")


def test_company_name_key_distinguishes_different_names():
    assert company_name_key("株式会社テスト") != company_name_key("株式会社テスト工業")


def test_extract_domain():
    assert extract_domain("https://www.example.co.jp/about") == "example.co.jp"
    assert extract_domain("example.com") == "example.com"
    assert extract_domain("http://Example.COM/") == "example.com"
    assert extract_domain("") is None
    assert extract_domain("not a url") is None


def test_normalize_site_url():
    assert normalize_site_url("example.com") == "https://example.com"
    assert normalize_site_url("https://example.com/") == "https://example.com/"
    assert normalize_site_url("") is None
