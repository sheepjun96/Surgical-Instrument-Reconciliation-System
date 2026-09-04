from pathlib import Path
from fastapi import APIRouter, Request, UploadFile, File, Form, Depends, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
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

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: bytes):
        for connection in self.active_connections:
            try:
                await connection.send_bytes(message)
            except Exception:
                pass

manager = ConnectionManager()

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

@router.get("/api/dashboard/current")
def current_dashboard(db: Session = Depends(get_db)):
    return resource_service.get_dashboard(db)

@router.get("/api/dashboard/{session_id}")
def get_specific_dashboard(session_id: int, db: Session = Depends(get_db)):
    return resource_service.get_dashboard(db, session_id)

@router.get("/api/sessions")
def get_sessions_list(db: Session = Depends(get_db)):
    return resource_service.get_all_sessions(db)

@router.post("/api/session/{session_id}/delete")
def delete_session_endpoint(session_id: int, db: Session = Depends(get_db)):
    return resource_service.delete_and_reorder_session(session_id, db)

@router.post("/api/session/reset")
def reset_session(db: Session = Depends(get_db)):
    return resource_service.reset_session(db)

@router.post("/api/capture")
async def upload_capture(
    phase: str = Form(...), 
    file: UploadFile = File(...), 
    bg_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db)
    ):
    return await resource_service.process_capture_upload(file, phase, db, bg_tasks)

@router.get("/health")
def health():
    return {"status": "ok"}

@router.websocket("/ws/stream/push")
async def websocket_push(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_bytes()
            await manager.broadcast(data)
    except WebSocketDisconnect:
        pass

# 브라우저가 영상을 받아보는 곳
@router.websocket("/ws/stream/view")
async def websocket_view(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 브라우저 연결 유지용 더미 데이터 수신
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)