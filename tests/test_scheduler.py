"""スケジューラのジョブ登録テスト(実行はしない)。"""
from datetime import datetime, timedelta, timezone

from app.services.sender import scheduler


def test_schedule_and_unschedule(monkeypatch):
    # テスト用に新しいスケジューラインスタンスを使う
    monkeypatch.setattr(scheduler, "_scheduler", None)
    run_at = datetime.now(timezone.utc) + timedelta(hours=1)

    scheduler.schedule_campaign(42, run_at)
    job = scheduler.get_scheduler().get_job("campaign-42")
    assert job is not None
    assert job.args == (42,)

    scheduler.unschedule_campaign(42)
    assert scheduler.get_scheduler().get_job("campaign-42") is None


async def test_schedule_replaces_existing(monkeypatch):
    # 実運用ではスケジューラ起動後に登録されるため、起動状態で置き換えを検証する
    monkeypatch.setattr(scheduler, "_scheduler", None)
    sched = scheduler.get_scheduler()
    sched.start()
    try:
        run_at = datetime.now(timezone.utc) + timedelta(hours=1)
        scheduler.schedule_campaign(7, run_at)
        scheduler.schedule_campaign(7, run_at + timedelta(hours=2))  # 置き換え
        jobs = [j for j in sched.get_jobs() if j.id == "campaign-7"]
        assert len(jobs) == 1
    finally:
        sched.shutdown(wait=False)
