from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from router.resource_router import router

BASE_DIR = Path(__file__).resolve().parent

UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Surgical Tool Monitor", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/data/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

app.include_router(router)

