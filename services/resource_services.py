from __future__ import annotations
import json, os, cv2
import numpy as np
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from fastapi import UploadFile
from collections import Counter

# AI 모듈 Import
from services.ai_rfdetr import get_predictor as get_rfdetr_predictor
from services.ai_colsr import get_colsr_predictor

_lock = Lock()

# Mock 관련 폴더 제거, Upload 폴더만 유지
UPLOAD_DIR = Path("data/uploads")

TOOL_MAPPING = {
    "forceps": {"name": "Forceps", "color": "#ef4444"},
    "hand_instrument": {"name": "Hand Instrument", "color": "#3b82f6"},
    "retractor": {"name": "Retractor", "color": "#a855f7"},
    "trocar": {"name": "Trocar", "color": "#22c55e"},
}

def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")

now = datetime.now(timezone.utc).astimezone()
_device = {"device_id": "jetson-nano-01", "camera_ready": True, "last_seen_monotonic": None, "last_seen_at": None}

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

async def process_capture_upload(file: UploadFile, phase: str):
    with _lock:
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        h, w = img.shape[:2]
        max_dim = 1280
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        session_dir = UPLOAD_DIR / str(_session["session_id"])
        session_dir.mkdir(parents=True, exist_ok=True)
        
        orig_path = session_dir / f"{phase}_original.jpg"
        cv2.imwrite(str(orig_path), img)

        # ---------------------------------------------------------
        # 1. RF-DETR 추론 실행
        # ---------------------------------------------------------
        rf_predictor = get_rfdetr_predictor()
        colsr_predictor = get_colsr_predictor()

        det_raw = rf_predictor.predict(str(orig_path))
        
        # ---------------------------------------------------------
        # 2. hand_instrument 크롭 및 CoLSR 교차 검증 로직
        # ---------------------------------------------------------
        valid_points = []
        counts_data = {}
        drawn_img = img.copy()

        for idx, d in enumerate(det_raw):
            c_name = d.get("class_name", "unknown")
            x1, y1, x2, y2 = map(int, d["bbox"])
            
            # 기본 BBox 시각화 그리기
            color_hex = TOOL_MAPPING.get(c_name, {}).get("color", "#aaaaaa")
            label_text = f"{TOOL_MAPPING.get(c_name, {}).get('name', c_name)} {int(d.get('confidence', 1.0)*100)}%"
            color = hex_to_bgr(color_hex)
            
            cv2.rectangle(drawn_img, (x1, y1), (x2, y2), color, 3)
            (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            cv2.rectangle(drawn_img, (x1, y1 - th - 10), (x1 + tw, y1), color, -1)
            cv2.putText(drawn_img, label_text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            # [수정된 핵심 로직]: hand_instrument일 경우 크롭하여 포인트 모델 사용
            if c_name == "hand_instrument":
                # 원본 이미지 밖으로 나가지 않도록 경계 보정
                crop_x1, crop_y1 = max(0, x1), max(0, y1)
                crop_x2, crop_y2 = min(w, x2), min(h, y2)
                
                crop_img = img[crop_y1:crop_y2, crop_x1:crop_x2]
                
                # 비정상 크롭 방어
                if crop_img.size == 0:
                    continue
                    
                # 크롭된 이미지 디스크에 저장
                crop_filename = f"{phase}_crop_hand_inst_{idx}.jpg"
                crop_path = session_dir / crop_filename
                cv2.imwrite(str(crop_path), crop_img)
                
                # 포인트 모델(CoLSR)을 '크롭된 이미지'에 대해 실행
                pt_raw = colsr_predictor.predict(str(crop_path))
                
                for pt in pt_raw:
                    pt_class = pt.get("class_name", "unknown")
                    # 크롭된 이미지 기준의 좌표이므로, 원본 이미지 좌표계로 복원
                    abs_x = int(pt["x"]) + crop_x1
                    abs_y = int(pt["y"]) + crop_y1
                    
                    valid_points.append({
                        "class_name": pt_class,
                        "x": abs_x,
                        "y": abs_y,
                        "confidence": pt.get("confidence", 1.0)
                    })
                    # 탐지된 하위 도구 개수 증가
                    counts_data[pt_class] = counts_data.get(pt_class, 0) + 1
            else:
                # hand_instrument가 아닌 도구(forceps, retractor 등)는 BBox 하나당 개수 1개로 처리
                counts_data[c_name] = counts_data.get(c_name, 0) + 1

        # ---------------------------------------------------------
        # 3. 유효 포인트 시각화 (hand_instrument 내부 포인트들)
        # ---------------------------------------------------------
        for p in valid_points:
            p_name = p.get("class_name", "")
            p_color = hex_to_bgr(TOOL_MAPPING.get(p_name, {}).get("color", "#aaaaaa"))
            px, py = p["x"], p["y"]
            
            cv2.circle(drawn_img, (px, py), 8, p_color, -1)
            cv2.circle(drawn_img, (px, py), 8, (255, 255, 255), 2)
            
        drawn_path = session_dir / f"{phase}_drawn.jpg"
        cv2.imwrite(str(drawn_path), drawn_img)

        # ---------------------------------------------------------
        # 4. JSON 데이터 저장 및 상태 업데이트
        # ---------------------------------------------------------
        with open(session_dir / f"{phase}_detections.json", "w", encoding="utf-8") as f:
            json.dump(det_raw, f, ensure_ascii=False, indent=2)
            
        with open(session_dir / f"{phase}_points_valid.json", "w", encoding="utf-8") as f:
            json.dump(valid_points, f, ensure_ascii=False, indent=2)
            
        with open(session_dir / f"{phase}_counts.json", "w", encoding="utf-8") as f:
            json.dump(counts_data, f, ensure_ascii=False, indent=2)

        captured_time = _iso(datetime.now(timezone.utc))
        _session["captures"][phase] = {
            "original_url": f"/{orig_path.as_posix()}",
            "drawn_url": f"/{drawn_path.as_posix()}",
            "captured_at": captured_time,
        }
        _session["counts"][phase] = counts_data

        if _session["captures"]["before"] and _session["captures"]["after"]:
            _session["status"] = "COMPLETED"
        elif _session["captures"]["before"]:
            _session["status"] = "WAITING_AFTER"

        return {"ok": True, "phase": phase}

def _expected_phase() -> str:
    if not _session["captures"]["before"]: return "before"
    if not _session["captures"]["after"]: return "after"
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
        return {
            "ok": True, "server_time": _iso(received_at),
            "session_id": _session["session_id"],
            "expected_phase": _expected_phase(),
        }

def get_device_status() -> dict:
    with _lock:
        # Mock 모드 완전 제거, 실제 시간 계산만 수행
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

def get_dashboard() -> dict:
    with _lock:
        result = deepcopy(_session)
        result["expected_phase"] = _expected_phase()
        result["mock_mode"] = False
        return result

def reset_session() -> dict:
    with _lock:
        _session["session_id"] += 1
        _session["status"] = "WAITING_BEFORE"
        _session["captures"] = {"before": None, "after": None}
        _session["counts"] = {"before": {}, "after": {}}
        return {"ok": True, "session_id": _session["session_id"], "status": _session["status"]}