import hmac
import hashlib
import time
from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from app.web.database import get_db

from app.web.models import FederatedSite, SiteKey

# Replay 방지를 위한 인메모리 Nonce 캐시 (유닛 테스트 및 단일 서버용)
# 운영 환경에서는 Redis 등의 TTL 캐시 사용이 권장됨
_NONCE_CACHE = set()

async def verify_signature(request: Request, db: Session = Depends(get_db)):
    # 1. 헤더 추출
    signature = request.headers.get("X-AMEVA-Signature")
    timestamp_str = request.headers.get("X-AMEVA-Timestamp")
    nonce = request.headers.get("X-AMEVA-Nonce")
    site_id = request.headers.get("X-AMEVA-Site-ID")

    if not all([signature, timestamp_str, nonce, site_id]):
        raise HTTPException(
            status_code=401, 
            detail="Missing security headers (X-AMEVA-Signature, X-AMEVA-Timestamp, X-AMEVA-Nonce, X-AMEVA-Site-ID)"
        )

    # 2. 타임스탬프 오차 검증 (Replay Attack 방어 - 5분)
    try:
        req_timestamp = float(timestamp_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")

    current_time = time.time()
    if abs(current_time - req_timestamp) > 300:
        raise HTTPException(status_code=401, detail="Request timestamp expired (tolerance: 5 minutes)")

    # 3. Nonce 중복 검증 (Replay Attack 방어)
    nonce_key = f"{site_id}:{nonce}"
    if nonce_key in _NONCE_CACHE:
        raise HTTPException(status_code=401, detail="Duplicate request detected (Nonce replay)")
    _NONCE_CACHE.add(nonce_key)
    # 간단한 Nonce 캐시 정리 (최대 10000개 유지)
    if len(_NONCE_CACHE) > 10000:
        _NONCE_CACHE.clear()

    # 4. 사이트 등록 정보 및 활성 키 확인
    site = db.query(FederatedSite).filter_by(site_id=site_id, status="ACTIVE").first()
    if not site:
        raise HTTPException(status_code=401, detail="Unregistered or suspended site ID")

    site_key = db.query(SiteKey).filter_by(site_id=site_id, is_active=1).first()
    if not site_key:
        raise HTTPException(status_code=401, detail="Active secret key not found for the site")

    # 5. 서명 계산 및 검증
    body_bytes = await request.body()
    message = f"{timestamp_str}.{nonce}.".encode("utf-8") + body_bytes
    expected_sig = hmac.new(
        site_key.secret_key.encode("utf-8"),
        message,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    return site_id

# Outbound Webhook 발송을 위한 서명 생성 헬퍼 함수
def generate_outbound_signature(secret_key: str, timestamp: float, nonce: str, body: bytes) -> str:
    message = f"{int(timestamp)}.{nonce}.".encode("utf-8") + body
    return hmac.new(
        secret_key.encode("utf-8"),
        message,
        hashlib.sha256
    ).hexdigest()
