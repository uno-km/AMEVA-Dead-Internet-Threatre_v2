import logging
import asyncio
import hashlib
import os
from sqlalchemy.orm import Session
from app.web.database import SessionLocal
from app.web.models import ArchivePost, ArchiveComment, ArchiveAgentStateSnapshot
from app.services.event_bus import get_event_bus
import json

MASK_ARCHIVE_CONTENT = os.getenv("MASK_ARCHIVE_CONTENT", "false").lower() == "true"

def mask_content(content: str) -> str:
    if not content:
        return ""
    if MASK_ARCHIVE_CONTENT:
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"[HASHED:{h}]"
    return content

logger = logging.getLogger("ResearchArchiver")

class ResearchArchiverConsumer:
    """
    플랫폼 측 백그라운드 소비자.
    특정 실험(experiment_id)의 도메인 이벤트 스트림('domain')을 감청하여
    글로벌 연구 데이터 아카이브 테이블(archive_posts, archive_comments, archive_agent_state_snapshots)로 비동기 미러링 복사합니다.
    """
    def __init__(self, experiment_id: str):
        self.experiment_id = experiment_id
        self.stream_name = f"ameva:exp:{experiment_id}:domain"
        self.group_name = "platform_archiver_group"
        self.consumer_name = "platform_archiver_worker"
        self.bus = get_event_bus()
        
        # 소비자 그룹 생성
        self.bus.create_consumer_group(self.stream_name, self.group_name)

    async def start_loop(self):
        logger.info(f"ResearchArchiverConsumer started for experiment {self.experiment_id}")
        while True:
            try:
                processed = await self.process_next()
                if processed == 0:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in ResearchArchiverConsumer loop: {e}")
                await asyncio.sleep(2.0)

    async def process_next(self) -> int:
        # XREADGROUP
        messages = self.bus.read_group(
            stream_name=self.stream_name,
            group_name=self.group_name,
            consumer_name=self.consumer_name,
            count=10,
            block_ms=1000
        )
        if not messages:
            return 0

        db: Session = SessionLocal()
        processed_count = 0
        try:
            for msg_id, envelope in messages:
                event_type = envelope.get("event_type")
                payload = envelope.get("payload", {})
                
                logger.info(f"Archiving event {event_type} (Msg ID: {msg_id})")

                if event_type == "post.created":
                    # 중복 저장 방지 (Post ID 와 Experiment ID 가 같으면 스킵)
                    post_id = payload.get("post_id")
                    exists = db.query(ArchivePost).filter_by(
                        experiment_id=self.experiment_id, 
                        post_id=post_id
                    ).first()
                    if not exists:
                        archive_post = ArchivePost(
                            experiment_id=self.experiment_id,
                            post_id=post_id,
                            board_name=payload.get("board_name"),
                            title=payload.get("title"),
                            content=mask_content(payload.get("content")),
                            agent_id=payload.get("agent_id")
                        )
                        db.add(archive_post)
 
                elif event_type == "comment.created":
                    comment_id = payload.get("comment_id")
                    exists = db.query(ArchiveComment).filter_by(
                        experiment_id=self.experiment_id, 
                        comment_id=comment_id
                    ).first()
                    if not exists:
                        archive_comment = ArchiveComment(
                            experiment_id=self.experiment_id,
                            comment_id=comment_id,
                            post_id=payload.get("post_id"),
                            parent_id=payload.get("parent_id"),
                            bot_name=payload.get("bot_name"),
                            content=mask_content(payload.get("content")),
                            anger_score=payload.get("anger_score", 0),
                            mentioned_bot=payload.get("mentioned_bot")
                        )
                        db.add(archive_comment)

                elif event_type == "agent.snapshot":
                    # LPDE 스냅샷 미러링
                    session_id = payload.get("session_id")
                    turn_index = payload.get("turn_index")
                    bot_name = payload.get("bot_name")
                    exists = db.query(ArchiveAgentStateSnapshot).filter_by(
                        experiment_id=self.experiment_id,
                        session_id=session_id,
                        turn_index=turn_index,
                        bot_name=bot_name
                    ).first()
                    if not exists:
                        archive_snapshot = ArchiveAgentStateSnapshot(
                            experiment_id=self.experiment_id,
                            session_id=session_id,
                            turn_index=turn_index,
                            bot_name=bot_name,
                            traits_json=json.dumps(payload.get("traits_json", [])),
                            states_json=json.dumps(payload.get("states_json", [])),
                            affect_json=json.dumps(payload.get("affect_json", [])),
                            memory_json=json.dumps(payload.get("memory_json", [])),
                            opinion_json=json.dumps(payload.get("opinion_json", [])),
                            power_json=json.dumps(payload.get("power_json", [])),
                            residual_json=json.dumps(payload.get("residual_json", [])),
                            role_label=payload.get("role_label", "swing_moderate")
                        )
                        db.add(archive_snapshot)

                db.commit()
                # ACK 전송
                self.bus.ack(self.stream_name, self.group_name, msg_id)
                processed_count += 1
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to process archive message: {e}")
            raise e
        finally:
            db.close()

        return processed_count
