from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MessageTemplate

router = APIRouter(prefix="/templates")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def list_templates(request: Request, db: Session = Depends(get_db)):
    items = db.scalars(select(MessageTemplate).order_by(MessageTemplate.id.desc())).all()
    return templates.TemplateResponse(
        request, "templates.html",
        {"items": items, "flash": request.query_params.get("flash", "")},
    )


@router.get("/new", response_class=HTMLResponse)
def new_template(request: Request):
    return templates.TemplateResponse(request, "template_edit.html", {"item": None})


@router.get("/{template_id}", response_class=HTMLResponse)
def edit_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(MessageTemplate, template_id)
    if item is None:
        return RedirectResponse(url="/templates/?flash=テンプレートが見つかりません", status_code=303)
    return templates.TemplateResponse(request, "template_edit.html", {"item": item})


@router.post("/save")
def save_template(
    template_id: int | None = Form(None),
    name: str = Form(...),
    subject: str = Form(""),
    body: str = Form(...),
    db: Session = Depends(get_db),
):
    if template_id:
        item = db.get(MessageTemplate, template_id)
        if item is None:
            return RedirectResponse(url="/templates/?flash=テンプレートが見つかりません", status_code=303)
        item.name, item.subject, item.body = name, subject or None, body
    else:
        db.add(MessageTemplate(name=name, subject=subject or None, body=body))
    db.commit()
    return RedirectResponse(url="/templates/?flash=保存しました", status_code=303)
