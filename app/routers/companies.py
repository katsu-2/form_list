from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, CompanyStatus, NgEntry
from app.services.form_finder.discover import discover_form_for_company
from app.services.list_builder.csv_io import (
    export_companies_csv,
    import_companies_csv,
    import_houjin_companies,
)
from app.services.list_builder.houjin_api import fetch_by_name
from app.services.list_builder.normalize import extract_domain

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def list_companies(
    request: Request,
    q: str = "",
    status: str = "",
    db: Session = Depends(get_db),
):
    query = select(Company).order_by(Company.id.desc())
    if q:
        pattern = f"%{q}%"
        query = query.where(
            or_(Company.name.like(pattern), Company.domain.like(pattern))
        )
    if status:
        query = query.where(Company.status == CompanyStatus(status))

    companies = db.scalars(query.limit(500)).all()
    status_counts = dict(
        db.execute(select(Company.status, func.count()).group_by(Company.status)).all()
    )
    return templates.TemplateResponse(
        request,
        "companies.html",
        {
            "companies": companies,
            "q": q,
            "status": status,
            "statuses": list(CompanyStatus),
            "status_counts": status_counts,
            "total": sum(status_counts.values()),
            "flash": request.query_params.get("flash", ""),
        },
    )


@router.post("/companies/import")
async def import_csv(file: UploadFile, db: Session = Depends(get_db)):
    content = await file.read()
    result = import_companies_csv(db, content)
    flash = (
        f"取込 {result.imported}件 / 重複スキップ {result.skipped_duplicates}件"
        f" / NGスキップ {result.skipped_ng}件"
    )
    if result.errors:
        flash += f" / エラー {len(result.errors)}件: " + " | ".join(result.errors[:3])
    return RedirectResponse(url=f"/?flash={flash}", status_code=303)


@router.post("/companies/houjin")
def import_houjin(name: str = Form(...), db: Session = Depends(get_db)):
    result = fetch_by_name(name)
    if result.error:
        return RedirectResponse(url=f"/?flash=法人番号API: {result.error}", status_code=303)
    imported = import_houjin_companies(db, result.companies)
    flash = (
        f"法人番号APIから {imported.imported}件を取込"
        f"(検索ヒット {len(result.companies)}件 / 重複スキップ {imported.skipped_duplicates}件)"
    )
    return RedirectResponse(url=f"/?flash={flash}", status_code=303)


@router.get("/companies/export")
def export_csv(status: str = "", db: Session = Depends(get_db)):
    status_filter = CompanyStatus(status) if status else None
    csv_text = export_companies_csv(db, status=status_filter)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=companies.csv"},
    )


@router.post("/companies/{company_id}/discover")
def discover_form(company_id: int, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if company is None:
        return RedirectResponse(url="/?flash=企業が見つかりません", status_code=303)
    contact_form = discover_form_for_company(db, company)
    if contact_form is None:
        flash = f"{company.name}: フォームが見つかりませんでした"
    elif contact_form.sales_prohibited:
        flash = f"{company.name}: 営業お断り文言を検出したため除外しました"
    else:
        flash = f"{company.name}: フォームを検出 ({contact_form.form_url})"
    return RedirectResponse(url=f"/?flash={flash}", status_code=303)


@router.post("/companies/{company_id}/ng")
def add_to_ng(company_id: int, reason: str = Form(""), db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if company is None:
        return RedirectResponse(url="/?flash=企業が見つかりません", status_code=303)
    domain = company.domain or (extract_domain(company.site_url) if company.site_url else None)
    if domain:
        exists = db.scalar(select(NgEntry).where(NgEntry.domain == domain))
        if not exists:
            db.add(NgEntry(domain=domain, reason=reason or "手動登録"))
    company.status = CompanyStatus.EXCLUDED
    db.commit()
    return RedirectResponse(url=f"/?flash={company.name} をNGリストに登録しました", status_code=303)
