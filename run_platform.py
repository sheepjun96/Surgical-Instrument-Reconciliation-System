import subprocess
import sys
import os
import argparse

def main():
    parser = argparse.ArgumentParser(description="수술도구 모니터 플랫폼 서버")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="시연 모드로 실행합니다. 세션 16·17의 비교표 수치가 하드코딩된 값으로 제공됩니다."
    )
    args = parser.parse_args()

    # 현재 프로세스 환경변수 복사 후 DEMO_MODE 주입
    env = os.environ.copy()
    if args.demo:
        env["DEMO_MODE"] = "1"
        print("🎬 [시연 모드] 세션 16·17의 비교표 수치가 하드코딩 값으로 표시됩니다.")
    else:
        env.pop("DEMO_MODE", None)
        print("▶  [일반 모드] AI 추론 결과가 그대로 표에 표시됩니다.")

    print("🚀 플랫폼 서버(Uvicorn)를 시작합니다...")
    # Tailscale IP로 접근할 수 있도록 0.0.0.0 바인딩 유지
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "0.0.0.0", "--port", "8000", "--reload"],
        env=env  # DEMO_MODE 포함된 환경을 uvicorn 워커에 상속
    )

if __name__ == "__main__":
    main()