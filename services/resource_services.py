from __future__ import annotations
import json, os, cv2, time
import numpy as np
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from fastapi import UploadFile, HTTPException
from collections import Counter

from sqlalchemy.orm import Session
from database_models.db_models import SurgicalSession

# AI 모듈 Import
from services.ai_rfdetr import get_predictor as get_rfdetr_predictor
from services.ai_colsr import get_colsr_predictor

_lock = Lock()
UPLOAD_DIR = Path("data/uploads")

TOOL_MAPPING = {
    "forceps": {"name": "Forceps", "color": "#ef4444"},
    "hand_instrument": {"name": "Hand Instrument", "color": "#3b82f6"},
    "retractor": {"name": "Retractor", "color": "#a855f7"},
    "trocar": {"name": "Trocar", "color": "#22c55e"},
}

# 스트리밍용 전역 변수
_stream_frame = b""

def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")

_device = {"device_id": "tinkerboard-2s", "camera_ready": False, "last_seen_monotonic": None, "last_seen_at": None}

def hex_to_bgr(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (4, 2, 0))

def get_or_create_latest_session(db: Session):
    session_obj = db.query(SurgicalSession).order_by(SurgicalSession.id.desc()).first()
    if not session_obj:
        session_obj = SurgicalSession()
        db.add(session_obj)
        db.commit()
        db.refresh(session_obj)
    return session_obj

def get_dashboard(db: Session, session_id: int = None) -> dict:
    with _lock:
        session_obj = None
        if session_id:
            session_obj = db.query(SurgicalSession).filter(SurgicalSession.id == session_id).first()

        if not session_obj:
            session_obj = get_or_create_latest_session(db)

        return {
            "session_id": session_obj.id,
            "status": session_obj.status,
            "expected_phase": "complete" if session_obj.status == "COMPLETED" else ("before" if session_obj.status == "WAITING_BEFORE" else "after"),
            "mock_mode": False,
            "captures": {
                "before": {
                    "original_url": session_obj.before_original_url,
                    "drawn_url": session_obj.before_drawn_url,
                    "captured_at": session_obj.before_captured_at,
                } if session_obj.before_original_url else None,
                "after": {
                    "original_url": session_obj.after_original_url,
                    "drawn_url": session_obj.after_drawn_url,
                    "captured_at": session_obj.after_captured_at,
                } if session_obj.after_original_url else None,
            },
            "counts": {
                "before": session_obj.before_counts if session_obj.before_counts else {},
                "after": session_obj.after_counts if session_obj.after_counts else {},
            }
        }

async def process_capture_upload(file: UploadFile, phase: str, db: Session):
    with _lock:
        session_obj = get_or_create_latest_session(db)
        
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        h, w = img.shape[:2]
        max_dim = 1280
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        session_dir = UPLOAD_DIR / str(session_obj.id)
        session_dir.mkdir(parents=True, exist_ok=True)
        
        orig_path = session_dir / f"{phase}_original.jpg"
        cv2.imwrite(str(orig_path), img)

        rf_predictor = get_rfdetr_predictor()
        colsr_predictor = get_colsr_predictor()

        det_raw = rf_predictor.predict(str(orig_path))
        
        valid_points = []
        counts_data = {}
        drawn_img = img.copy()

        for idx, d in enumerate(det_raw):
            c_name = d.get("class_name", "unknown")
            x1, y1, x2, y2 = map(int, d["bbox"])
            
            color_hex = TOOL_MAPPING.get(c_name, {}).get("color", "#aaaaaa")
            label_text = f"{TOOL_MAPPING.get(c_name, {}).get('name', c_name)} {int(d.get('confidence', 1.0)*100)}%"
            color = hex_to_bgr(color_hex)
            
            cv2.rectangle(drawn_img, (x1, y1), (x2, y2), color, 3)
            (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            cv2.rectangle(drawn_img, (x1, y1 - th - 10), (x1 + tw, y1), color, -1)
            cv2.putText(drawn_img, label_text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            if c_name == "hand_instrument":
                crop_x1, crop_y1 = max(0, x1), max(0, y1)
                crop_x2, crop_y2 = min(w, x2), min(h, y2)
                
                crop_img = img[crop_y1:crop_y2, crop_x1:crop_x2]
                
                if crop_img.size == 0:
                    continue
                    
                crop_filename = f"{phase}_crop_hand_inst_{idx}.jpg"
                crop_path = session_dir / crop_filename
                cv2.imwrite(str(crop_path), crop_img)
                
                pt_raw = colsr_predictor.predict(str(crop_path))
                
                MIN_DIST = 10
                pt_raw_sorted = sorted(pt_raw, key=lambda x: x.get("confidence", 0.0), reverse=True)
                
                for pt in pt_raw_sorted:
                    pt_class = pt.get("class_name", "unknown")
                    abs_x = int(pt["x"]) + crop_x1
                    abs_y = int(pt["y"]) + crop_y1
                    
                    is_duplicate = False
                    for existing_pt in valid_points:
                        if existing_pt["class_name"] == pt_class:
                            dist = ((existing_pt["x"] - abs_x)**2 + (existing_pt["y"] - abs_y)**2)**0.5
                            if dist < MIN_DIST:
                                is_duplicate = True
                                break
                    
                    if not is_duplicate:
                        valid_points.append({
                            "class_name": pt_class,
                            "x": abs_x,
                            "y": abs_y,
                            "confidence": pt.get("confidence", 1.0)
                        })
                        counts_data[pt_class] = counts_data.get(pt_class, 0) + 1
            else:
                counts_data[c_name] = counts_data.get(c_name, 0) + 1

        for p in valid_points:
            p_name = p.get("class_name", "")
            p_color = hex_to_bgr(TOOL_MAPPING.get(p_name, {}).get("color", "#aaaaaa"))
            px, py = p["x"], p["y"]
            cv2.circle(drawn_img, (px, py), 8, p_color, -1)
            cv2.circle(drawn_img, (px, py), 8, (255, 255, 255), 2)
            
        drawn_path = session_dir / f"{phase}_drawn.jpg"
        cv2.imwrite(str(drawn_path), drawn_img)

        # JSON 저장은 유지
        with open(session_dir / f"{phase}_detections.json", "w", encoding="utf-8") as f:
            json.dump(det_raw, f, ensure_ascii=False, indent=2)
            
        with open(session_dir / f"{phase}_points_valid.json", "w", encoding="utf-8") as f:
            json.dump(valid_points, f, ensure_ascii=False, indent=2)

        captured_time = _iso(datetime.now(timezone.utc))

        # DB 레코드 업데이트
        if phase == "before":
            session_obj.before_original_url = f"/{orig_path.as_posix()}"
            session_obj.before_drawn_url = f"/{drawn_path.as_posix()}"
            session_obj.before_captured_at = captured_time
            session_obj.before_counts = counts_data
            session_obj.status = "COMPLETED" if session_obj.after_original_url else "WAITING_AFTER"
        elif phase == "after":
            session_obj.after_original_url = f"/{orig_path.as_posix()}"
            session_obj.after_drawn_url = f"/{drawn_path.as_posix()}"
            session_obj.after_captured_at = captured_time
            session_obj.after_counts = counts_data
            session_obj.status = "COMPLETED" if session_obj.before_original_url else "WAITING_BEFORE"

        db.commit()
        return {"ok": True, "phase": phase}

def register_heartbeat(payload: dict, db: Session) -> dict:
    with _lock:
        received_at = datetime.now(timezone.utc).astimezone()
        _device.update({
            "device_id": payload["device_id"],
            "camera_ready": payload["camera_ready"],
            "last_seen_monotonic": monotonic(),
            "last_seen_at": _iso(received_at),
        })
        session_obj = get_or_create_latest_session(db)
        
        # 디바이스에게 현재 최신 세션 상태를 응답
        expected_phase = "complete" if session_obj.status == "COMPLETED" else ("before" if session_obj.status == "WAITING_BEFORE" else "after")
        return {
            "ok": True, "server_time": _iso(received_at),
            "session_id": session_obj.id,
            "expected_phase": expected_phase,
        }

def get_device_status() -> dict:
    with _lock:
        if _device["last_seen_monotonic"] is None:
            seconds = None
            connected = False
        else:
            seconds = round(monotonic() - _device["last_seen_monotonic"], 1)
            connected = seconds <= 3 and _device["camera_ready"]

        return {
            "device_id": _device["device_id"], "connected": connected,
            "seconds_since_last_seen": seconds, "mock_mode": False,
        }

def reset_session(db: Session) -> dict:
    with _lock:
        new_session = SurgicalSession()
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        return {"ok": True, "session_id": new_session.id, "status": new_session.status}

def update_stream_frame(frame_bytes: bytes):
    global _stream_frame
    _stream_frame = frame_bytes

def generate_mjpeg_stream():
    while True:
        if _stream_frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + _stream_frame + b'\r\n')
        # 서버에서 프레임을 쏴주는 주기 (0.05초 = 최대 20fps 방어)
        time.sleep(0.05)