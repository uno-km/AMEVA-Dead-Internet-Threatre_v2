# ==========================================
# [설정 항목] 원하는 LLM 모델을 정의하세요.
# ==========================================
# 코랩 GPU 환경(T4 VRAM 16GB)에 적합한 추천 모델 리스트입니다.
# - "qwen2.5:1.5b" (약 1.0GB, 초고속)
# - "qwen2.5:3b"   (약 2.0GB, 성능/속도 균형 - 기본 추천)
# - "qwen2.5:7b"   (약 4.7GB, 높은 언어 이해도)
# - "llama3.1:8b"  (약 4.7GB, 긴 콘텍스트 및 추론)
MODEL_NAME = "qwen2.5:3b"

# ==========================================
# 1. Ollama 및 필수 패키지 설치
# ==========================================
print("1. zstd 및 Ollama 설치 중...")
!apt-get update && apt-get install -y zstd wget
!curl -fsSL https://ollama.com/install.sh | sh

import subprocess
import time
import re
import os

# ==========================================
# 2. Ollama 서버 백그라운드 구동 (외부 오리진 허용 설정)
# ==========================================
print("2. Ollama 서버 시작 중...")
with open("ollama.log", "w") as f:
    env = os.environ.copy()
    env["OLLAMA_ORIGINS"] = "*"      # 외부 및 모든 도메인에서의 CORS 요청 허용 (로컬 연동 필수)
    env["OLLAMA_HOST"] = "0.0.0.0"   # 모든 IP 대역에서 바인딩 허용
    subprocess.Popen(["ollama", "serve"], stdout=f, stderr=f, env=env)
time.sleep(5)  # 서버가 안정적으로 시작할 때까지 대기

# ==========================================
# 3. 설정한 LLM 모델 다운로드
# ==========================================
print(f"3. LLM 모델 다운로드 중... ({MODEL_NAME})")
!ollama pull {MODEL_NAME}

# ==========================================
# 4. Cloudflare Tunnel 설치 및 무료 터널 개통
# ==========================================
print("4. Cloudflare 터널 설치 중...")
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
!dpkg -i cloudflared-linux-amd64.deb

print("5. 외부 연동용 터널 주소 생성 중...")
with open("cloudflared.log", "w") as f:
    # 로컬 포트 11434(Ollama 포트)를 외부에 보안 터널로 매핑
    subprocess.Popen(["cloudflared", "tunnel", "--url", "http://localhost:11434"], stdout=f, stderr=f)

# cloudflared 로그에서 trycloudflare.com 임시 외부 도메인 자동 추출
print("터널 접속 주소 확인 중 (최대 40초)...")
for i in range(20):
    time.sleep(2)
    if os.path.exists("cloudflared.log"):
        with open("cloudflared.log", "r") as f:
            log = f.read()
            urls = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", log)
            if urls:
                print("\n" + "="*60)
                print("🎉 연동 준비 완료! 아래 주소를 로컬 클라이언트나 봇 설정에 입력해 주세요:")
                print(f"👉 {urls[0]}")
                print("="*60)
                print(f"\n💡 [로컬 실행 가이드]")
                print(f"로컬 터널 실행 매개변수 예시:")
                print(f"python client_ws.py --bot bot_1 --exp LOBBY --server ws://localhost:8050 --ollama {urls[0]} --model {MODEL_NAME}")
                print(f"\n⚠️ [주의 사항]")
                print(f"- 코랩 세션이 비활성화(Idle) 상태가 되어 끊기면 터널 주소도 함께 소멸합니다.")
                print(f"- 브라우저의 코랩 탭을 열어두고 테스트를 진행하세요.")
                break
else:
    print("\n⚠️ 터널 주소를 추출하지 못했습니다. 아래 명령어로 로그를 직접 확인해 보세요.")
    print("!cat cloudflared.log")
