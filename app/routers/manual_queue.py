"""手動対応キュー: CAPTCHA等で自動送信できず止まったタスクを人が処理する画面。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import SendLog, SendResult, SendTask, SendTaskStatus

router = APIRouter(prefix="/manual")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def manual_queue(request: Request, db: Session = Depends(get_db)):
    tasks = db.scalars(
        select(SendTask)
        .where(SendTask.status == SendTaskStatus.MANUAL)
        .order_by(SendTask.id)
    ).all()
    return templates.TemplateResponse(
        request,
        "manual_queue.html",
        {"tasks": tasks, "flash": request.query_params.get("flash", "")},
    )


@router.post("/{task_id}/done")
def mark_done(task_id: int, db: Session = Depends(get_db)):
    """人が手動で送信を完了した場合。成功として記録する。"""
    task = db.get(SendTask, task_id)
    if task and task.status == SendTaskStatus.MANUAL:
        task.status = SendTaskStatus.SENT
        task.detail = "手動で送信完了"
        task.sent_at = datetime.utcnow()
        db.add(
            SendLog(
                campaign_id=task.campaign_id,
                company_id=task.company_id,
                result=SendResult.SUCCESS,
                detail="手動で送信完了",
            )
        )
        db.commit()
    return RedirectResponse(url="/manual/?flash=送信完了として記録しました", status_code=303)


@router.post("/{task_id}/skip")
def mark_skip(task_id: int, db: Session = Depends(get_db)):
    """手動対応せずスキップする場合。"""
    task = db.get(SendTask, task_id)
    if task and task.status == SendTaskStatus.MANUAL:
        task.status = SendTaskStatus.SKIPPED
        task.detail = "手動対応をスキップ"
        db.add(
            SendLog(
                campaign_id=task.campaign_id,
                company_id=task.company_id,
                result=SendResult.SKIPPED,
                detail="手動対応をスキップ",
            )
        )
        db.commit()
    return RedirectResponse(url="/manual/?flash=スキップしました", status_code=303)
