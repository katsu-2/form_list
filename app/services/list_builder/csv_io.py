"""企業リストのCSVインポート/エクスポート。

インポートCSVの想定カラム(ヘッダ行必須、順不同、余分な列は無視):
    name(必須), url, corporate_number, industry, address
"""
import csv
import io
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanyStatus, NgEntry
from app.services.list_builder.normalize import (
    company_name_key,
    extract_domain,
    normalize_company_name,
    normalize_site_url,
)

IMPORT_COLUMNS = {"name", "url", "corporate_number", "industry", "address"}

EXPORT_COLUMNS = [
    "id",
    "name",
    "corporate_number",
    "domain",
    "site_url",
    "industry",
    "address",
    "source",
    "status",
]


@dataclass
class ImportResult:
    imported: int = 0
    skipped_duplicates: int = 0
    skipped_ng: int = 0
    errors: list[str] = field(default_factory=list)


def import_companies_csv(db: Session, content: bytes | str, source: str = "csv") -> ImportResult:
    """CSVを取り込み、正規化・重複排除・NGリスト照合を行って companies に保存する。"""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")  # ExcelのBOM付きUTF-8に対応
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None or "name" not in reader.fieldnames:
        return ImportResult(errors=["ヘッダ行に name 列がありません"])

    result = ImportResult()

    ng_domains = set(db.scalars(select(NgEntry.domain)))
    existing_domains = set(db.scalars(select(Company.domain).where(Company.domain.is_not(None))))
    existing_name_keys = {company_name_key(n) for n in db.scalars(select(Company.name))}

    for line_no, row in enumerate(reader, start=2):
        raw_name = (row.get("name") or "").strip()
        if not raw_name:
            result.errors.append(f"{line_no}行目: name が空のためスキップ")
            continue

        name = normalize_company_name(raw_name)
        url = (row.get("url") or "").strip()
        domain = extract_domain(url) if url else None
        site_url = normalize_site_url(url) if url else None

        if domain and domain in ng_domains:
            result.skipped_ng += 1
            continue

        # 重複判定: ドメインがあればドメインで、なければ社名キーで判定
        name_key = company_name_key(name)
        if domain:
            if domain in existing_domains:
                result.skipped_duplicates += 1
                continue
            existing_domains.add(domain)
        elif name_key in existing_name_keys:
            result.skipped_duplicates += 1
            continue
        existing_name_keys.add(name_key)

        db.add(
            Company(
                name=name,
                corporate_number=(row.get("corporate_number") or "").strip() or None,
                domain=domain,
                site_url=site_url,
                industry=(row.get("industry") or "").strip() or None,
                address=(row.get("address") or "").strip() or None,
                source=source,
                status=CompanyStatus.NEW,
            )
        )
        result.imported += 1

    db.commit()
    return result


def export_companies_csv(db: Session, status: CompanyStatus | None = None) -> str:
    """companies をCSV文字列にエクスポートする。"""
    query = select(Company).order_by(Company.id)
    if status is not None:
        query = query.where(Company.status == status)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for c in db.scalars(query):
        writer.writerow(
            [
                c.id,
                c.name,
                c.corporate_number or "",
                c.domain or "",
                c.site_url or "",
                c.industry or "",
                c.address or "",
                c.source or "",
                c.status.value,
            ]
        )
    return buf.getvalue()
