from fastapi import FastAPI

from app.db import init_db
from app.routers import (
    campaigns,
    companies,
    dashboard,
    manual_queue,
    settings,
    templates_admin,
)
from app.services.sender.scheduler import start_scheduler

app = FastAPI(title="フォーム営業ツール")

app.include_router(companies.router)
app.include_router(templates_admin.router)
app.include_router(campaigns.router)
app.include_router(settings.router)
app.include_router(dashboard.router)
app.include_router(manual_queue.router)


@app.on_event("startup")
def startup() -> None:
    init_db()
    start_scheduler()
