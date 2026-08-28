from pathlib import Path
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services import resource_services as resource_service

BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=BASE_DIR / "templates")
router = APIRouter()

class HeartbeatRequest(BaseModel):
    device_id: str
    camera_ready: bool = True
    sent_at: str | None = None

@router.get("/")
def root_redirect(db: Session = Depends(get_db)):
    session_obj = resource_service.get_or_create_latest_session(db)
    return RedirectResponse(url=f"/{session_obj.id}")

@router.get("/{session_id:int}", response_class=HTMLResponse)
def dashboard_page(request: Request, session_id: int):
    return templates.TemplateResponse(request=request, name="index.html")

@router.get("/api/device/status")
def device_status():
    return resource_service.get_device_status()

@router.post("/api/device/heartbeat")
def device_heartbeat(payload: HeartbeatRequest, db: Session = Depends(get_db)):
    return resource_service.register_heartbeat(payload.model_dump(), db)

# 현재(가장 최신) 세션 데이터 요청
@router.get("/api/dashboard/current")
def current_dashboard(db: Session = Depends(get_db)):
    return resource_service.get_dashboard(db)

# 특정 과거 세션 데이터 요청
@router.get("/api/dashboard/{session_id}")
def get_specific_dashboard(session_id: int, db: Session = Depends(get_db)):
    return resource_service.get_dashboard(db, session_id)

@router.post("/api/session/reset")
def reset_session(db: Session = Depends(get_db)):
    return resource_service.reset_session(db)

@router.post("/api/capture")
async def upload_capture(phase: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    return await resource_service.process_capture_upload(file, phase, db)

@router.get("/health")
def health():
    return {"status": "ok"}

@router.post("/api/stream/push")
async def push_stream(file: UploadFile = File(...)):
    contents = await file.read()
    resource_service.update_stream_frame(contents)
    return {"ok": True}

@router.get("/api/stream")
def get_stream():
    return StreamingResponse(
        resource_service.generate_mjpeg_stream(), 
        media_type="multipart/x-mixed-replace; boundary=frame"
    )