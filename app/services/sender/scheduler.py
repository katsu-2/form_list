"""キャンペーンのスケジュール実行(自動モード)。

APScheduler(AsyncIOScheduler)で指定時刻に run_campaign を実行する。
アプリ起動時に、未実施の予約キャンペーンをスケジューラへ再登録する。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Campaign
from app.services.sender.runner import run_campaign

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _job_id(campaign_id: int) -> str:
    return f"campaign-{campaign_id}"


async def _run_and_mark(campaign_id: int) -> None:
    logger.info("スケジュール実行を開始: campaign %s", campaign_id)
    await run_campaign(campaign_id, dry_run=False)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    """スケジューラを起動し、予約済みキャンペーンを再登録する。"""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
    _reload_scheduled_campaigns()


def schedule_campaign(campaign_id: int, run_at: datetime) -> None:
    """キャンペーンを指定時刻(UTC)に実行するよう登録する。既存の登録は置き換える。"""
    scheduler = get_scheduler()
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)
    scheduler.add_job(
        _run_and_mark,
        trigger="date",
        run_date=run_at,
        args=[campaign_id],
        id=_job_id(campaign_id),
        replace_existing=True,
        misfire_grace_time=3600,  # 起動遅延でも1時間以内なら実行
    )


def unschedule_campaign(campaign_id: int) -> None:
    scheduler = get_scheduler()
    if scheduler.get_job(_job_id(campaign_id)):
        scheduler.remove_job(_job_id(campaign_id))


def _reload_scheduled_campaigns() -> None:
    """未完了かつ未来(またはグレース内)の予約を再登録する。"""
    db = SessionLocal()
    try:
        campaigns = db.scalars(
            select(Campaign).where(
                Campaign.scheduled_at.is_not(None),
                Campaign.status.in_(["draft", "scheduled"]),
            )
        ).all()
        for campaign in campaigns:
            schedule_campaign(campaign.id, campaign.scheduled_at)
            logger.info("予約キャンペーンを再登録: %s @ %s", campaign.id, campaign.scheduled_at)
    finally:
        db.close()
