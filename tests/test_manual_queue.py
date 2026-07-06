"""手動対応キューの状態遷移テスト。"""
from app.models import (
    Campaign,
    Company,
    CompanyStatus,
    ContactForm,
    MessageTemplate,
    SendLog,
    SendResult,
    SendTask,
    SendTaskStatus,
)
from app.routers.manual_queue import mark_done, mark_skip


def _setup_manual_task(db):
    company = Company(name="テスト社", status=CompanyStatus.READY)
    db.add(company)
    db.flush()
    form = ContactForm(company_id=company.id, form_url="http://example/contact", field_mapping={})
    template = MessageTemplate(name="t", body="body")
    db.add_all([form, template])
    db.flush()
    campaign = Campaign(name="c", template_id=template.id)
    db.add(campaign)
    db.flush()
    task = SendTask(
        campaign_id=campaign.id,
        company_id=company.id,
        contact_form_id=form.id,
        rendered_body="body",
        status=SendTaskStatus.MANUAL,
        detail="CAPTCHA検出",
    )
    db.add(task)
    db.commit()
    return task


def test_mark_done_records_success(db):
    task = _setup_manual_task(db)
    mark_done(task.id, db=db)
    db.refresh(task)
    assert task.status == SendTaskStatus.SENT
    log = db.query(SendLog).one()
    assert log.result == SendResult.SUCCESS


def test_mark_skip_records_skip(db):
    task = _setup_manual_task(db)
    mark_skip(task.id, db=db)
    db.refresh(task)
    assert task.status == SendTaskStatus.SKIPPED
    log = db.query(SendLog).one()
    assert log.result == SendResult.SKIPPED


def test_mark_done_ignores_non_manual(db):
    task = _setup_manual_task(db)
    task.status = SendTaskStatus.SENT
    db.commit()
    mark_done(task.id, db=db)
    # 既にSENTのタスクにログは追加されない
    assert db.query(SendLog).count() == 0
