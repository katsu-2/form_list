from fastapi import FastAPI

from app.db import init_db
from app.routers import campaigns, companies, dashboard, settings, templates_admin

app = FastAPI(title="フォーム営業ツール")

app.include_router(companies.router)
app.include_router(templates_admin.router)
app.include_router(campaigns.router)
app.include_router(settings.router)
app.include_router(dashboard.router)


@app.on_event("startup")
def startup() -> None:
    init_db()
