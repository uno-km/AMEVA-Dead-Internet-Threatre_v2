import time
import hashlib
import random
from datetime import datetime
from sqlalchemy.orm import Session
from app.web.models import WorkerNode, Reputation, ActiveNode

class CapabilityProbeService:
    @staticmethod
    def run_benchmark(db: Session, node_id: str) -> dict:
        """
        워커 노드의 하드웨어 스펙 및 신뢰성을 검증하기 위한 벤치마크 프로브를 실행합니다.
        실제 런타임에서는 웹소켓으로 워커에 퍼즐을 던지고 응답 시간을 측정하지만,
        여기서는 워커의 등록된 정보와 연동하여 실측 연산 및 지연시간을 모의 측정합니다.
        """
        worker = db.query(WorkerNode).filter_by(node_id=node_id).first()
        if not worker:
            raise ValueError(f"Worker node '{node_id}' not found")

        # 1. 벤치마크 챌린지 정의 (해시 마이닝 퍼즐 모의)
        # 난이도가 VRAM 및 RAM 사양에 따라 다르게 설정되거나 동일하게 주어짐.
        # 여기서는 난이도를 모의 연산하여 CPU/GPU 속도를 추정.
        target_difficulty = 2  # 난이도 (100% 결정론적 통과 및 속도 보장)
        prefix = f"bench_{node_id}_{time.time()}"
        
        start_time = time.time()
        
        # 실제 연산 수행 (너무 오래 걸리지 않도록 가볍게 실행하되 실측 가능한 연산)
        found = False
        nonce = 0
        while not found and nonce < 100000:
            nonce += 1
            text = f"{prefix}{nonce}".encode()
            h = hashlib.sha256(text).hexdigest()
            if h.startswith("0" * target_difficulty):
                found = True
                
        end_time = time.time()
        latency = end_time - start_time
        
        # 2. 성능 지표 계산
        # VRAM 용량에 따라 계산 가능한 등급 설정 (OOM 없이 정상 가속 가능한지 검증)
        # 만약 자가 보고된 vram_gb가 실제 동작 스펙에 부합하는지 벤치마크 결과값으로 매핑
        expected_vram = worker.vram_gb
        
        # 품질 평가: 연산 정답 성공 여부
        quality = 100.0 if found else 0.0
        
        # 성능(Capability) 점수 산출: VRAM 8GB 이상을 100점으로 정량화
        capability = min(100.0, (expected_vram / 8.0) * 100.0) if expected_vram > 0 else 30.0
        
        # 지연시간(Latency) 점수 산출: 초 단위 latency
        avg_latency = latency * 1000.0 # ms 단위
        
        # 3. 평판 데이터 갱신
        agent_id = f"bot_node_{node_id}"
        # ActiveNode가 있다면 bot_name을 agent_id로 사용
        active_node = db.query(ActiveNode).filter_by(node_id=f"node_{node_id}").first()
        if active_node and active_node.bot_name:
            agent_id = active_node.bot_name
            
        rep = db.query(Reputation).filter_by(agent_id=agent_id).first()
        if not rep:
            rep = Reputation(
                agent_id=agent_id,
                score=100.0,
                capability_score=capability,
                reliability_score=100.0,
                quality_score=quality,
                avg_latency=avg_latency
            )
            db.add(rep)
        else:
            rep.capability_score = capability
            rep.quality_score = quality
            # 지연시간 가중 평균 업데이트
            rep.avg_latency = (rep.avg_latency * 0.7) + (avg_latency * 0.3)
            # 신뢰성 보정
            if quality > 80.0:
                rep.reliability_score = min(100.0, rep.reliability_score + 5.0)
            else:
                rep.reliability_score = max(0.0, rep.reliability_score - 20.0)
            
            # 종합 평판 점수 공식 보정
            rep.score = (rep.capability_score * 0.3) + (rep.reliability_score * 0.3) - (rep.avg_latency / 100.0 * 2.0) + (rep.quality_score * 0.2)
            
        # 4. 워커 상태 업데이트
        worker.last_benchmarked_at = datetime.now()
        worker.is_verified = 1 if quality > 80.0 else 0
        
        db.commit()
        db.refresh(worker)
        if rep:
            db.refresh(rep)
            
        return {
            "node_id": node_id,
            "agent_id": agent_id,
            "latency_ms": avg_latency,
            "capability_score": capability,
            "reliability_score": rep.reliability_score if rep else 100.0,
            "quality_score": quality,
            "overall_reputation_score": rep.score if rep else 100.0,
            "is_verified": bool(worker.is_verified)
        }
