from collections import Counter

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Campaign, CompanyStatus, Company, SendLog, SendResult

router = APIRouter(prefix="/dashboard")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    # 全体の送信結果内訳
    result_counts = dict(
        db.execute(select(SendLog.result, func.count()).group_by(SendLog.result)).all()
    )
    total_logs = sum(result_counts.values())
    success = result_counts.get(SendResult.SUCCESS, 0)
    success_rate = (success / total_logs * 100) if total_logs else 0.0

    # スキップ・手動対応・失敗の理由内訳(detail の先頭で分類)
    reason_counter: Counter[str] = Counter()
    non_success = db.scalars(
        select(SendLog).where(SendLog.result != SendResult.SUCCESS)
    ).all()
    for log in non_success:
        reason_counter[_reason_bucket(log.detail)] += 1

    # 企業ステータス内訳(リスト作成の進捗)
    company_status = dict(
        db.execute(select(Company.status, func.count()).group_by(Company.status)).all()
    )

    # キャンペーン別サマリ
    campaign_rows = []
    for campaign in db.scalars(select(Campaign).order_by(Campaign.id.desc())).all():
        counts = dict(
            db.execute(
                select(SendLog.result, func.count())
                .where(SendLog.campaign_id == campaign.id)
                .group_by(SendLog.result)
            ).all()
        )
        sent = sum(counts.values())
        ok = counts.get(SendResult.SUCCESS, 0)
        campaign_rows.append(
            {
                "campaign": campaign,
                "total": sent,
                "success": ok,
                "rate": (ok / sent * 100) if sent else 0.0,
                "manual": counts.get(SendResult.MANUAL_QUEUE, 0),
                "failed": counts.get(SendResult.FAILED, 0),
                "skipped": counts.get(SendResult.SKIPPED, 0),
            }
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "total_logs": total_logs,
            "success": success,
            "success_rate": success_rate,
            "result_counts": {r.value: c for r, c in result_counts.items()},
            "reasons": reason_counter.most_common(),
            "company_status": {s.value: c for s, c in company_status.items()},
            "statuses": list(CompanyStatus),
            "campaign_rows": campaign_rows,
        },
    )


def _reason_bucket(detail: str | None) -> str:
    """失敗・スキップ理由をおおまかに分類する。"""
    if not detail:
        return "その他"
    for keyword, label in [
        ("CAPTCHA", "CAPTCHA"),
        ("営業", "営業お断り"),
        ("本文", "本文欄なし"),
        ("送信ボタン", "送信ボタンなし"),
        ("タイムアウト", "タイムアウト"),
        ("完了文言", "完了未確認"),
        ("却下", "手動却下"),
    ]:
        if keyword in detail:
            return label
    return "その他"
