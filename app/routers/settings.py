from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import SenderProfile

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")

PROFILE_FIELDS = [
    ("company_name", "会社名"),
    ("person_name", "担当者名"),
    ("person_name_kana", "担当者名(カナ)"),
    ("email", "メールアドレス"),
    ("phone", "電話番号"),
    ("postal_code", "郵便番号"),
    ("address", "住所"),
    ("department", "部署"),
    ("position", "役職"),
    ("site_url", "自社サイトURL"),
]


def get_profile(db: Session) -> SenderProfile:
    profile = db.scalar(select(SenderProfile))
    if profile is None:
        profile = SenderProfile()
        db.add(profile)
        db.commit()
    return profile


@router.get("/", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "settings.html",
        {
            "profile": get_profile(db),
            "fields": PROFILE_FIELDS,
            "flash": request.query_params.get("flash", ""),
        },
    )


@router.post("/save")
async def save_settings(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    profile = get_profile(db)
    for field, _label in PROFILE_FIELDS:
        setattr(profile, field, (form.get(field) or "").strip())
    db.commit()
    return RedirectResponse(url="/settings/?flash=保存しました", status_code=303)
