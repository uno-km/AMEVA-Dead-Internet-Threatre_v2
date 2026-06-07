# AMEVA-DeadInternetSociety

A multi-agent debate simulation system utilizing Latent Personality Dynamics Engine (LPDE) to simulate toxic internet behaviors and emotional keyboard warriors.

## Phase 2: Real-time LPDE Engine

The system is currently running in **Phase 2**, where the Latent Personality Dynamics Engine (LPDE) actively drives the agents' actions and replies, rather than acting as a shadow observer. 

### Key Features
- **Event-Driven Edge State**: Relations (trust, tension) between bots are dynamically updated based on comment events (AGREE, DISAGREE, ATTACK, MENTION, etc.).
- **God LLM Interventions**: The director (God LLM) uses JSON deltas to perturb agents' internal state vectors directly (e.g. `{"kind": "stir", "delta": {"affect": [0.0, 0.3]}}`) when the debate stalls.
- **Compressed State Tags**: For 1.8B models, complex emotional states are compressed into short system tags (e.g., `[SYS_STATE: bot_1|ANG:85(ENRAGED)|TGT:bot_2:15]`) rather than lengthy verbal descriptions.
- **Strict Single Source of Truth**: The LPDE full prompt adapter is the single path for context building. Legacy shadow-mode branches have been removed.

### Architecture Limitations & Future Optimizations
1. **Shared Crowd Model**: Currently, `docker-compose.yml` runs multiple Qwen-1.8B instances for each bot. A future optimization should consolidate this into a single shared inference container that handles all crowd-bot requests sequentially, saving VRAM.
2. **Edge Snapshots**: `EdgeState` is only stored as its latest version (`updated_at`). For deeper analytics, historical EdgeState snapshots (similar to `AgentStateSnapshot`) should be implemented in the future.
3. **Event Schema**: Temporary workaround `residual_json` is used in `CurrentAgentState` to pass event data to the inspector API. This requires a proper database schema migration (`event_data_json`) in the future.
4. **Intervention Policy**: The current intervention logic (God LLM) triggers based on simple deterministic thresholds (e.g., tension > 0.6). A more sophisticated semantic or reinforcement learning-based policy is needed for Phase 3.

### System Components
- **API (FastAPI)**: UI and system control (`run.py`).
- **Runner**: Orchestrates turns, invokes LLMs, and handles interventions.
- **Sanitizer**: Cleans up model outputs, removing generated prefixes and leaked directives.
- **Prompt Adapter**: Bridges numerical LPDE states into NL prompts and structured history gists.
- **Personality Engine**: Core LPDE logic for personality dimensions (Affect, Opinion, Power, Edges).
