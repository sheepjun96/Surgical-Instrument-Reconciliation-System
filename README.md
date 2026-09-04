# Surgical Instrument Reconciliation System

수술 전후 수술 도구의 수량을 실시간으로 탐지하고 비교하여 체내 도구 잔류 등의 의료 사고를 예방하고 수술실의 업무 효율을 높이는 AI 기반 통합 모니터링 시스템입니다.

## 🌟 Key Features
* **실시간 수술 도구 탐지**: 팅커보드 2와 맞춤형 촬영 기구를 통해 이미지를 획득하고, RF-DETR 및 Point 예측 인공지능을 활용해 수술 도구의 종류와 위치를 정확하게 인식합니다.
* **수술 전후 수량 비교 (Reconciliation)**: 수술 전 세팅된 도구와 수술 후 회수된 도구의 수량을 비교표로 시각화하여 누락(미검출) 및 추가 여부를 즉각적으로 확인할 수 있습니다.
* **직관적인 모니터링 대시보드**: Vue.js를 활용하여 카메라 연결 상태, AI 분석 완료 여부, 수량 차이에 따른 하이라이트(경고색 등)를 실시간으로 반영하는 반응형 UI를 제공합니다.
* **유연한 백엔드 아키텍처**: FastAPI를 기반으로 가볍고 빠른 RESTful API를 구축하였으며, MySQL을 통해 세션 및 추론 데이터를 안전하게 영속화합니다.

## 🛠 Tech Stack
**Hardware**
* Tinker Board 2
* 맞춤형 촬영 기구 (Custom Camera Rig)

**AI (Deep Learning)**
* RF-DETR (Object Detection)
* Point Prediction Model

**Backend (API Server)**
* Python 3.11
* FastAPI
* MySQL

**Frontend (Web UI)**
* HTML5 / CSS3
* Vanilla JavaScript
* Vue.js (CDN)

## 🚀 Getting Started

### Prerequisites
* Python 3.8 이상 설치
* MySQL 서버 실행 및 데이터베이스 세팅
* 카메라 하드웨어 연동 설정 (Tinker Board 2)

### Installation & Execution

1. **Clone the repository**
   ```bash
   git clone [https://github.com/sheepjun96/Surgical-Instrument-Reconciliation-System.git](https://github.com/sheepjun96/Surgical-Instrument-Reconciliation-System.git)
   cd Surgical-Instrument-Reconciliation-System
   ```
2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   Database Configuration
   ```

3. **Database Configuration**
- .env 파일을 생성하고 MySQL 연결 정보를 입력합니다.
- Alembic 또는 제공된 스키마 파일을 통해 데이터베이스 테이블을 생성합니다.

4. **Run the server**
  ```bash
python run_platform.py
 ```
- 서버 실행 후, 브라우저에서 http://127.0.0.1:8000 (또는 설정된 IP)로 접속하여 모니터링 대시보드를 확인할 수 있습니다.

📂 Project Structure
```text
Surgical-Instrument-Reconciliation-System/
├── main.py              # FastAPI 애플리케이션 진입점
├── router/              # API 라우터 (dashboard, device, session 등)
├── models/              # 데이터베이스 모델 (MySQL) 및 Pydantic 스키마
├── services/            # 비즈니스 로직 및 AI 추론 파이프라인
├── static/              # 정적 파일 (CSS, JS, 썸네일 이미지)
├── templates/           # HTML 템플릿 파일 (index.html 등)
├── requirements.txt     # 파이썬 의존성 패키지 목록
└── README.md
```
