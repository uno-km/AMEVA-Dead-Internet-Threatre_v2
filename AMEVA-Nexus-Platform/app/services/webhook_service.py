import httpx
import time
import uuid
import json
import logging
from sqlalchemy.orm import Session
from app.web.models import FederatedSite, SiteKey, AuditEvent
from app.services.security import generate_outbound_signature

logger = logging.getLogger("WebhookService")

class WebhookService:
    @staticmethod
    async def push_event(db: Session, event_type: str, experiment_id: str, payload: dict, site_id: str = None):
        """
        플랫폼 내부 이벤트를 등록된 연합 사이트에 Webhook으로 Push합니다.
        site_id가 지정되지 않으면 활성화된 모든 사이트로 전송합니다(Fanout).
        """
        # 1. 대상 사이트 조회
        query = db.query(FederatedSite).filter_by(status="ACTIVE")
        if site_id:
            query = query.filter_by(site_id=site_id)
        sites = query.all()

        if not sites:
            logger.info("No active federated sites to dispatch webhook event.")
            return

        # 2. Audit Trail 기록 (플랫폼 중앙)
        # 로우 데이터 전체가 아닌 감사용 정보를 AuditEvent에 적재
        # 민감 데이터 최소화 원칙에 따라 content 등의 상세 정보는 DIT 내부 로컬에 보관
        audit = AuditEvent(
            event_type=event_type,
            tenant_id=site_id or "SYSTEM",
            experiment_id=experiment_id,
            agent_id=payload.get("agent_id") or payload.get("node_id"),
            payload_json=json.dumps({
                "event_type": event_type,
                "occurred_at": time.time(),
                "summary": payload.get("description") or f"Event {event_type} triggered"
            }),
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)

        # 3. 비동기 HTTP 요청 발송
        async with httpx.AsyncClient() as client:
            for site in sites:
                if not site.webhook_url:
                    continue

                # 사이트별 활성 키 가져오기
                site_key = db.query(SiteKey).filter_by(site_id=site.site_id, is_active=1).first()
                if not site_key:
                    logger.warning(f"No active secret key found for site {site.site_id}. Skipping Webhook.")
                    continue

                # Envelope 구성 (명세서 규격 준수)
                event_id = f"evt_{uuid.uuid4().hex[:12]}"
                envelope = {
                    "schema_version": "1.0.0",
                    "site_id": site.site_id,
                    "experiment_id": experiment_id,
                    "event_id": event_id,
                    "occurred_at": datetime_to_iso8601(time.time()),
                    "event_type": event_type,
                    "payload": payload,
                    "extensions": {}
                }
                body_bytes = json.dumps(envelope).encode("utf-8")
                
                # 서명 생성
                timestamp = time.time()
                nonce = uuid.uuid4().hex
                sig = generate_outbound_signature(site_key.secret_key, timestamp, nonce, body_bytes)

                headers = {
                    "Content-Type": "application/json",
                    "X-AMEVA-Signature": sig,
                    "X-AMEVA-Timestamp": str(int(timestamp)),
                    "X-AMEVA-Nonce": nonce,
                    "X-AMEVA-Site-ID": "PLATFORM"  # 플랫폼이 발행주체임을 명시
                }

                # 전송 (간단한 재시도 3회 포함)
                success = False
                for attempt in range(3):
                    try:
                        resp = await client.post(
                            site.webhook_url,
                            content=body_bytes,
                            headers=headers,
                            timeout=5.0
                        )
                        if resp.status_code == 200:
                            success = True
                            break
                        else:
                            logger.warning(f"Webhook push to {site.site_id} failed with code {resp.status_code} (Attempt {attempt+1})")
                    except Exception as e:
                        logger.error(f"Webhook push to {site.site_id} failed with error: {e} (Attempt {attempt+1})")
                    time.sleep(0.5)

                if not success:
                    # 실패 시 사이트의 상태를 OFFLINE 또는 점검 등으로 업데이트할 수 있음
                    logger.error(f"Permanently failed to push webhook event {event_id} to site {site.site_id}.")
                    # 비상 로그 감사 트레일에 실패 기록 추가 가능

    @classmethod
    def push_event_background(cls, db: Session, event_type: str, experiment_id: str, payload: dict, site_id: str = None):
        """
        비동기 push_event를 동기 환경이나 유닛 테스트 환경에서도 백그라운드/동기식으로 안전하게 실행합니다.
        """
        import asyncio

        coro = cls.push_event(db, event_type, experiment_id, payload, site_id)

        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(coro)
                return
        except RuntimeError:
            pass

        # 구동 중인 loop가 없으나 get_event_loop()가 존재하면 사용, 없으면 새 loop 세팅
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        loop.run_until_complete(coro)

def datetime_to_iso8601(timestamp: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
