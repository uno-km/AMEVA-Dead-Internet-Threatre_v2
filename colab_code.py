# 1. Ollama 설치 및 백그라운드 실행
print("1. Ollama 설치 중...")
!curl -fsSL https://ollama.com/install.sh | sh

import subprocess
import time
import re

print("2. Ollama 서버 시작 중...")
with open("ollama.log", "w") as f:
    subprocess.Popen(["ollama", "serve"], stdout=f, stderr=f)
time.sleep(3)

# 2. 테스트용 가벼운 모델 다운로드 (빠른 다운로드를 위해 gemma:2b 사용)
print("3. Gemma:2b 모델 다운로드 중... (약 1.6GB)")
!ollama pull gemma:2b

# 3. Cloudflare Tunnel 설치 및 실행 (로그인/토큰 필요 없음)
print("4. Cloudflare 터널 설치 중...")
!wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
!dpkg -i cloudflared-linux-amd64.deb

print("5. 터널 생성 및 주소 추출 중...")
with open("cloudflared.log", "w") as f:
    subprocess.Popen(["cloudflared", "tunnel", "--url", "http://localhost:11434"], stdout=f, stderr=f)

# 터널 주소가 로그에 찍힐 때까지 잠시 대기
for _ in range(10):
    time.sleep(2)
    with open("cloudflared.log", "r") as f:
        log = f.read()
        urls = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", log)
        if urls:
            print("\n🎉 성공! 아래 주소를 로컬 봇 설정에 넣으세요:")
            print(f"👉 {urls[0]}")
            break
else:
    print("\n⚠️ 주소를 추출하는 데 실패했습니다. cloudflared.log 파일을 확인해 보세요.")
