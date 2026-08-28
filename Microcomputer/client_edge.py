import cv2
import requests
import time
import sys
import threading
import websocket
import ASUS.GPIO as GPIO
from datetime import datetime, timezone

SERVER_IP = "http://100.87.106.35:8000" 
CAPTURE_API = f"http://{SERVER_IP}/api/capture"
HEARTBEAT_API = f"http://{SERVER_IP}/api/device/heartbeat"
WS_STREAM_API = f"ws://{SERVER_IP}/ws/stream/push"

BUTTON_PIN = 40
DEVICE_ID = "tinker-board-2s"

# [스트리밍용 설정]
STREAM_WIDTH = 1280
STREAM_HEIGHT = 720
STREAM_FPS = 30
STREAM_QUALITY = 50  # 최대 70까지

# [캡처용 설정]
CAPTURE_WIDTH = 3264   # FHD: 1920
CAPTURE_HEIGHT = 2448  # FHD: 1080
CAPTURE_QUALITY = 100

ENABLE_LOCAL_VIEW = False 
current_phase = "before"
camera_is_ready = False
latest_frame = None
is_running = True

def heartbeat_loop():
    while True:
        payload = {
            "device_id": DEVICE_ID, "camera_ready": camera_is_ready,
            "sent_at": datetime.now(timezone.utc).astimezone().isoformat()
        }
        try: requests.post(HEARTBEAT_API, json=payload, timeout=2)
        except: pass
        time.sleep(1.5)

def stream_loop():
    global latest_frame, is_running
    ws = websocket.WebSocket()
    is_ws_connected = False

    while is_running:
        # 웹소켓 연결 유지
        if not is_ws_connected:
            try:
                ws.connect(WS_STREAM_API)
                is_ws_connected = True
                print("🌐 스트리밍 웹소켓 서버에 연결되었습니다.")
            except Exception:
                time.sleep(1)
                continue

        # 프레임 바이너리 전송
        if latest_frame is not None:
            # 1080p 리사이즈 및 인코딩
            stream_frame = cv2.resize(latest_frame, (STREAM_WIDTH, STREAM_HEIGHT))
            success, img_encoded = cv2.imencode('.jpg', stream_frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
            
            if success:
                try:
                    ws.send_binary(img_encoded.tobytes())
                except Exception:
                    # 전송 실패 시 연결이 끊어진 것으로 간주하고 재접속 유도
                    is_ws_connected = False
                    ws.close()
        
        # 30FPS 조절
        time.sleep(1.0 / STREAM_FPS)

def get_working_camera():
    cap = cv2.VideoCapture(5, cv2.CAP_V4L2)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, 30)
        
        ret, _ = cap.read()
        if ret: return cap
    cap.release()
    return None

def main():
    global current_phase, camera_is_ready, latest_frame, is_running

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    cap = get_working_camera()
    if cap is not None:
        camera_is_ready = True
        print("✅ 카메라 연결 성공")
    else:
        print("❌ 카메라 연결 실패")
        return

    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=stream_loop, daemon=True).start()
    print("시스템 준비 완료. (종료하려면 Ctrl+C)")

    try:
        while is_running:
            ret, frame = cap.read()
            if not ret: continue
            
            latest_frame = frame 

            if ENABLE_LOCAL_VIEW:
                cv2.imshow("Live View", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'): break

            if GPIO.input(BUTTON_PIN) == GPIO.HIGH:
                print(f"📸 캡처 전송 중... ({current_phase})")
                success, img_encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, CAPTURE_QUALITY])
                if success:
                    try:
                        res = requests.post(CAPTURE_API, data={'phase': current_phase}, files={'file': ('capture.jpg', img_encoded.tobytes(), 'image/jpeg')}, timeout=5)
                        if res.status_code == 200:
                            print(f"✅ 전송 완료 ({current_phase})")
                            current_phase = "after" if current_phase == "before" else "before"
                    except Exception as e:
                        print(f"❌ 전송 실패: {e}")
                time.sleep(2)

    except KeyboardInterrupt:
        print("\n프로그램을 안전하게 종료합니다...")
    finally:
        is_running = False
        cap.release()
        if ENABLE_LOCAL_VIEW:
            cv2.destroyAllWindows()
            for _ in range(5): cv2.waitKey(1)
        GPIO.cleanup()
        sys.exit(0)

if __name__ == "__main__":
    main()