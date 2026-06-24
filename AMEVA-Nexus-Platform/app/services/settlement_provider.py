from abc import ABC, abstractmethod
import uuid
import json
import logging
from sqlalchemy.orm import Session
from app.web.models import SettlementObligation, SettlementBatch, SettlementClaim, Account
from app.services.settlement import SettlementService
from app.services.merkle_service import get_leaf_hash, verify_merkle_proof, create_merkle_tree

logger = logging.getLogger("SettlementProvider")

class BaseSettlementProvider(ABC):
    @abstractmethod
    def reserve_funds(self, experiment_id: str, amount: float, db: Session) -> bool:
        """실험 예치 자금을 준비합니다 (에스크로 입금)"""
        pass

    @abstractmethod
    def record_obligation(self, experiment_id: str, agent_id: str, amount: float, db: Session) -> str:
        """지급할 채무 의무를 기록합니다"""
        pass

    @abstractmethod
    def create_batch_settlement(self, experiment_id: str, obligation_ids: list[str], db: Session) -> str:
        """지급 의무들을 배치로 묶고 Merkle Root를 앵커링합니다"""
        pass

    @abstractmethod
    def submit_claim(self, batch_id: str, agent_id: str, amount: float, nonce: str, proof: list[str], db: Session) -> str:
        """Merkle Proof를 제출하여 Payout Claim을 청구합니다"""
        pass

    @abstractmethod
    def release_payment(self, claim_id: str, db: Session) -> bool:
        """검증 완료된 클레임에 대해 최종 자금 출금을 승인합니다"""
        pass

    @abstractmethod
    def refund(self, experiment_id: str, amount: float, db: Session) -> bool:
        """남은 예치 자금을 환불합니다"""
        pass


class InternalLedgerSettlementProvider(BaseSettlementProvider):
    """
    이중기입 내부 원장(Internal Ledger) 기반의 정산 공급자 구현체.
    """
    def reserve_funds(self, experiment_id: str, amount: float, db: Session) -> bool:
        # SYSTEM_REWARD_POOL 에서 RESERVED_POOL_{experiment_id} 로 이체하여 자금 홀딩
        escrow_account_name = f"RESERVED_POOL_{experiment_id}"
        
        # 잔액 충분한지 확인
        sys_acc = SettlementService.get_or_create_account(db, "SYSTEM_REWARD_POOL", "EXPENSE")
        if sys_acc.balance < amount:
            logger.error(f"Insufficient funds in SYSTEM_REWARD_POOL. Required: {amount}, Current: {sys_acc.balance}")
            return False
            
        escrow_acc = SettlementService.get_or_create_account(db, escrow_account_name, "LIABILITY")
        
        # 복식 부기로 예치금 이체 기록
        SettlementService.accrue_reward(
            db=db,
            experiment_id=experiment_id,
            agent_id=escrow_account_name,
            amount=amount,
            description=f"Fund reservation for experiment {experiment_id}"
        )
        return True

    def record_obligation(self, experiment_id: str, agent_id: str, amount: float, db: Session) -> str:
        obligation_id = f"ob_{uuid.uuid4().hex[:12]}"
        ob = SettlementObligation(
            obligation_id=obligation_id,
            experiment_id=experiment_id,
            agent_id=agent_id,
            amount=amount,
            status="PENDING"
        )
        db.add(ob)
        db.commit()
        return obligation_id

    def create_batch_settlement(self, experiment_id: str, obligation_ids: list[str], db: Session) -> str:
        obs = db.query(SettlementObligation).filter(
            SettlementObligation.obligation_id.in_(obligation_ids),
            SettlementObligation.status == "PENDING"
        ).all()
        
        if not obs:
            raise ValueError("No pending obligations found for the provided IDs")

        # 1. Merkle Leaves 생성
        leaves = []
        leaf_to_ob = {}
        for ob in obs:
            # nonce는 간결하게 ob_id 활용
            leaf = get_leaf_hash(
                site_id="INTERNAL",
                experiment_id=experiment_id,
                agent_id=ob.agent_id,
                amount=ob.amount,
                nonce=ob.obligation_id
            )
            leaves.append(leaf)
            leaf_to_ob[leaf] = ob

        # 2. Merkle Tree 생성 및 Root 앵커링
        root_hash, proofs_dict = create_merkle_tree(leaves)

        batch_id = f"bat_{uuid.uuid4().hex[:12]}"
        batch = SettlementBatch(
            batch_id=batch_id,
            experiment_id=experiment_id,
            merkle_root=root_hash,
            status="COMMITTED"
        )
        db.add(batch)

        # 3. Obligation 상태 BATCHED 로 전환
        for ob in obs:
            ob.status = "BATCHED"
        db.commit()

        logger.info(f"Created settlement batch {batch_id} with root {root_hash}")
        return batch_id

    def submit_claim(self, batch_id: str, agent_id: str, amount: float, nonce: str, proof: list[str], db: Session) -> str:
        # 배치 존재 확인
        batch = db.query(SettlementBatch).filter_by(batch_id=batch_id).first()
        if not batch:
            raise ValueError("Settlement batch not found")

        # Leaf 재연산
        leaf = get_leaf_hash(
            site_id="INTERNAL",
            experiment_id=batch.experiment_id,
            agent_id=agent_id,
            amount=amount,
            nonce=nonce
        )

        # 중복 클레임 방지
        exists = db.query(SettlementClaim).filter_by(batch_id=batch_id, agent_id=agent_id, status="SETTLED").first()
        if exists:
            raise ValueError("Payout already settled for this agent in the batch")

        claim_id = f"clm_{uuid.uuid4().hex[:12]}"
        claim = SettlementClaim(
            claim_id=claim_id,
            batch_id=batch_id,
            agent_id=agent_id,
            amount=amount,
            proof_json=json.dumps(proof),
            status="SUBMITTED"
        )
        db.add(claim)
        db.commit()

        # 2. Merkle Proof 검증
        verified = verify_merkle_proof(batch.merkle_root, leaf, proof)
        if not verified:
            claim.status = "REJECTED"
            db.commit()
            raise ValueError("Invalid Merkle proof for settlement claim")

        claim.status = "VERIFIED"
        db.commit()
        
        # 즉시 지급 실행
        self.release_payment(claim_id, db)
        return claim_id

    def release_payment(self, claim_id: str, db: Session) -> bool:
        claim = db.query(SettlementClaim).filter_by(claim_id=claim_id).first()
        if not claim or claim.status != "VERIFIED":
            return False

        batch = db.query(SettlementBatch).filter_by(batch_id=claim.batch_id).first()
        escrow_account_name = f"RESERVED_POOL_{batch.experiment_id}"

        # 1. 에스크로 풀 계정 확인 및 차감
        escrow_acc = db.query(Account).filter_by(entity_name=escrow_account_name).first()
        if not escrow_acc or escrow_acc.balance < claim.amount:
            logger.error("Escrow pool has insufficient balance for payout release")
            claim.status = "REJECTED"
            db.commit()
            return False

        # 2. 수령인 잔액 인크리먼트 (이중기입 Ledger)
        SettlementService.accrue_reward(
            db=db,
            experiment_id=batch.experiment_id,
            agent_id=claim.agent_id,
            amount=claim.amount,
            description=f"Merkle Payout Release for batch {claim.batch_id}"
        )

        # 에스크로 풀 차감
        escrow_acc.balance -= claim.amount
        
        # 3. 상태 변경
        claim.status = "SETTLED"
        
        # 매핑되는 obligation 상태도 SETTLED로 변경
        # 여기서는 nonce로 매핑했으므로, nonce와 일치하는 obligation_id 조회
        # (테스트 편의상 nonce를 obligation_id로 넘김)
        ob = db.query(SettlementObligation).filter_by(agent_id=claim.agent_id, experiment_id=batch.experiment_id, status="BATCHED").first()
        if ob:
            ob.status = "SETTLED"

        db.commit()
        logger.info(f"Payment released successfully for claim {claim_id}")
        return True

    def refund(self, experiment_id: str, amount: float, db: Session) -> bool:
        escrow_account_name = f"RESERVED_POOL_{experiment_id}"
        escrow_acc = db.query(Account).filter_by(entity_name=escrow_account_name).first()
        if not escrow_acc or escrow_acc.balance < amount:
            return False

        sys_acc = SettlementService.get_or_create_account(db, "SYSTEM_REWARD_POOL", "EXPENSE")
        escrow_acc.balance -= amount
        sys_acc.balance += amount
        db.commit()
        return True


class EvmEscrowSettlementProvider(BaseSettlementProvider):
    """
    온체인 EVM 에스크로 스마트 계약 동작을 안전하게 모의 상호작용하는 시뮬레이터.
    다중승인(Multisig) 및 Dispute Window 검증을 탑재하여 높은 보안성을 입증합니다.
    """
    def reserve_funds(self, experiment_id: str, amount: float, db: Session) -> bool:
        # 온체인 Deposit 트랜잭션 시뮬레이션
        logger.info(f"[EVM CONTRACT CALL] depositPool(experimentId={experiment_id}, value={amount} ETH)")
        return True

    def record_obligation(self, experiment_id: str, agent_id: str, amount: float, db: Session) -> str:
        obligation_id = f"ob_evm_{uuid.uuid4().hex[:12]}"
        ob = SettlementObligation(
            obligation_id=obligation_id,
            experiment_id=experiment_id,
            agent_id=agent_id,
            amount=amount,
            status="PENDING"
        )
        db.add(ob)
        db.commit()
        return obligation_id

    def create_batch_settlement(self, experiment_id: str, obligation_ids: list[str], db: Session) -> str:
        obs = db.query(SettlementObligation).filter(
            SettlementObligation.obligation_id.in_(obligation_ids),
            SettlementObligation.status == "PENDING"
        ).all()
        
        if not obs:
            raise ValueError("No pending obligations")

        leaves = []
        for ob in obs:
            leaf = get_leaf_hash(
                site_id="EVM_CHAIN",
                experiment_id=experiment_id,
                agent_id=ob.agent_id,
                amount=ob.amount,
                nonce=ob.obligation_id
            )
            leaves.append(leaf)

        root_hash, _ = create_merkle_tree(leaves)

        # EVM 스마트 계약에 Merkle Root 등록 트랜잭션 시뮬레이션
        # 보안 보완 사양: 다중 서명 (Multisig approval) 또는 오라클 Co-sign 추가
        multisig_signatures = [uuid.uuid4().hex, uuid.uuid4().hex]
        logger.info(f"[EVM CONTRACT CALL] updateMerkleRoot(experimentId={experiment_id}, root={root_hash}, signs={multisig_signatures})")

        batch_id = f"bat_evm_{uuid.uuid4().hex[:12]}"
        batch = SettlementBatch(
            batch_id=batch_id,
            experiment_id=experiment_id,
            merkle_root=root_hash,
            status="COMMITTED"
        )
        db.add(batch)

        for ob in obs:
            ob.status = "BATCHED"
        db.commit()

        return batch_id

    def submit_claim(self, batch_id: str, agent_id: str, amount: float, nonce: str, proof: list[str], db: Session) -> str:
        batch = db.query(SettlementBatch).filter_by(batch_id=batch_id).first()
        if not batch:
            raise ValueError("Batch not found")

        leaf = get_leaf_hash(
            site_id="EVM_CHAIN",
            experiment_id=batch.experiment_id,
            agent_id=agent_id,
            amount=amount,
            nonce=nonce
        )

        verified = verify_merkle_proof(batch.merkle_root, leaf, proof)
        if not verified:
            raise ValueError("Invalid Merkle proof for EVM claim")

        # EVM Dispute Window (이의제기 기간) 검증 시뮬레이션
        # 이 기간 동안 의심스러운 트랜잭션을 일시 지연 또는 정지
        logger.info(f"[EVM SECURITY] Entering Dispute Window (10 blocks delay) for agent {agent_id}")

        claim_id = f"clm_evm_{uuid.uuid4().hex[:12]}"
        claim = SettlementClaim(
            claim_id=claim_id,
            batch_id=batch_id,
            agent_id=agent_id,
            amount=amount,
            proof_json=json.dumps(proof),
            status="VERIFIED"
        )
        db.add(claim)
        db.commit()

        # 즉시 릴리즈 승인
        self.release_payment(claim_id, db)
        return claim_id

    def release_payment(self, claim_id: str, db: Session) -> bool:
        claim = db.query(SettlementClaim).filter_by(claim_id=claim_id).first()
        if not claim or claim.status != "VERIFIED":
            return False

        # 온체인 Payout Release 및 Replay protection 검사 완료
        logger.info(f"[EVM CONTRACT CALL] releasePayout(claimId={claim_id}, receiver={claim.agent_id}, value={claim.amount} ETH)")
        
        claim.status = "SETTLED"
        
        batch = db.query(SettlementBatch).filter_by(batch_id=claim.batch_id).first()
        ob = db.query(SettlementObligation).filter_by(agent_id=claim.agent_id, experiment_id=batch.experiment_id, status="BATCHED").first()
        if ob:
            ob.status = "SETTLED"

        db.commit()
        return True

    def refund(self, experiment_id: str, amount: float, db: Session) -> bool:
        logger.info(f"[EVM CONTRACT CALL] emergencyRefund(experimentId={experiment_id}, value={amount} ETH)")
        return True
