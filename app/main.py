from fastapi import FastAPI

from app.db import init_db
from app.routers import companies

app = FastAPI(title="フォーム営業ツール")

app.include_router(companies.router)


@app.on_event("startup")
def startup() -> None:
    init_db()
