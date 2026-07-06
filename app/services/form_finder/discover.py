"""フォーム探索の実行とDBへの反映。"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanyStatus, ContactForm
from app.services.form_finder.finder import find_contact_form
from app.services.form_parser.llm_mapping import complete_mapping


def discover_form_for_company(
    db: Session, company: Company, *, use_llm: bool = True
) -> ContactForm | None:
    """企業のサイトからフォームを探索し、結果を companies / contact_forms に保存する。

    ルールベースで必須項目のマッピングに漏れがある場合、use_llm=True かつ Claude API が
    利用可能なら LLM で補完を試みる(利用不可なら何もせずルールベースの結果を使う)。
    """
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
    field_mapping = dict(form.field_mapping)
    unmapped_required = list(form.unmapped_required_fields)

    # 営業禁止でなく、必須項目にマッピング漏れがあるときだけ LLM 補完を試みる
    if use_llm and not form.sales_prohibited and unmapped_required:
        unmapped_by_name = {f.name: f for f in form.fields if f.role is None}
        completion = complete_mapping(list(unmapped_by_name.values()))
        for role, name in completion.items():
            field_mapping.setdefault(role, name)
        # 補完後に埋まった必須項目を未マッピングリストから除去
        filled_names = set(field_mapping.values())
        unmapped_required = [n for n in unmapped_required if n not in filled_names]

    contact_form = db.scalar(
        select(ContactForm).where(
            ContactForm.company_id == company.id,
            ContactForm.form_url == result.form_url,
        )
    )
    if contact_form is None:
        contact_form = ContactForm(company_id=company.id, form_url=result.form_url)
        db.add(contact_form)

    contact_form.field_mapping = field_mapping
    contact_form.unmapped_fields = unmapped_required
    contact_form.has_captcha = form.has_captcha
    contact_form.sales_prohibited = form.sales_prohibited
    contact_form.last_verified_at = datetime.utcnow()

    if form.sales_prohibited:
        company.status = CompanyStatus.EXCLUDED
    elif field_mapping.get("body") and not unmapped_required:
        company.status = CompanyStatus.READY
    else:
        company.status = CompanyStatus.FORM_FOUND

    db.commit()
    return contact_form
