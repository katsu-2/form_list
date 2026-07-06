import httpx
import pytest

from app.models import Company
from app.services.list_builder.csv_io import import_houjin_companies
from app.services.list_builder.houjin_api import HoujinCompany, _parse_csv, fetch_by_name

# 法人番号APIのCSV(type=12)を模した1行(必要な列だけ埋める)
SAMPLE_ROW = (
    "1,1234567890123,01,00,2020-01-01,2020-01-01,"
    "株式会社サンプル,,301,東京都,千代田区,丸の内1-1-1,,13,13101,1000000\n"
    "2,9876543210987,01,00,2020-01-01,2020-01-01,"
    "テスト工業株式会社,,301,大阪府,大阪市北区,梅田2-2-2,,27,27127,5300001\n"
)


def test_parse_csv():
    companies = _parse_csv(SAMPLE_ROW)
    assert len(companies) == 2
    assert companies[0].corporate_number == "1234567890123"
    assert companies[0].name == "株式会社サンプル"
    assert companies[0].address == "東京都千代田区丸の内1-1-1"
    assert companies[1].name == "テスト工業株式会社"


def test_parse_csv_skips_short_rows():
    assert _parse_csv("1,2,3\n") == []


def test_fetch_by_name_requires_app_id(monkeypatch):
    monkeypatch.delenv("HOUJIN_API_APP_ID", raising=False)
    result = fetch_by_name("サンプル")
    assert result.companies == []
    assert result.error is not None
    assert "HOUJIN_API_APP_ID" in result.error


def test_fetch_by_name_with_mock(monkeypatch):
    monkeypatch.setenv("HOUJIN_API_APP_ID", "test-id")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["name"] == "サンプル"
        assert request.url.params["id"] == "test-id"
        return httpx.Response(200, content=SAMPLE_ROW.encode("shift_jis"))

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        result = fetch_by_name("サンプル", client=client)
    assert result.error is None
    assert len(result.companies) == 2


def test_fetch_by_name_http_error(monkeypatch):
    monkeypatch.setenv("HOUJIN_API_APP_ID", "test-id")
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    with httpx.Client(transport=transport) as client:
        result = fetch_by_name("x", client=client)
    assert result.companies == []
    assert "500" in result.error


def test_import_houjin_dedupes(db):
    companies = [
        HoujinCompany("1234567890123", "株式会社サンプル", "東京都千代田区"),
        HoujinCompany("1234567890123", "(株)サンプル", "東京都千代田区"),  # 社名キー重複
        HoujinCompany("9876543210987", "別会社工業", "大阪府"),
    ]
    result = import_houjin_companies(db, companies)
    assert result.imported == 2
    assert result.skipped_duplicates == 1
    names = {c.name for c in db.query(Company).all()}
    assert names == {"株式会社サンプル", "別会社工業"}
