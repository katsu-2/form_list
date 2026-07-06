from sqlalchemy import select

from app.models import Company, CompanyStatus, NgEntry
from app.services.list_builder.csv_io import export_companies_csv, import_companies_csv

CSV = """name,url,industry
株式会社テスト,https://www.test-example.co.jp,IT
(株)テスト,https://test-example.co.jp/company,IT
別会社商事,,卸売
NG商事,https://ng-example.com,
"""


def test_import_dedupes_and_respects_ng(db):
    db.add(NgEntry(domain="ng-example.com", reason="test"))
    db.commit()

    result = import_companies_csv(db, CSV)

    assert result.imported == 2  # テスト(1件目)と別会社商事
    assert result.skipped_duplicates == 1  # 同一ドメインの(株)テスト
    assert result.skipped_ng == 1
    assert result.errors == []

    companies = db.scalars(select(Company)).all()
    assert {c.name for c in companies} == {"株式会社テスト", "別会社商事"}
    test_co = next(c for c in companies if c.name == "株式会社テスト")
    assert test_co.domain == "test-example.co.jp"
    assert test_co.status == CompanyStatus.NEW


def test_import_missing_name_column(db):
    result = import_companies_csv(db, "url\nhttps://example.com\n")
    assert result.imported == 0
    assert result.errors


def test_import_bom_and_empty_name(db):
    content = "﻿name,url\n,https://example.com\nA社,https://a-sha.example\n".encode()
    result = import_companies_csv(db, content)
    assert result.imported == 1
    assert len(result.errors) == 1


def test_export_roundtrip(db):
    # このテストではNGリスト未登録のため、重複以外の3社が取り込まれる
    import_companies_csv(db, CSV)
    csv_text = export_companies_csv(db)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("id,name")
    assert len(lines) == 4  # ヘッダ + 3社
