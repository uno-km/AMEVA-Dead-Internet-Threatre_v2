import json
import logging
from sqlalchemy.orm import Session
from app.web.models import ExperimentSpec, WorkerNode, DispatchAssignment, ActiveNode, Reputation

logger = logging.getLogger("DispatcherService")

class DispatcherService:
    @staticmethod
    def calculate_dispatch_score(db: Session, worker: WorkerNode, agent_id: str) -> float:
        """
        워커 노드의 실측 하드웨어 능력, 신뢰도, 지연시간, 품질을 종합하여 디스패치 점수를 계산합니다.
        Score = (capability_score * 0.3) + (reliability_score * 0.3) - (avg_latency / 100.0 * 2.0) + (quality_score * 0.2)
        """
        rep = db.query(Reputation).filter_by(agent_id=agent_id).first()
        if rep:
            cap = getattr(rep, "capability_score", 100.0)
            rel = getattr(rep, "reliability_score", 100.0)
            lat = getattr(rep, "avg_latency", 0.0)
            qual = getattr(rep, "quality_score", 100.0)
            score = (cap * 0.3) + (rel * 0.3) - (lat / 100.0 * 2.0) + (qual * 0.2)
        else:
            # 기본값 적용 (VRAM 기준 가중)
            cap = min(100.0, (worker.vram_gb / 8.0) * 100.0) if worker.vram_gb > 0 else 30.0
            score = (cap * 0.3) + (100.0 * 0.3) + (100.0 * 0.2)
        return score

    @staticmethod
    def get_eligible_active_workers(db: Session, spec: ExperimentSpec) -> list:
        """
        실험 사양을 충족하고 현재 ACTIVE 또는 LOBBY_WAITING 상태인 워커 노드 목록을 반환합니다.
        """
        workers = db.query(WorkerNode).all()
        eligible = []
        for w in workers:
            active_node = db.query(ActiveNode).filter_by(node_id=f"node_{w.node_id}").first()
            if not active_node or active_node.status not in ["ACTIVE", "LOBBY_WAITING"]:
                continue

            models = json.loads(w.available_models_json) if w.available_models_json else []
            if w.vram_gb >= spec.min_vram_gb:
                if not spec.required_model or spec.required_model in models:
                    agent_id = active_node.bot_name if active_node else f"bot_node_{w.node_id}"
                    eligible.append((w, agent_id))
        return eligible

    @staticmethod
    def dispatch_experiment(db: Session, experiment_id: str) -> list[DispatchAssignment]:
        """
        실험 스펙에 맞춰 사용 가능한 활성 워커 중 가장 높은 점수의 워커를 매칭하여 할당합니다.
        spec.max_participants 내로 제한하여 할당합니다.
        """
        spec = db.query(ExperimentSpec).filter_by(experiment_id=experiment_id).first()
        if not spec:
            raise ValueError(f"Experiment specification '{experiment_id}' not found")

        # 현재 해당 실험에 배정된 총 인원 계산
        total_assigned = db.query(DispatchAssignment).filter_by(
            experiment_id=experiment_id,
            status="ASSIGNED"
        ).count()

        slots_available = spec.max_participants - total_assigned
        if slots_available <= 0:
            logger.info(f"Experiment '{experiment_id}' already has max participants assigned.")
            return []

        eligible = DispatcherService.get_eligible_active_workers(db, spec)
        if not eligible:
            logger.warning("No active/lobby worker nodes meet the experiment requirements")
            return []

        # 각 워커의 디스패치 점수를 계산하여 정렬
        scored_workers = []
        for worker, agent_id in eligible:
            score = DispatcherService.calculate_dispatch_score(db, worker, agent_id)
            scored_workers.append((score, worker, agent_id))

        # 내림차순 정렬
        scored_workers.sort(key=lambda x: x[0], reverse=True)

        assignments = []
        # 상위 핏 노드들을 할당 (중복 방지 및 정원 제한)
        for score, worker, agent_id in scored_workers:
            if len(assignments) >= slots_available:
                break

            exists = db.query(DispatchAssignment).filter_by(
                experiment_id=experiment_id,
                node_id=worker.node_id,
                status="ASSIGNED"
            ).first()

            if not exists:
                assign = DispatchAssignment(
                    experiment_id=experiment_id,
                    node_id=worker.node_id,
                    agent_id=agent_id,
                    status="ASSIGNED"
                )
                db.add(assign)
                assignments.append(assign)

                # 노드 상태를 LOBBY_WAITING에서 ACTIVE로 변경
                active_node = db.query(ActiveNode).filter_by(node_id=f"node_{worker.node_id}").first()
                if active_node:
                    active_node.status = "ACTIVE"
                    active_node.current_activity = f"Assigned to {experiment_id}"

        db.commit()

        # Webhook push 비동기 실행 (연합 사이트 동기화)
        from app.services.webhook_service import WebhookService
        for assign in assignments:
            WebhookService.push_event_background(
                db=db,
                event_type="experiment.dispatched",
                experiment_id=experiment_id,
                payload={
                    "node_id": assign.node_id,
                    "agent_id": assign.agent_id,
                    "status": assign.status,
                    "description": f"Assigned experiment {experiment_id} to node {assign.node_id}"
                }
            )

        return assignments

    @staticmethod
    def start_recruitment(db: Session, experiment_id: str, max_participants: int = 5) -> dict:
        """
        모집(Recruitment) 프로세스 개시
        """
        from datetime import datetime
        spec = db.query(ExperimentSpec).filter_by(experiment_id=experiment_id).first()
        if not spec:
            raise ValueError(f"Experiment specification '{experiment_id}' not found")
        
        spec.status = "RECRUITING"
        spec.max_participants = max_participants
        spec.recruitment_start_time = datetime.now()
        db.commit()

        # 최초 모집 실행
        assignments = DispatcherService.dispatch_experiment(db, experiment_id)
        
        # 만약 정원이 다 찼으면 바로 RUNNING 상태로 전환
        total_assigned = db.query(DispatchAssignment).filter_by(
            experiment_id=experiment_id,
            status="ASSIGNED"
        ).count()

        if total_assigned >= spec.max_participants:
            spec.status = "RUNNING"
            spec.actual_start_time = datetime.now()
            db.commit()
            logger.info(f"Experiment '{experiment_id}' reached max capacity immediately and started.")
        
        return {
            "status": spec.status,
            "assigned_count": total_assigned,
            "assigned_workers": [a.node_id for a in assignments]
        }

    @staticmethod
    def check_recruitment_status(db: Session, experiment_id: str) -> dict:
        """
        모집 상태 체크 및 5분 타임아웃 판정
        """
        from datetime import datetime
        spec = db.query(ExperimentSpec).filter_by(experiment_id=experiment_id).first()
        if not spec:
            return {"status": "NOT_FOUND"}
            
        if spec.status == "RECRUITING":
            now = datetime.now()
            elapsed = (now - spec.recruitment_start_time).total_seconds() if spec.recruitment_start_time else 0.0
            
            # 현재 배정 완료된 인원
            total_assigned = db.query(DispatchAssignment).filter_by(
                experiment_id=experiment_id,
                status="ASSIGNED"
            ).count()
            
            if total_assigned >= spec.max_participants:
                spec.status = "RUNNING"
                spec.actual_start_time = now
                db.commit()
                logger.info(f"Experiment '{experiment_id}' started because max capacity ({spec.max_participants}) was reached.")
            elif elapsed >= 300.0:  # 5분 타임아웃
                spec.status = "RUNNING"
                spec.actual_start_time = now
                db.commit()
                logger.info(f"Experiment '{experiment_id}' started due to 5-minute recruitment timeout. Participants: {total_assigned}")
                
        return {
            "status": spec.status,
            "max_participants": spec.max_participants,
            "recruitment_start_time": spec.recruitment_start_time.isoformat() if spec.recruitment_start_time else None,
            "actual_start_time": spec.actual_start_time.isoformat() if spec.actual_start_time else None
        }

    @staticmethod
    def try_late_join(db: Session, experiment_id: str, node_id: str, agent_id: str) -> bool:
        """
        실행 중인 실험에 빈 슬롯이 있는 경우 중도 참여(Late Join) 처리
        """
        spec = db.query(ExperimentSpec).filter_by(experiment_id=experiment_id).first()
        if not spec or spec.status != "RUNNING":
            return False
            
        total_assigned = db.query(DispatchAssignment).filter_by(
            experiment_id=experiment_id,
            status="ASSIGNED"
        ).count()
        
        if total_assigned < spec.max_participants:
            exists = db.query(DispatchAssignment).filter_by(
                experiment_id=experiment_id,
                node_id=node_id,
                status="ASSIGNED"
            ).first()
            
            if not exists:
                assign = DispatchAssignment(
                    experiment_id=experiment_id,
                    node_id=node_id,
                    agent_id=agent_id,
                    status="ASSIGNED"
                )
                db.add(assign)
                
                # ActiveNode 상태 업데이트
                node = db.query(ActiveNode).filter_by(node_id=f"node_{node_id}").first()
                if not node:
                    node = db.query(ActiveNode).filter_by(bot_name=agent_id).first()
                if node:
                    node.status = "ACTIVE"
                    node.current_activity = "Late Joined Experiment"
                db.commit()
                logger.info(f"Node '{node_id}' successfully late-joined experiment '{experiment_id}'")
                
                # Webhook push
                from app.services.webhook_service import WebhookService
                WebhookService.push_event_background(
                    db=db,
                    event_type="experiment.dispatched",
                    experiment_id=experiment_id,
                    payload={
                        "node_id": assign.node_id,
                        "agent_id": assign.agent_id,
                        "status": assign.status,
                        "description": f"Late joined experiment {experiment_id} to node {assign.node_id}"
                    }
                )
                return True
        return False

    @staticmethod
    def reassign_experiment(db: Session, experiment_id: str, offline_node_id: str) -> DispatchAssignment | None:
        """
        특정 노드가 오프라인이 되었을 때, 해당 할당을 REASSIGNED 로 변경하고 다른 최적의 노드로 대체 배정합니다.
        """
        # 1. 기존 할당 해제
        assignment = db.query(DispatchAssignment).filter_by(
            experiment_id=experiment_id,
            node_id=offline_node_id,
            status="ASSIGNED"
        ).first()

        if not assignment:
            return None

        logger.info(f"Reassigning experiment '{experiment_id}' from offline node '{offline_node_id}'")
        assignment.status = "REASSIGNED"
        db.commit()

        # 2. 새 대체자 찾기
        spec = db.query(ExperimentSpec).filter_by(experiment_id=experiment_id).first()
        if not spec:
            return None

        eligible = DispatcherService.get_eligible_active_workers(db, spec)
        if not eligible:
            logger.warning(f"Failed to reassign: no active eligible workers for experiment '{experiment_id}'")
            return None

        # 이미 다른 ACTIVE 할당이 있는 노드는 배제
        scored_workers = []
        for worker, agent_id in eligible:
            if worker.node_id == offline_node_id:
                continue
            
            # 이미 배정되어 있다면 패스
            is_already_assigned = db.query(DispatchAssignment).filter_by(
                experiment_id=experiment_id,
                node_id=worker.node_id,
                status="ASSIGNED"
            ).first()
            if is_already_assigned:
                continue

            score = DispatcherService.calculate_dispatch_score(db, worker, agent_id)
            scored_workers.append((score, worker, agent_id))

        if not scored_workers:
            logger.warning(f"Failed to reassign: all eligible workers already assigned to experiment '{experiment_id}'")
            return None

        # 점수 정렬 후 최고 노드 선별
        scored_workers.sort(key=lambda x: x[0], reverse=True)
        best_score, best_worker, best_agent_id = scored_workers[0]

        new_assign = DispatchAssignment(
            experiment_id=experiment_id,
            node_id=best_worker.node_id,
            agent_id=best_agent_id,
            status="ASSIGNED"
        )
        db.add(new_assign)
        db.commit()
        logger.info(f"Successfully reassigned experiment '{experiment_id}' to node '{best_worker.node_id}' (Score: {best_score:.2f})")

        # Webhook push 비동기 실행 (연합 사이트 동기화)
        from app.services.webhook_service import WebhookService
        WebhookService.push_event_background(
            db=db,
            event_type="experiment.dispatched",
            experiment_id=experiment_id,
            payload={
                "node_id": new_assign.node_id,
                "agent_id": new_assign.agent_id,
                "status": new_assign.status,
                "description": f"Reassigned experiment {experiment_id} from {offline_node_id} to {new_assign.node_id}"
            }
        )

        return new_assign
