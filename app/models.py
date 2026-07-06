import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class CompanyStatus(str, enum.Enum):
    NEW = "new"                  # 収集直後
    FORM_FOUND = "form_found"    # フォームURL特定済み
    FORM_NOT_FOUND = "form_not_found"
    READY = "ready"              # フォーム解析済み・送信可能
    EXCLUDED = "excluded"        # NG・営業禁止などで除外


class SendResult(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    MANUAL_QUEUE = "manual_queue"  # CAPTCHA等で人の対応待ち


class SendMode(str, enum.Enum):
    SEMI_AUTO = "semi_auto"  # 下書き→人が承認→送信
    AUTO = "auto"


class SendTaskStatus(str, enum.Enum):
    DRAFT = "draft"            # 下書き生成済み・承認待ち
    APPROVED = "approved"      # 承認済み・送信待ち
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    MANUAL = "manual"          # CAPTCHA等で人の対応待ち
    SKIPPED = "skipped"


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("domain", name="uq_companies_domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    corporate_number: Mapped[str | None] = mapped_column(String(13))  # 法人番号
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    site_url: Mapped[str | None] = mapped_column(String(1024))
    industry: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(512))
    source: Mapped[str | None] = mapped_column(String(64))  # csv / houjin_api / crawl
    status: Mapped[CompanyStatus] = mapped_column(
        Enum(CompanyStatus), default=CompanyStatus.NEW, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    forms: Mapped[list["ContactForm"]] = relationship(back_populates="company")


class ContactForm(Base):
    __tablename__ = "contact_forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    form_url: Mapped[str] = mapped_column(String(1024))
    field_mapping: Mapped[dict | None] = mapped_column(JSON)  # {role: field_name}
    unmapped_fields: Mapped[list | None] = mapped_column(JSON)  # マッピングできなかった項目
    has_captcha: Mapped[bool] = mapped_column(Boolean, default=False)
    sales_prohibited: Mapped[bool] = mapped_column(Boolean, default=False)  # 営業お断り文言
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)

    company: Mapped[Company] = relationship(back_populates="forms")


class MessageTemplate(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)  # {{company_name}} 等の変数を埋め込み可
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    send_mode: Mapped[SendMode] = mapped_column(Enum(SendMode), default=SendMode.SEMI_AUTO)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=30)
    daily_limit: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    template: Mapped[MessageTemplate] = relationship()


class SendLog(Base):
    __tablename__ = "send_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result: Mapped[SendResult] = mapped_column(Enum(SendResult), index=True)
    detail: Mapped[str | None] = mapped_column(Text)  # 失敗理由・スキップ理由
    screenshot_path: Mapped[str | None] = mapped_column(String(1024))

    company: Mapped[Company] = relationship()


class SenderProfile(Base):
    """フォームに入力する差出人(自社)情報。1行のみ運用する。"""

    __tablename__ = "sender_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), default="")
    person_name: Mapped[str] = mapped_column(String(255), default="")
    person_name_kana: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    postal_code: Mapped[str] = mapped_column(String(16), default="")
    address: Mapped[str] = mapped_column(String(512), default="")
    department: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[str] = mapped_column(String(255), default="")
    site_url: Mapped[str] = mapped_column(String(1024), default="")


class SendTask(Base):
    """キャンペーンから生成される送信タスク(下書き→承認→送信)。"""

    __tablename__ = "send_tasks"
    __table_args__ = (
        UniqueConstraint("campaign_id", "company_id", name="uq_send_tasks_campaign_company"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    contact_form_id: Mapped[int] = mapped_column(ForeignKey("contact_forms.id"))
    rendered_subject: Mapped[str | None] = mapped_column(String(512))
    rendered_body: Mapped[str] = mapped_column(Text)
    status: Mapped[SendTaskStatus] = mapped_column(
        Enum(SendTaskStatus), default=SendTaskStatus.DRAFT, index=True
    )
    detail: Mapped[str | None] = mapped_column(Text)  # 失敗理由・手動対応理由
    screenshot_path: Mapped[str | None] = mapped_column(String(1024))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    campaign: Mapped[Campaign] = relationship()
    company: Mapped[Company] = relationship()
    contact_form: Mapped[ContactForm] = relationship()


class NgEntry(Base):
    __tablename__ = "ng_list"
    __table_args__ = (UniqueConstraint("domain", name="uq_ng_list_domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    reason: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
