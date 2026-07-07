from pathlib import Path
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from services import resource_services as resource_service


BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=BASE_DIR / "templates")
router = APIRouter()


class HeartbeatRequest(BaseModel):
    device_id: str
    camera_ready: bool = True
    sent_at: str | None = None


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/api/device/status")
def device_status():
    return resource_service.get_device_status()


@router.post("/api/device/heartbeat")
def device_heartbeat(payload: HeartbeatRequest):
    return resource_service.register_heartbeat(payload.model_dump())


@router.get("/api/dashboard/current")
def current_dashboard():
    return resource_service.get_dashboard()


@router.post("/api/session/reset")
def reset_session():
    return resource_service.reset_session()

@router.post("/api/capture")
async def upload_capture(phase: str = Form(...), file: UploadFile = File(...)):
    return await resource_service.process_capture_upload(file, phase)

@router.get("/health")
def health():
    return {"status": "ok"}

