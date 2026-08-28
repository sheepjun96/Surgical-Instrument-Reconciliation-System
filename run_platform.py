import subprocess
import sys

def main():
    ngrok_path = "C:/Users/gcubme/Downloads/ngrok-v3-stable-windows-amd64/ngrok.exe"

    print("🌐 Ngrok 터미널을 새 창에서 엽니다...")
    subprocess.Popen(f'start cmd /k "{ngrok_path} http 8000"', shell=True)

    print("🚀 플랫폼 서버(Uvicorn)를 시작합니다...")
    subprocess.run([sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"])

if __name__ == "__main__":
    main()