from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Campaign,
    MessageTemplate,
    SendLog,
    SendTask,
    SendTaskStatus,
    SenderProfile,
)
from app.services.sender.runner import generate_drafts, run_campaign
from app.services.sender.scheduler import schedule_campaign, unschedule_campaign
from app.services.sender.values import missing_profile_fields

router = APIRouter(prefix="/campaigns")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def list_campaigns(request: Request, db: Session = Depends(get_db)):
    items = db.scalars(select(Campaign).order_by(Campaign.id.desc())).all()
    template_items = db.scalars(select(MessageTemplate).order_by(MessageTemplate.id.desc())).all()
    return templates.TemplateResponse(
        request, "campaigns.html",
        {
            "items": items,
            "template_items": template_items,
            "flash": request.query_params.get("flash", ""),
        },
    )


@router.post("/create")
def create_campaign(
    name: str = Form(...),
    template_id: int = Form(...),
    interval_seconds: int = Form(30),
    daily_limit: int = Form(100),
    db: Session = Depends(get_db),
):
    if db.get(MessageTemplate, template_id) is None:
        return RedirectResponse(url="/campaigns/?flash=テンプレートが見つかりません", status_code=303)
    campaign = Campaign(
        name=name,
        template_id=template_id,
        interval_seconds=max(interval_seconds, 10),
        daily_limit=max(daily_limit, 1),
    )
    db.add(campaign)
    db.commit()
    created, warnings = generate_drafts(db, campaign)
    flash = f"キャンペーンを作成し、下書きを{created}件生成しました"
    if warnings:
        flash += f"(スキップ{len(warnings)}件)"
    return RedirectResponse(url=f"/campaigns/{campaign.id}?flash={flash}", status_code=303)


@router.get("/{campaign_id}", response_class=HTMLResponse)
def campaign_detail(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return RedirectResponse(url="/campaigns/?flash=キャンペーンが見つかりません", status_code=303)
    tasks = db.scalars(
        select(SendTask).where(SendTask.campaign_id == campaign_id).order_by(SendTask.id)
    ).all()
    logs = db.scalars(
        select(SendLog).where(SendLog.campaign_id == campaign_id).order_by(SendLog.id.desc()).limit(100)
    ).all()

    # 差出人情報の不足チェック(承認前に気づけるように表示)
    profile = db.scalar(select(SenderProfile)) or SenderProfile()
    profile_warnings = set()
    for t in tasks:
        if t.contact_form.field_mapping:
            profile_warnings.update(
                missing_profile_fields(profile, t.contact_form.field_mapping)
            )

    counts = {s: sum(1 for t in tasks if t.status == s) for s in SendTaskStatus}
    return templates.TemplateResponse(
        request, "campaign_detail.html",
        {
            "campaign": campaign,
            "tasks": tasks,
            "logs": logs,
            "counts": counts,
            "statuses": SendTaskStatus,
            "profile_warnings": sorted(profile_warnings),
            "flash": request.query_params.get("flash", ""),
        },
    )


@router.post("/{campaign_id}/tasks/{task_id}/approve")
def approve_task(campaign_id: int, task_id: int, db: Session = Depends(get_db)):
    task = db.get(SendTask, task_id)
    if task and task.status == SendTaskStatus.DRAFT:
        task.status = SendTaskStatus.APPROVED
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.post("/{campaign_id}/tasks/{task_id}/reject")
def reject_task(campaign_id: int, task_id: int, db: Session = Depends(get_db)):
    task = db.get(SendTask, task_id)
    if task and task.status in (SendTaskStatus.DRAFT, SendTaskStatus.APPROVED):
        task.status = SendTaskStatus.SKIPPED
        task.detail = "手動で却下"
        db.commit()
    return RedirectResponse(url=f"/campaigns/{campaign_id}", status_code=303)


@router.post("/{campaign_id}/approve-all")
def approve_all(campaign_id: int, db: Session = Depends(get_db)):
    tasks = db.scalars(
        select(SendTask).where(
            SendTask.campaign_id == campaign_id, SendTask.status == SendTaskStatus.DRAFT
        )
    ).all()
    for t in tasks:
        t.status = SendTaskStatus.APPROVED
    db.commit()
    return RedirectResponse(
        url=f"/campaigns/{campaign_id}?flash={len(tasks)}件を承認しました", status_code=303
    )


@router.post("/{campaign_id}/run")
def run(
    campaign_id: int,
    background_tasks: BackgroundTasks,
    dry_run: str = Form(""),
    db: Session = Depends(get_db),
):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return RedirectResponse(url="/campaigns/?flash=キャンペーンが見つかりません", status_code=303)
    is_dry = dry_run == "1"
    background_tasks.add_task(run_campaign, campaign_id, dry_run=is_dry)
    flash = "dry-run(入力のみ・送信なし)を開始しました" if is_dry else "送信を開始しました"
    return RedirectResponse(url=f"/campaigns/{campaign_id}?flash={flash}", status_code=303)


@router.post("/{campaign_id}/schedule")
def schedule(
    campaign_id: int,
    run_at: str = Form(...),  # datetime-local の値(ローカル時刻)
    db: Session = Depends(get_db),
):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return RedirectResponse(url="/campaigns/?flash=キャンペーンが見つかりません", status_code=303)
    try:
        # datetime-local はタイムゾーンなし。ここではUTCとして解釈する
        run_dt = datetime.fromisoformat(run_at).replace(tzinfo=timezone.utc)
    except ValueError:
        return RedirectResponse(
            url=f"/campaigns/{campaign_id}?flash=日時の形式が不正です", status_code=303
        )
    if run_dt <= datetime.now(timezone.utc):
        return RedirectResponse(
            url=f"/campaigns/{campaign_id}?flash=未来の日時を指定してください", status_code=303
        )

    campaign.scheduled_at = run_dt.replace(tzinfo=None)
    campaign.status = "scheduled"
    db.commit()
    schedule_campaign(campaign_id, run_dt)
    return RedirectResponse(
        url=f"/campaigns/{campaign_id}?flash={run_at} (UTC) に自動実行を予約しました",
        status_code=303,
    )


@router.post("/{campaign_id}/unschedule")
def unschedule(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return RedirectResponse(url="/campaigns/?flash=キャンペーンが見つかりません", status_code=303)
    campaign.scheduled_at = None
    if campaign.status == "scheduled":
        campaign.status = "draft"
    db.commit()
    unschedule_campaign(campaign_id)
    return RedirectResponse(
        url=f"/campaigns/{campaign_id}?flash=予約を解除しました", status_code=303
    )
