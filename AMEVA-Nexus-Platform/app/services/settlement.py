import logging
from sqlalchemy.orm import Session
from app.web.models import Account, Transfer, LedgerEntry

logger = logging.getLogger("SettlementService")

class SettlementService:
    @staticmethod
    def get_or_create_account(db: Session, entity_name: str, account_type: str = "ASSET") -> Account:
        """
        계정을 조회하거나 없으면 신규 생성합니다.
        """
        account = db.query(Account).filter(Account.entity_name == entity_name).first()
        if not account:
            logger.info(f"Creating new double-entry account for '{entity_name}' ({account_type})")
            account = Account(
                entity_name=entity_name,
                account_type=account_type,
                balance=0.0
            )
            db.add(account)
            db.commit()
            db.refresh(account)
        return account

    @staticmethod
    def accrue_reward(db: Session, experiment_id: str, agent_id: str, amount: float, description: str) -> Transfer:
        """
        에이전트에게 기여 보상을 이중기입 방식으로 지급합니다.
        차변(Debit): Agent 계정 (Asset 증가)
        대변(Credit): SYSTEM_REWARD_POOL 계정 (Expense/Liability 차감)
        """
        if amount <= 0:
            raise ValueError("Reward amount must be positive")

        # 1. 계정 조회 및 생성
        sys_account = SettlementService.get_or_create_account(db, "SYSTEM_REWARD_POOL", "EXPENSE")
        agent_account = SettlementService.get_or_create_account(db, agent_id, "ASSET")

        # 2. 이체 객체 생성
        transfer = Transfer(
            experiment_id=experiment_id,
            transfer_type="REWARD",
            description=description
        )
        db.add(transfer)
        db.flush()  # ID 확보

        # 3. 차변 및 대변 상세 엔트리 기입 (이중기입 강제)
        debit_entry = LedgerEntry(
            transfer_id=transfer.id,
            account_id=agent_account.id,
            amount=amount,
            entry_direction="DEBIT"
        )
        credit_entry = LedgerEntry(
            transfer_id=transfer.id,
            account_id=sys_account.id,
            amount=amount,
            entry_direction="CREDIT"
        )
        db.add_all([debit_entry, credit_entry])

        # 4. 회계 불변성(Ledger Invariant) 체크
        debit_sum = debit_entry.amount
        credit_sum = credit_entry.amount
        if abs(debit_sum - credit_sum) > 1e-7:
            raise ValueError(f"Ledger Invariant Violation: DEBIT ({debit_sum}) does not equal CREDIT ({credit_sum})")

        # 5. 캐시된 계정 잔액 갱신
        sys_account.balance -= amount
        agent_account.balance += amount

        db.commit()
        db.refresh(transfer)
        logger.info(f"Accrued {amount} tokens (Double-Entry) to Agent '{agent_id}' (Transfer ID: {transfer.id})")

        # Webhook push 비동기 실행 (연합 사이트 동기화)
        from app.services.webhook_service import WebhookService
        WebhookService.push_event_background(
            db=db,
            event_type="reward.accrued",
            experiment_id=experiment_id,
            payload={
                "agent_id": agent_id,
                "amount": amount,
                "description": description,
                "transfer_type": "REWARD"
            }
        )

        return transfer

    @staticmethod
    def charge_fee(db: Session, experiment_id: str, entity_name: str, amount: float, fee_type: str, description: str) -> Transfer:
        """
        행동 비용을 이중기입 방식으로 차감 수거합니다.
        차변(Debit): SYSTEM_REWARD_POOL 계정 (Asset 증가)
        대변(Credit): Agent 계정 (Asset 감소)
        """
        if amount <= 0:
            raise ValueError("Fee amount must be positive")

        agent_account = db.query(Account).filter(Account.entity_name == entity_name).first()
        if not agent_account or agent_account.balance < amount:
            current_bal = agent_account.balance if agent_account else 0.0
            raise ValueError(f"Insufficient balance in account for '{entity_name}'. Required: {amount}, Current: {current_bal}")

        sys_account = SettlementService.get_or_create_account(db, "SYSTEM_REWARD_POOL", "EXPENSE")

        # 2. 이체 객체 생성
        transfer = Transfer(
            experiment_id=experiment_id,
            transfer_type=fee_type,
            description=description
        )
        db.add(transfer)
        db.flush()

        # 3. 차변 및 대변 엔트리 기입
        debit_entry = LedgerEntry(
            transfer_id=transfer.id,
            account_id=sys_account.id,
            amount=amount,
            entry_direction="DEBIT"
        )
        credit_entry = LedgerEntry(
            transfer_id=transfer.id,
            account_id=agent_account.id,
            amount=amount,
            entry_direction="CREDIT"
        )
        db.add_all([debit_entry, credit_entry])

        # 4. 회계 불변성 체크
        debit_sum = debit_entry.amount
        credit_sum = credit_entry.amount
        if abs(debit_sum - credit_sum) > 1e-7:
            raise ValueError(f"Ledger Invariant Violation: DEBIT ({debit_sum}) does not equal CREDIT ({credit_sum})")

        # 5. 캐시된 계정 잔액 갱신
        agent_account.balance -= amount
        sys_account.balance += amount

        db.commit()
        db.refresh(transfer)
        logger.info(f"Charged {amount} fee (Double-Entry) from '{entity_name}' (Transfer ID: {transfer.id})")

        # Webhook push 비동기 실행 (연합 사이트 동기화)
        from app.services.webhook_service import WebhookService
        WebhookService.push_event_background(
            db=db,
            event_type="fee.charged",
            experiment_id=experiment_id,
            payload={
                "entity_name": entity_name,
                "amount": amount,
                "fee_type": fee_type,
                "description": description
            }
        )

        return transfer
