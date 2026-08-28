import cv2
import requests
import time
import threading
import ASUS.GPIO as GPIO
from datetime import datetime, timezone

# 환경 및 해상도 설정
BASE_URL = "https://unblock-stubborn-avenue.ngrok-free.dev" 
CAPTURE_API = f"{BASE_URL}/api/capture"
HEARTBEAT_API = f"{BASE_URL}/api/device/heartbeat"
STREAM_API = f"{BASE_URL}/api/stream/push"

BUTTON_PIN = 40
DEVICE_ID = "tinker-board-2s"

# [스트리밍용 설정]
STREAM_WIDTH = 1280
STREAM_HEIGHT = 720
STREAM_FPS = 10
STREAM_QUALITY = 60  # JPEG 압축률 (0~100)

# [캡처용 설정]
CAPTURE_WIDTH = 1920
CAPTURE_HEIGHT = 1080
CAPTURE_QUALITY = 100

current_phase = "before"
camera_is_ready = False
latest_frame = None # 원본 고화질 프레임

# 백그라운드 스레드
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
    global latest_frame
    while True:
        if latest_frame is not None:
            # 원본 프레임을 스트리밍용 크기로 리사이즈
            stream_frame = cv2.resize(latest_frame, (STREAM_WIDTH, STREAM_HEIGHT))
            # 스트리밍 품질로 압축
            success, img_encoded = cv2.imencode('.jpg', stream_frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUALITY])
            if success:
                try:
                    requests.post(STREAM_API, files={'file': ('frame.jpg', img_encoded.tobytes(), 'image/jpeg')}, timeout=1)
                except:
                    pass
        time.sleep(1.0 / STREAM_FPS) # 프레임 속도 조절

# 메인 카메라 제어
def get_working_camera():
    cap = cv2.VideoCapture(5, cv2.CAP_V4L2)
    if cap.isOpened():
        ret, _ = cap.read()
        if ret: return cap
    cap.release()
    return None

def main():
    global current_phase, camera_is_ready, latest_frame

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(
        BUTTON_PIN,
        GPIO.IN,
        pull_up_down=GPIO.PUD_DOWN
    )

    cap = get_working_camera()
    if cap is not None:
        camera_is_ready = True
        # 카메라는 캡처용 고해상도로 켭니다.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH) 
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    else:
        print("❌ 카메라 에러")
        return

    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=stream_loop, daemon=True).start()

    print("시스템 대기 중...")

    try:
        while True:
            ret, frame = cap.read()
            if not ret: continue
            
            latest_frame = frame 
            cv2.imshow("Live View", frame)
            cv2.waitKey(1)

            if GPIO.input(BUTTON_PIN) == GPIO.HIGH:
                print(f"📸 캡처 전송 중... ({current_phase})")
                # 캡처는 100% 원본 화질로 인코딩
                success, img_encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, CAPTURE_QUALITY])
                if success:
                    try:
                        res = requests.post(CAPTURE_API, data={'phase': current_phase}, files={'file': ('capture.jpg', img_encoded.tobytes(), 'image/jpeg')})
                        if res.status_code == 200:
                            current_phase = "after" if current_phase == "before" else "before"
                    except: pass
                time.sleep(2)

    except KeyboardInterrupt: pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
        GPIO.cleanup()

if __name__ == "__main__":
    main()