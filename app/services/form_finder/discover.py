"""フォーム探索の実行とDBへの反映。"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanyStatus, ContactForm
from app.services.form_finder.finder import find_contact_form


def discover_form_for_company(db: Session, company: Company) -> ContactForm | None:
    """企業のサイトからフォームを探索し、結果を companies / contact_forms に保存する。"""
    if not company.site_url:
        company.status = CompanyStatus.FORM_NOT_FOUND
        db.commit()
        return None

    result = find_contact_form(company.site_url)
    if not result.found:
        company.status = CompanyStatus.FORM_NOT_FOUND
        db.commit()
        return None

    form = result.forms[0]
    contact_form = db.scalar(
        select(ContactForm).where(
            ContactForm.company_id == company.id,
            ContactForm.form_url == result.form_url,
        )
    )
    if contact_form is None:
        contact_form = ContactForm(company_id=company.id, form_url=result.form_url)
        db.add(contact_form)

    contact_form.field_mapping = form.field_mapping
    contact_form.unmapped_fields = form.unmapped_required_fields
    contact_form.has_captcha = form.has_captcha
    contact_form.sales_prohibited = form.sales_prohibited
    contact_form.last_verified_at = datetime.utcnow()

    if form.sales_prohibited:
        company.status = CompanyStatus.EXCLUDED
    elif form.field_mapping.get("body") and not form.unmapped_required_fields:
        company.status = CompanyStatus.READY
    else:
        company.status = CompanyStatus.FORM_FOUND

    db.commit()
    return contact_form
