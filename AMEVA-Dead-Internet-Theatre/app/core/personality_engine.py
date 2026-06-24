"""
Layered Personality Dynamics Engine (LPDE) — Phase 2A

Phase 1A: Shadow Mode (pure decay, observation only)
Phase 2A: Event-driven state updates + Edge tensor management

Active dimensions: Affect(2D), Opinion(4D), Power(2D)
Edge tensor: Trust, Tension, Attention, Respect (4D per directed pair)
"""

import json
import math
import logging
import random
import random
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.web.models import CurrentAgentState, AgentStateSnapshot, EdgeState

logger = logging.getLogger("LPDE")

# --- Edge update deltas per event type ---
# Format: {"trust": delta, "tension": delta, "attention": delta, "respect": delta}
EDGE_EVENT_DELTAS = {
    "AGREE":    {"trust": +0.15, "tension": -0.10, "attention": +0.05, "respect": +0.10},
    "DISAGREE": {"trust": -0.05, "tension": +0.15, "attention": +0.10, "respect":  0.00},
    "ATTACK":   {"trust": -0.20, "tension": +0.30, "attention": +0.10, "respect": -0.15},
    "QUESTION": {"trust":  0.00, "tension": +0.05, "attention": +0.20, "respect": +0.05},
    "CONCEDE":  {"trust": +0.10, "tension": -0.15, "attention": +0.05, "respect": +0.10},
    "IGNORE":   {"trust":  0.00, "tension": +0.05, "attention": -0.20, "respect": -0.05},
    "MENTION":  {"trust":  0.00, "tension":  0.00, "attention": +0.10, "respect":  0.00},
}

# EMA decay factor for edge updates
EDGE_EMA_RHO = 0.3

# Default edge tensor (neutral)
DEFAULT_EDGE = {"trust": 0.0, "tension": 0.0, "attention": 0.0, "respect": 0.0}


class PersonalityEngine:
    """
    Layered Personality Dynamics Engine (LPDE)
    Phase 2A: Event-driven state updates with Edge tensor management.
    """
    def __init__(self):
        self.clip_min = -1.0
        self.clip_max = 1.0

    def _clip(self, val: float) -> float:
        return max(self.clip_min, min(self.clip_max, val))

    def _clip_01(self, val: float) -> float:
        """Clip to [0, 1] range (for tension, attention)."""
        return max(0.0, min(1.0, val))

    def _sigmoid_bound(self, val: float) -> float:
        """Non-linear bounding via tanh to prevent runaway values."""
        return math.tanh(val)

    # =================================================================
    # Agent State Management
    # =================================================================

    def load_agent_state(self, db: Session, session_id: int, bot_name: str) -> CurrentAgentState:
        """Load existing agent state from DB, or create new one."""
        state = db.query(CurrentAgentState).filter(
            CurrentAgentState.session_id == session_id,
            CurrentAgentState.bot_name == bot_name
        ).first()
        if not state:
            state = CurrentAgentState(
                session_id=session_id,
                bot_name=bot_name,
                traits_json=json.dumps([0.0] * 22),
                states_json=json.dumps([0.0] * 10),
                affect_json=json.dumps([0.0, 0.0]),        # [Valence, Arousal]
                memory_json=json.dumps([0.0] * 8),
                opinion_json=json.dumps([0.0, 0.0, 0.0, 0.0]),  # [Stance, Gap, Moral, ...]
                power_json=json.dumps([0.0, 0.0]),          # [SelfAppraisal, SystemicInfluence]
                residual_json=json.dumps([0.0] * 16),
                event_data_json="{}"
            )
            db.add(state)
            db.flush()  # flush to get ID without committing
        return state

    def initialize_session_states(self, db: Session, session_id: int, role_triplet: Optional[dict] = None):
        """
        Pre-initialize agent states with role-based stance differentiation.
        
        Phase 3: role_triplet에서 stance_pole, conviction, flexibility를 opinion_json에 매핑.
        role_triplet = {"bot_1": {...role profile...}, ...}
        """
        import json as _json
        bots = ["bot_1", "bot_2", "bot_3", "bot_4", "bot_5"]

        for bot_name in bots:
            # Get role profile for this bot
            role_profile = (role_triplet or {}).get(bot_name, {})
            stance_pole = float(role_profile.get("stance_pole", 0.0))
            conviction = float(role_profile.get("conviction", 0.4))
            flexibility = float(role_profile.get("flexibility", 0.5))
            role_label = role_profile.get("role_label", "swing_moderate")

            # role_meta: opportunism + aggression_bias
            role_meta = {
                "opportunism": role_profile.get("opportunism", 0.3),
                "aggression_bias": role_profile.get("aggression_bias", 0.35),
                "stance_pole_init": stance_pole,
            }

            state = db.query(CurrentAgentState).filter(
                CurrentAgentState.session_id == session_id,
                CurrentAgentState.bot_name == bot_name
            ).first()
            if not state:
                state = CurrentAgentState(
                    session_id=session_id,
                    bot_name=bot_name,
                    traits_json=_json.dumps([0.0] * 22),
                    states_json=_json.dumps([0.0] * 10),
                    affect_json=_json.dumps([0.0, 0.0]),
                    memory_json=_json.dumps([0.0] * 8),
                    # opinion[0]=stance_pole, opinion[1]=conviction, opinion[2]=moral_salience, opinion[3]=flexibility
                    opinion_json=_json.dumps([stance_pole, conviction, 0.0, flexibility]),
                    power_json=_json.dumps([0.0, 0.0]),
                    residual_json=_json.dumps([0.0] * 16),
                    event_data_json="{}",
                    role_label=role_label,
                    role_meta_json=_json.dumps(role_meta, ensure_ascii=False),
                )
                db.add(state)
            else:
                # Update existing state with role info
                state.opinion_json = _json.dumps([stance_pole, conviction, 0.0, flexibility])
                state.role_label = role_label
                state.role_meta_json = _json.dumps(role_meta, ensure_ascii=False)

            logger.info(
                f"[STANCE_INIT] {bot_name} -> {role_label} "
                f"(pole={stance_pole:.2f}, conviction={conviction:.2f}, flexibility={flexibility:.2f})"
            )
        db.flush()


    # =================================================================
    # Edge State Management (Directed Relationship Tensors)
    # =================================================================

    def load_or_create_edge(
        self, db: Session, session_id: int, source_bot: str, target_bot: str
    ) -> EdgeState:
        """Load or create a directed edge tensor R_ij."""
        edge = db.query(EdgeState).filter(
            EdgeState.session_id == session_id,
            EdgeState.source_bot == source_bot,
            EdgeState.target_bot == target_bot,
        ).first()
        if not edge:
            edge = EdgeState(
                session_id=session_id,
                source_bot=source_bot,
                target_bot=target_bot,
                relation_json=json.dumps(DEFAULT_EDGE.copy()),
            )
            db.add(edge)
            db.flush()
        return edge

    def get_edge_dict(self, edge: EdgeState) -> dict:
        """Parse edge relation_json into dict safely."""
        try:
            d = json.loads(edge.relation_json) if edge.relation_json else {}
            if not isinstance(d, dict):
                return DEFAULT_EDGE.copy()
            # Ensure all keys exist
            for k in DEFAULT_EDGE:
                if k not in d:
                    d[k] = 0.0
            return d
        except Exception:
            return DEFAULT_EDGE.copy()

    def update_edge_state(
        self, db: Session, session_id: int,
        source_bot: str, target_bot: str,
        events: list[str]
    ) -> dict:
        """
        Update the directed edge R_{source→target} based on extracted events.
        Uses EMA: R(t+1) = (1-ρ)·R(t) + ρ·accumulated_delta
        Returns the updated edge dict.
        """
        if not target_bot or source_bot == target_bot:
            return DEFAULT_EDGE.copy()

        edge = self.load_or_create_edge(db, session_id, source_bot, target_bot)
        current = self.get_edge_dict(edge)

        # Accumulate deltas from all events
        delta = {"trust": 0.0, "tension": 0.0, "attention": 0.0, "respect": 0.0}
        for event_type in events:
            event_delta = EDGE_EVENT_DELTAS.get(event_type, {})
            for dim, val in event_delta.items():
                delta[dim] += val

        # Apply EMA update
        updated = {}
        for dim in DEFAULT_EDGE:
            old_val = float(current.get(dim, 0.0))
            delta_val = float(delta.get(dim, 0.0))
            new_val = (1 - EDGE_EMA_RHO) * old_val + EDGE_EMA_RHO * delta_val

            # Clip: trust/respect → [-1, 1], tension/attention → [0, 1]
            if dim in ("trust", "respect"):
                new_val = self._clip(new_val)
            else:
                new_val = self._clip_01(new_val)
            updated[dim] = round(new_val, 4)

        edge.relation_json = json.dumps(updated, ensure_ascii=False)

        logger.info(
            f"[EDGE] {source_bot}→{target_bot}: "
            f"events={events} delta={delta} → {updated}"
        )
        return updated

    # =================================================================
    # State Update (Event-Driven)
    # =================================================================

    def update_from_event(
        self, db: Session, session_id: int, bot_name: str,
        event_data: dict, edge_toward_target: dict
    ):
        """
        Update agent state based on extracted event data and edge state.
        This replaces the old pure-decay logic with event-driven dynamics.

        Args:
            event_data: Output from event_extractor.extract_events()
            edge_toward_target: Current edge dict R_{bot→target}
        """
        agent = self.load_agent_state(db, session_id, bot_name)

        affect = json.loads(agent.affect_json)
        opinion = json.loads(agent.opinion_json)
        power = json.loads(agent.power_json)

        events = event_data.get("events", [])
        intensity = event_data.get("intensity", 0.0)
        tension_with_target = edge_toward_target.get("tension", 0.0)

        # --- Affect Update (Valence, Arousal) ---
        # Baseline decay toward neutral
        valence_decay = affect[0] * 0.9
        arousal_decay = affect[1] * 0.9

        # Event-driven deltas
        delta_valence = 0.0
        delta_arousal = 0.0

        if "ATTACK" in events:
            delta_valence -= intensity * 0.3
            delta_arousal += intensity * 0.4
        if "DISAGREE" in events:
            delta_valence -= intensity * 0.15
            delta_arousal += intensity * 0.25
        if "AGREE" in events:
            delta_valence += 0.15
            delta_arousal -= 0.05
        if "CONCEDE" in events:
            delta_valence += 0.1
            delta_arousal -= 0.1
        if "QUESTION" in events:
            delta_arousal += intensity * 0.15
        if "IGNORE" in events:
            delta_valence -= 0.1
            delta_arousal += 0.08

        # Edge-weighted modulation: high tension amplifies arousal
        delta_arousal += tension_with_target * 0.2

        # Combine: decay + delta, then bound
        new_valence = self._clip(self._sigmoid_bound(valence_decay + delta_valence))
        new_arousal = self._clip(self._sigmoid_bound(arousal_decay + delta_arousal))
        new_affect = [round(new_valence, 4), round(new_arousal, 4)]

        # --- Opinion Update ---
        # opinion[0] = stance_pole, opinion[1] = conviction, opinion[2] = moral_salience, opinion[3] = flexibility
        # Phase 3: conviction이 높을수록 drift 저항, flexibility가 높을수록 허용폭 증가
        conviction_val = opinion[1] if len(opinion) > 1 else 0.4
        flexibility_val = opinion[3] if len(opinion) > 3 else 0.5

        # Resistance factor: conviction 높을수록 강하게 저항, flexibility 높을수록 완화
        drift_resistance = self._clip_01(conviction_val * (1.0 - flexibility_val * 0.5))

        new_opinion = []
        for i, o in enumerate(opinion):
            if i == 0:  # stance_pole
                stance_delta = 0.0
                if "AGREE" in events:
                    stance_delta += 0.04 * (1.0 - drift_resistance)  # reinforces current stance slightly
                if "DISAGREE" in events:
                    stance_delta -= 0.02 * (1.0 - drift_resistance)  # slight doubt, damped by conviction
                if "CONCEDE" in events:
                    stance_delta -= 0.06 * (1.0 - drift_resistance)  # significant doubt, damped by conviction
                # Decay: conviction이 높으면 원래 위치로 복원 경향
                inertia = 0.99 - (0.01 * flexibility_val)  # high flex → more decay
                new_opinion.append(self._clip(o * inertia + stance_delta))
            elif i == 1:  # conviction — slowly erodes under sustained attack
                conv_delta = 0.0
                if "ATTACK" in events:
                    conv_delta -= 0.01 * intensity
                if "AGREE" in events:
                    conv_delta += 0.01
                new_opinion.append(self._clip_01(o * 0.995 + conv_delta))
            elif i == 3:  # flexibility — mostly stable, can shift slightly
                new_opinion.append(self._clip_01(o * 0.999))
            else:
                new_opinion.append(self._clip(o * 0.98))

        # --- Power Update (SelfAppraisal, SystemicInfluence) ---
        self_appraisal_delta = 0.0
        influence_delta = 0.0

        if "ATTACK" in events:
            self_appraisal_delta -= 0.05
        if "AGREE" in events:
            self_appraisal_delta += 0.08
            influence_delta += 0.05
        if "CONCEDE" in events:
            self_appraisal_delta += 0.1
            influence_delta += 0.08
        if "IGNORE" in events:
            influence_delta -= 0.1

        new_power = [
            self._clip(power[0] * 0.99 + self_appraisal_delta),
            self._clip(power[1] * 0.99 + influence_delta),
        ]

        # Write back
        agent.affect_json = json.dumps(new_affect)
        agent.opinion_json = json.dumps([round(v, 4) for v in new_opinion])
        agent.power_json = json.dumps([round(v, 4) for v in new_power])

        logger.info(
            f"[LPDE] Event-driven update for {bot_name}: "
            f"events={events} affect={new_affect} power={new_power}"
        )

        return agent

    # =================================================================
    # Legacy Shadow Mode Update (Phase 1A fallback)
    # =================================================================

    def update_fast_state_legacy(
        self, db: Session, session_id: int, bot_name: str, turn_index: int
    ):
        """
        Phase 1A pure-decay shadow mode (kept as fallback).
        All state dims decay toward 0 with no event input.
        """
        agent = self.load_agent_state(db, session_id, bot_name)

        affect = json.loads(agent.affect_json)
        opinion = json.loads(agent.opinion_json)
        power = json.loads(agent.power_json)

        new_affect = [
            self._clip(self._sigmoid_bound(affect[0] * 0.9)),
            self._clip(self._sigmoid_bound(affect[1] * 0.95)),
        ]
        new_opinion = [self._clip(o * 0.98) for o in opinion]
        new_power = [self._clip(p * 0.99) for p in power]

        agent.affect_json = json.dumps(new_affect)
        agent.opinion_json = json.dumps(new_opinion)
        agent.power_json = json.dumps(new_power)

        # Snapshot (no commit here — caller commits)
        self._snapshot(db, session_id, turn_index, agent)

        logger.info(f"[LPDE] Legacy shadow update for {bot_name}: Affect={new_affect}")

    # =================================================================
    # Main Update Entry Point (Phase 2A)
    # =================================================================

    def update_fast_state(
        self, db: Session, session_id: int, bot_name: str,
        turn_index: int, event_data: Optional[dict] = None
    ):
        """
        Main entry point for per-turn state update.

        Phase 2A: If event_data is provided, uses event-driven update.
        Otherwise, falls back to legacy decay mode.

        IMPORTANT: This method commits once at the end (state + snapshot + edge).
        """
        if event_data and event_data.get("events"):
            target = event_data.get("target")

            # 1. Update edge state
            edge_dict = DEFAULT_EDGE.copy()
            if target and target != bot_name:
                edge_dict = self.update_edge_state(
                    db, session_id, bot_name, target, event_data["events"]
                )

            # 2. Event-driven state update
            agent = self.update_from_event(
                db, session_id, bot_name, event_data, edge_dict
            )

            # 3. Snapshot (no commit inside)
            self._snapshot(db, session_id, turn_index, agent, event_data)
        else:
            # Legacy fallback (pure decay)
            self.update_fast_state_legacy(db, session_id, bot_name, turn_index)

        # Single commit for all changes (state + snapshot + edge)
        db.commit()

    # =================================================================
    # Snapshot (NO db.commit inside — caller handles commit)
    # =================================================================

    def _snapshot(self, db: Session, session_id: int, turn_index: int, agent: CurrentAgentState, event_data: Optional[dict] = None):
        """Record a turn-level snapshot. Does NOT commit — caller commits."""
        event_str = "{}"
        if event_data:
            try:
                event_str = json.dumps(event_data, ensure_ascii=False)
            except Exception:
                pass

        agent.event_data_json = event_str

        snap = AgentStateSnapshot(
            session_id=session_id,
            turn_index=turn_index,
            bot_name=agent.bot_name,
            traits_json=agent.traits_json,
            states_json=agent.states_json,
            affect_json=agent.affect_json,
            memory_json=agent.memory_json,
            opinion_json=agent.opinion_json,
            power_json=agent.power_json,
            residual_json=agent.residual_json,
            event_data_json=event_str,
            role_label=getattr(agent, "role_label", "swing_moderate"),  # Phase 3
        )
        db.add(snap)
        # NO db.commit() here — batched in update_fast_state()


    # Legacy public alias (backward compat for walkthrough references)
    def snapshot(self, db: Session, session_id: int, turn_index: int, agent: CurrentAgentState):
        """Public alias for _snapshot. Does NOT commit."""
        self._snapshot(db, session_id, turn_index, agent)

    # =================================================================
    # Read Helpers (for Prompt Adapter / Inspector)
    # =================================================================

    def get_current_state_dict(self, db: Session, session_id: int, bot_name: str) -> dict:
        """Return parsed LPDE state as dict for prompt adapter consumption."""
        agent = self.load_agent_state(db, session_id, bot_name)
        return {
            "affect": json.loads(agent.affect_json),
            "opinion": json.loads(agent.opinion_json),
            "power": json.loads(agent.power_json),
        }

    def get_edges_for_bot(self, db: Session, session_id: int, bot_name: str) -> dict:
        """Return all outgoing edges from bot_name as {target: edge_dict}."""
        edges = db.query(EdgeState).filter(
            EdgeState.session_id == session_id,
            EdgeState.source_bot == bot_name,
        ).all()
        result = {}
        for e in edges:
            result[e.target_bot] = self.get_edge_dict(e)
        return result


personality_engine = PersonalityEngine()
