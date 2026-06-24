import json
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from app.web.models import Base, AuditEvent, ArchivePost, ArchiveComment

logger = logging.getLogger("ReplayEngine")

class ReplayEngine:
    @staticmethod
    def replay_experiment(db: Session, experiment_id: str) -> bool:
        """
        주어진 experiment_id에 대해 저장된 모든 AuditEvent들을 순차 재현(Replay)합니다.
        재현 결과로 나타난 상태(Post, Comment 등)가 원본 DB의 데이터와 정밀 일치하는지 대조합니다.
        데이터 격리를 위해 메모리상에 임시 SQLite DB를 생성하여 복구 검증을 수행합니다.
        """
        logger.info(f"Starting deterministic state replay audit for experiment '{experiment_id}'")
        
        # 1. 원본 AuditEvent 로드
        events = db.query(AuditEvent).filter_by(experiment_id=experiment_id).order_by(AuditEvent.id.asc()).all()
        if not events:
            logger.warning(f"No audit events found for experiment '{experiment_id}' to replay.")
            return False

        # 2. 인메모리 임시 DB 및 스키마 생성
        temp_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(temp_engine)
        TempSession = sessionmaker(bind=temp_engine)
        temp_db = TempSession()

        try:
            # 3. 이벤트 순차 재실행 (Reconstruct state)
            for event in events:
                payload = json.loads(event.payload_json) if event.payload_json else {}
                event_type = event.event_type
                
                # 웹소켓 및 REST API에서 발행되었던 비즈니스 상태 변화 복원
                if event_type == "post.created":
                    post = ArchivePost(
                        experiment_id=experiment_id,
                        post_id=payload.get("post_id"),
                        board_name=payload.get("board_name"),
                        title=payload.get("title"),
                        content=payload.get("content"),
                        agent_id=payload.get("agent_id"),
                        created_at=event.created_at
                    )
                    temp_db.add(post)
                elif event_type == "comment.created":
                    comment = ArchiveComment(
                        experiment_id=experiment_id,
                        comment_id=payload.get("comment_id"),
                        post_id=payload.get("post_id"),
                        parent_id=payload.get("parent_id"),
                        bot_name=payload.get("bot_name"),
                        content=payload.get("content"),
                        anger_score=payload.get("anger_score", 0),
                        mentioned_bot=payload.get("mentioned_bot"),
                        created_at=event.created_at
                    )
                    temp_db.add(comment)
                # 이 외의 정산 이벤트나 워커 등록 이벤트 복원도 가능하지만, 핵심 비즈니스 상태 중심
                
            temp_db.commit()

            # 4. 정합성 대조 (State Comparison)
            # 원본 DB에 기록된 포스트/댓글들과 인메모리에서 복구된 내역을 비교
            orig_posts = db.query(ArchivePost).filter_by(experiment_id=experiment_id).order_by(ArchivePost.post_id.asc()).all()
            replayed_posts = temp_db.query(ArchivePost).filter_by(experiment_id=experiment_id).order_by(ArchivePost.post_id.asc()).all()
            
            if len(orig_posts) != len(replayed_posts):
                logger.error(f"Replay mismatch (Post Count): Original={len(orig_posts)}, Replayed={len(replayed_posts)}")
                return False

            orig_comments = db.query(ArchiveComment).filter_by(experiment_id=experiment_id).order_by(ArchiveComment.comment_id.asc()).all()
            replayed_comments = temp_db.query(ArchiveComment).filter_by(experiment_id=experiment_id).order_by(ArchiveComment.comment_id.asc()).all()

            if len(orig_comments) != len(replayed_comments):
                logger.error(f"Replay mismatch (Comment Count): Original={len(orig_comments)}, Replayed={len(replayed_comments)}")
                return False

            # 개별 데이터 해시/값 검증
            for op, rp in zip(orig_posts, replayed_posts):
                if op.title != rp.title or op.content != rp.content or op.agent_id != rp.agent_id:
                    logger.error(f"Replay content mismatch on Post ID '{op.post_id}'")
                    return False
                    
            for oc, rc in zip(orig_comments, replayed_comments):
                if oc.content != rc.content or oc.bot_name != rc.bot_name or oc.post_id != rc.post_id:
                    logger.error(f"Replay content mismatch on Comment ID '{oc.comment_id}'")
                    return False

            logger.info("Deterministic event replay verified: 100% Match!")
            return True
            
        except Exception as e:
            logger.error(f"Error during deterministic event replay: {e}")
            return False
        finally:
            temp_db.close()
            temp_engine.dispose()
