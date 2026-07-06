"""キャンペーンの下書き生成と、承認済みタスクの順次送信。

レート制御:
- 送信間隔: campaign.interval_seconds(最低10秒に切り上げ)
- 日次上限: campaign.daily_limit(SendLog の当日成功数で判定)
- 同一企業への重複送信禁止(過去に成功ログがあればスキップ)
- NGリストのドメインはスキップ
"""
import asyncio
from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Campaign,
    Company,
    CompanyStatus,
    ContactForm,
    NgEntry,
    SendLog,
    SendResult,
    SendTask,
    SendTaskStatus,
    SenderProfile,
)
from app.services.sender.engine import send_via_form
from app.services.sender.render import render_template, template_vars

MIN_INTERVAL_SECONDS = 10

# 多重実行防止(プロセス内)
_run_lock = asyncio.Lock()


def generate_drafts(db: Session, campaign: Campaign) -> tuple[int, list[str]]:
    """READY企業を対象に下書きを生成する。(生成数, スキップ理由リスト) を返す。"""
    warnings: list[str] = []
    ng_domains = set(db.scalars(select(NgEntry.domain)))
    sent_company_ids = set(
        db.scalars(select(SendLog.company_id).where(SendLog.result == SendResult.SUCCESS))
    )
    existing_task_company_ids = set(
        db.scalars(select(SendTask.company_id).where(SendTask.campaign_id == campaign.id))
    )

    companies = db.scalars(
        select(Company).where(Company.status == CompanyStatus.READY)
    ).all()

    created = 0
    for company in companies:
        if company.id in existing_task_company_ids:
            continue
        if company.id in sent_company_ids:
            warnings.append(f"{company.name}: 送信済みのためスキップ")
            continue
        if company.domain and company.domain in ng_domains:
            warnings.append(f"{company.name}: NGリストのためスキップ")
            continue
        form = next(
            (f for f in company.forms if not f.sales_prohibited and f.field_mapping),
            None,
        )
        if form is None:
            warnings.append(f"{company.name}: 利用可能なフォームがありません")
            continue

        variables = template_vars(company)
        body, unknown_b = render_template(campaign.template.body, variables)
        subject, unknown_s = render_template(campaign.template.subject or "", variables)
        for var in set(unknown_b + unknown_s):
            warnings.append(f"{company.name}: 未定義の変数 {{{{{var}}}}} を空欄にしました")

        db.add(
            SendTask(
                campaign_id=campaign.id,
                company_id=company.id,
                contact_form_id=form.id,
                rendered_subject=subject or None,
                rendered_body=body,
                status=SendTaskStatus.DRAFT,
            )
        )
        created += 1

    db.commit()
    return created, warnings


def _sent_today(db: Session) -> int:
    today_start = datetime.combine(datetime.utcnow().date(), time.min)
    return db.scalar(
        select(func.count())
        .select_from(SendLog)
        .where(SendLog.result == SendResult.SUCCESS, SendLog.sent_at >= today_start)
    ) or 0


_STATUS_TO_RESULT = {
    "sent": SendResult.SUCCESS,
    "failed": SendResult.FAILED,
    "manual": SendResult.MANUAL_QUEUE,
    "skipped": SendResult.SKIPPED,
}

_STATUS_TO_TASK_STATUS = {
    "sent": SendTaskStatus.SENT,
    "failed": SendTaskStatus.FAILED,
    "manual": SendTaskStatus.MANUAL,
    "skipped": SendTaskStatus.SKIPPED,
}


async def run_campaign(campaign_id: int, *, dry_run: bool = False) -> None:
    """承認済みタスクを順次送信する(バックグラウンド実行用)。"""
    if _run_lock.locked():
        return
    async with _run_lock:
        db = SessionLocal()
        try:
            campaign = db.get(Campaign, campaign_id)
            if campaign is None:
                return
            profile = db.scalar(select(SenderProfile)) or SenderProfile()
            interval = max(campaign.interval_seconds, MIN_INTERVAL_SECONDS)

            campaign.status = "running"
            db.commit()

            tasks = db.scalars(
                select(SendTask)
                .where(
                    SendTask.campaign_id == campaign.id,
                    SendTask.status == SendTaskStatus.APPROVED,
                )
                .order_by(SendTask.id)
            ).all()

            for i, task in enumerate(tasks):
                if not dry_run and _sent_today(db) >= campaign.daily_limit:
                    campaign.status = "daily_limit_reached"
                    db.commit()
                    return

                form: ContactForm = task.contact_form
                task.status = SendTaskStatus.SENDING
                db.commit()

                outcome = await send_via_form(
                    form.form_url,
                    form.field_mapping or {},
                    profile,
                    task.rendered_body,
                    task.rendered_subject,
                    dry_run=dry_run,
                    task_id=task.id,
                )

                if outcome.status == "dry_run":
                    task.status = SendTaskStatus.APPROVED  # dry-runは状態を消費しない
                    task.detail = outcome.detail
                    task.screenshot_path = outcome.screenshot_path
                    db.commit()
                else:
                    task.status = _STATUS_TO_TASK_STATUS[outcome.status]
                    task.detail = outcome.detail
                    task.screenshot_path = outcome.screenshot_path
                    task.sent_at = datetime.utcnow()
                    db.add(
                        SendLog(
                            campaign_id=campaign.id,
                            company_id=task.company_id,
                            result=_STATUS_TO_RESULT[outcome.status],
                            detail=outcome.detail,
                            screenshot_path=outcome.screenshot_path,
                        )
                    )
                    db.commit()

                if i < len(tasks) - 1 and not dry_run:
                    await asyncio.sleep(interval)

            campaign.status = "completed" if not dry_run else "draft"
            db.commit()
        finally:
            db.close()
