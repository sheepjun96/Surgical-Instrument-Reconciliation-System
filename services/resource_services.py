from __future__ import annotations
import json, os, cv2
import numpy as np
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from fastapi import UploadFile

MOCK_MODE = os.getenv("APP_MOCK_MODE", "true").lower() == "true"
_lock = Lock()

MOCK_DIR = Path("data/mocks")
STATIC_IMG_DIR = Path("static/images")

TOOL_MAPPING = {
    "needle_holder": {"name": "Needle Holder", "color": "#ef4444"},
    "grasper": {"name": "Grasper", "color": "#3b82f6"},
    "clip_applier": {"name": "Clip Applier", "color": "#a855f7"},
    "scissors": {"name": "Scissors", "color": "#22c55e"},
    "dissector": {"name": "Dissector", "color": "#f59e0b"},
    "energy_device": {"name": "Energy Device", "color": "#ec4899"}
}

def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")

now = datetime.now(timezone.utc).astimezone()
_device = {
    "device_id": "jetson-nano-01",
    "camera_ready": True,
    "last_seen_monotonic": None,
    "last_seen_at": None,
}

_session = {
    "session_id": 1,
    "status": "WAITING_BEFORE",
    "started_at": _iso(now),
    "updated_at": _iso(now),
    "captures": {"before": None, "after": None},
    "counts": {"before": {}, "after": {}},
}

def hex_to_bgr(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (4, 2, 0))

def draw_and_resize(source_path, target_path, detections, points, max_size=1080):
    if not os.path.exists(source_path):
        return False
    
    img = cv2.imread(str(source_path))
    if img is None:
        return False

    for det in detections:
        bbox = det["bbox"]
        label = f"{det['label']} {int(det['confidence']*100)}%"
        color = hex_to_bgr(det["color"])
        
        x1, y1, x2, y2 = map(int, bbox)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
        
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1.5, 3)
        cv2.rectangle(img, (x1, y1 - th - 15), (x1 + tw + 10, y1), color, -1)
        cv2.putText(img, label, (x1 + 5, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)

    for pt in points:
        color = hex_to_bgr(pt["color"])
        cv2.circle(img, (int(pt["x"]), int(pt["y"])), 15, color, -1)
        cv2.circle(img, (int(pt["x"]), int(pt["y"])), 15, (255, 255, 255), 3)

    h, w = img.shape[:2]
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    cv2.write(str(target_path), img)
    return True

def process_upload_image(file: UploadFile, session_id: str):
    contents = file.file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    resized_img = cv2.resize(img, (500, 500))
    
    save_path = f"data/uploads/{session_id}/display.jpg"
    cv2.imwrite(save_path, resized_img)
    
    return save_path, 500, 500

def load_json_safe(filename: str) -> dict:
    filepath = MOCK_DIR / filename
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def format_detections(det_list):
    return [{
        "label": TOOL_MAPPING.get(d.get("class_name", ""), {}).get("name", d.get("class_name")),
        "color": TOOL_MAPPING.get(d.get("class_name", ""), {}).get("color", "#aaaaaa"),
        "confidence": d.get("confidence", 1.0),
        "bbox": d.get("bbox", [0, 0, 0, 0])
    } for d in det_list]

def format_points(pt_list):
    return [{
        "x": p.get("x", 0),
        "y": p.get("y", 0),
        "color": TOOL_MAPPING.get(p.get("class_name", ""), {}).get("color", "#aaaaaa")
    } for p in pt_list]

def build_mock_session():
    counts_b = load_json_safe("final_counts_before.json")
    counts_a = load_json_safe("final_counts_after.json")
    
    det_b = format_detections(load_json_safe("rf_detr_before.json").get("detections", []))
    pt_b = format_points(load_json_safe("point_before.json").get("points", []))
    
    det_a = format_detections(load_json_safe("rf_detr_after.json").get("detections", []))
    pt_a = format_points(load_json_safe("point_after.json").get("points", []))

    # 이미지 처리 (원본 before.jpg를 읽어 before_drawn.jpg로 생성)
    if counts_b: draw_and_resize(STATIC_IMG_DIR / "before.jpg", STATIC_IMG_DIR / "before_drawn.jpg", det_b, pt_b)
    if counts_a: draw_and_resize(STATIC_IMG_DIR / "after.jpg", STATIC_IMG_DIR / "after_drawn.jpg", det_a, pt_a)

    return {
        "session_id": _session["session_id"],
        "status": "COMPLETED" if counts_a else "WAITING_AFTER" if counts_b else "WAITING_BEFORE",
        "captures": {
            "before": {
                "image_url": "/static/images/before_drawn.jpg", # 그려진 썸네일 전송
                "captured_at": _iso(now - timedelta(hours=1, minutes=32)),
            } if counts_b else None,
            "after": {
                "image_url": "/static/images/after_drawn.jpg",  # 그려진 썸네일 전송
                "captured_at": _iso(now - timedelta(minutes=4)),
            } if counts_a else None,
        },
        "counts": {"before": counts_b, "after": counts_a}
    }

def _expected_phase(dashboard_state) -> str:
    captures = dashboard_state["captures"]
    if not captures["before"]: return "before"
    if not captures["after"]: return "after"
    return "complete"

def register_heartbeat(payload: dict) -> dict:
    with _lock:
        received_at = datetime.now(timezone.utc).astimezone()
        _device.update({
            "device_id": payload["device_id"],
            "camera_ready": payload["camera_ready"],
            "last_seen_monotonic": monotonic(),
            "last_seen_at": _iso(received_at),
        })
        current_dash = build_mock_session() if MOCK_MODE else _session
        return {
            "ok": True,
            "server_time": _iso(received_at),
            "session_id": current_dash["session_id"],
            "expected_phase": _expected_phase(current_dash),
        }

def get_device_status() -> dict:
    with _lock:
        if MOCK_MODE:
            seconds = 0.4
            last_seen_at = _iso(datetime.now(timezone.utc).astimezone() - timedelta(seconds=seconds))
            connected = True
            camera_ready = True
        elif _device["last_seen_monotonic"] is None:
            seconds = None; last_seen_at = None; connected = False; camera_ready = False
        else:
            seconds = round(monotonic() - _device["last_seen_monotonic"], 1)
            last_seen_at = _device["last_seen_at"]
            camera_ready = _device["camera_ready"]
            connected = seconds <= 3 and camera_ready

        return {
            "device_id": _device["device_id"], "connected": connected,
            "camera_ready": camera_ready, "last_seen_at": last_seen_at,
            "seconds_since_last_seen": seconds, "mock_mode": MOCK_MODE,
        }

def get_dashboard() -> dict:
    with _lock:
        # Mock JSON 파일을 조합하여 최종 대시보드 상태 반환
        result = build_mock_session() if MOCK_MODE else deepcopy(_session)
        result["expected_phase"] = _expected_phase(result)
        result["mock_mode"] = MOCK_MODE
        return result

def reset_session() -> dict:
    with _lock:
        _session["session_id"] += 1
        _session["status"] = "WAITING_BEFORE"
        _session["captures"] = {"before": None, "after": None}
        _session["counts"] = {"before": {}, "after": {}}
        return {"ok": True, "session_id": _session["session_id"], "status": _session["status"]}