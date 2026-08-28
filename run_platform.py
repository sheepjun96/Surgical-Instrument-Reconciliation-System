import subprocess
import sys

def main():
    print("🚀 플랫폼 서버(Uvicorn)를 시작합니다...")
    # Tailscale IP로 접근할 수 있도록 0.0.0.0 바인딩 유지
    subprocess.run([
        sys.executable, "-m", "uvicorn", "main:app", 
        "--host", "0.0.0.0", "--port", "8000", "--reload"
    ])

if __name__ == "__main__":
    main()