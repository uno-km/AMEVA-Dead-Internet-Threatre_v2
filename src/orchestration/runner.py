import asyncio
import logging
import random
import re
import json
import math
from datetime import datetime
from src.db.database import SessionLocal
from src.db.models import Session, Post, Comment, BotState
from src.core.llm_client import LLMClient
from src.core.persona import PersonaManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Orchestrator")

main_llm = LLMClient("http://llm-main:8080")
police_llm = LLMClient("http://llm-police:8080")
god_llm = LLMClient("http://llm-god:8080")

bots = {
    "bot_1": LLMClient("http://llm-bot-1:8080"),
    "bot_2": LLMClient("http://llm-bot-2:8080"),
    "bot_3": LLMClient("http://llm-bot-3:8080")
}

def reset_bot_states(db):
    states = db.query(BotState).all()
    for s in states:
        s.anger_targets = "{}"
    db.commit()

def calculate_effective_anger(anger_dict: dict) -> float:
    """Calculate vector magnitude of anger."""
    if not anger_dict:
        return 0.0
    sum_sq = sum(val ** 2 for val in anger_dict.values())
    return math.sqrt(sum_sq)

async def evaluate_spectator_anger(speaker: str, comment_text: str, spectators: list) -> dict:
    """God LLM evaluates targeted anger increases for the spectators."""
    logger.info(f"[ROUTING] Sending context to God LLM for Targeted Anger Matrix...")
    
    spec_1, spec_2 = spectators[0], spectators[1]
    
    prompt = (
        f"너는 갈등과 폭력을 조장하는 악마 같은 심리 분석 AI다.\n"
        f"방금 {speaker}가 다음과 같이 발언했다:\n\"{comment_text}\"\n\n"
        f"이 발언을 지켜본 관전자 {spec_1}과(와) {spec_2}가 각각 {speaker}를 향해 얼마나 분노를 느낄지 0에서 20 사이의 증가치로 평가해라.\n"
        f"반드시 아래 JSON 형식으로만 대답해라. 절대 다른 말은 추가하지 마라.\n"
        f"{{\"{spec_1}\": {{\"target\": \"{speaker}\", \"increase\": 10}}, \"{spec_2}\": {{\"target\": \"{speaker}\", \"increase\": 5}}}}"
    )
    
    result = await god_llm.generate_completion("너는 갈등을 조장하는 평가자다.", prompt, max_tokens=100)
    
    try:
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            out = {}
            for k in [spec_1, spec_2]:
                if k in data and "increase" in data[k] and "target" in data[k]:
                    val = min(max(int(data[k]["increase"]), 0), 20)
                    out[k] = {"target": data[k]["target"], "increase": val}
            logger.info(f"[GOD LLM] Targeted Anger Evaluated: {out}")
            return out
    except Exception as e:
        logger.error(f"[GOD LLM] Failed to parse targeted JSON: {result} | Error: {e}")
        
    logger.info("[GOD LLM] Fallback to +0 for spectators")
    return {spec_1: {"target": speaker, "increase": 0}, spec_2: {"target": speaker, "increase": 0}}

async def check_police_dispatch(db) -> bool:
    """Check if 2 or more bots have Effective Anger >= 100"""
    states = db.query(BotState).all()
    angry_count = sum(1 for s in states if calculate_effective_anger(json.loads(s.anger_targets)) >= 100)
    return angry_count >= 2

def get_next_speaker(db, last_speaker: str, last_mentioned: str) -> str:
    """Interrupt Logic: Determine who speaks next based on mentions and anger magnitude."""
    states = db.query(BotState).all()
    
    anger_info = {}
    for s in states:
        anger_dict = json.loads(s.anger_targets)
        anger_info[s.bot_name] = calculate_effective_anger(anger_dict)
        
    candidates = [b for b in bots.keys() if b != last_speaker]
    
    # Sort candidates by effective anger
    candidates.sort(key=lambda x: anger_info[x], reverse=True)
    angriest_bot = candidates[0]
    angriest_score = anger_info[angriest_bot]
    
    # Interrupt Logic
    if last_mentioned in candidates:
        mentioned_score = anger_info[last_mentioned]
        # If the angriest bot is NOT the mentioned bot, and their anger is >= 50 AND higher than mentioned bot
        if angriest_bot != last_mentioned and angriest_score >= 50 and angriest_score > mentioned_score:
            logger.info(f"[INTERRUPT] {angriest_bot} (Anger: {angriest_score:.1f}) hijacks turn from {last_mentioned} (Anger: {mentioned_score:.1f})!")
            return angriest_bot
        else:
            logger.info(f"[QUEUE] {last_mentioned} takes their turn as mentioned.")
            return last_mentioned
    else:
        # Fallback if mention is missing or invalid
        logger.info(f"[QUEUE] Fallback to angriest bot: {angriest_bot}")
        return angriest_bot

def build_emotion_prompt(bot_name: str, anger_targets: dict, effective_anger: float) -> str:
    target_str = ", ".join([f"{k}: {v}" for k, v in anger_targets.items()])
    if not target_str:
        target_str = "없음"
        
    base_info = f"[나의 감정 상태]\n나의 총합 유효 분노: {effective_anger:.1f}\n나의 타겟별 분노치: {target_str}\n"
    
    if effective_anger < 30:
        directive = "너는 현재 차분한 상태다. 논리적으로 이야기하며 싸움을 말려라."
    elif effective_anger < 70:
        directive = "너는 꽤 화가 난 상태다. 너를 화나게 한 타겟 봇을 신랄하게 비판해라."
    else:
        directive = "너는 현재 극대노 상태다. 타겟 봇에게 원색적인 비난과 조롱을 쏟아부어라."
        
    return base_info + directive

def extract_mention(text: str) -> str:
    """Extract @bot_1, @bot_2, @bot_3 from text."""
    for b in ["bot_1", "bot_2", "bot_3"]:
        if f"@{b}" in text:
            return b
    return None

async def run_session():
    db = SessionLocal()
    try:
        logger.info("==================================================")
        logger.info("[ORCHESTRATOR] [SESSION START] Initializing new session.")
        logger.info("==================================================")
        
        reset_bot_states(db)
        await PersonaManager.reset_personas()
        
        session = Session(status="ACTIVE")
        db.add(session)
        db.commit()
        db.refresh(session)
        
        # 1. Main LLM writes a post
        logger.info("[ROUTING] Requesting llm-main (8B) to generate a new topic...")
        post_content = await main_llm.generate_completion(
            "너는 커뮤니티의 익명 게시글 작성자다. 무작위의 논쟁적인 주제로 짧은 글을 하나 작성해라. 한국어로만 작성해라.",
            "새로운 글을 작성해줘.",
            max_tokens=300
        )
        if not post_content:
            post_content = "오늘 날씨가 참 좋네요. 다들 어떻게 지내시나요?"
        
        post = Post(session_id=session.id, title="새로운 논쟁 거리", content=post_content)
        db.add(post)
        db.commit()
        db.refresh(post)
        
        # 2. Police Bot approves
        logger.info(f"[ROUTING] Requesting llm-police (1.5B) to approve the post...")
        police_content = f"이 게시글은 검열을 통과했습니다. 모두 자신의 첫 입장을 표명하십시오."
        
        police_comment = Comment(post_id=post.id, bot_name="police", content=police_content)
        db.add(police_comment)
        db.commit()
        db.refresh(police_comment)
        
        # 3. Phase 1: All bots state their first stance
        logger.info("[PHASE 1] Initial Stance Declaration")
        for b_name in ["bot_1", "bot_2", "bot_3"]:
            await asyncio.sleep(3)
            persona = await PersonaManager.get_persona(b_name)
            bot_client = bots[b_name]
            prompt = f"게시글 내용: {post.content}\n\n이 게시글에 대한 너의 가장 솔직하고 확고한 첫 의견을 한국어로 남겨라."
            
            reply_content = await bot_client.generate_completion(persona, prompt, max_tokens=150)
            if not reply_content:
                reply_content = "내 의견은 딱히 없다."
                
            c = Comment(post_id=post.id, parent_id=police_comment.id, bot_name=b_name, content=reply_content)
            db.add(c)
            db.commit()
            logger.info(f"[{b_name.upper()}] Initial Stance: {reply_content}")
            
        # 4. Phase 2: Interruption & Mention Battle
        logger.info("[PHASE 2] Targeted Anger Battle Started")
        
        last_speaker = "bot_3"
        last_mentioned = "bot_1" # Default starting
        parent_comment_id = c.id
        
        for turn_idx in range(20):
            await asyncio.sleep(5) 
            
            current_bot = get_next_speaker(db, last_speaker, last_mentioned)
            
            logger.info(f"--- TURN {turn_idx+1}: {current_bot.upper()} ---")
            persona = await PersonaManager.get_persona(current_bot)
            bot_client = bots[current_bot]
            bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()
            
            anger_dict = json.loads(bot_state.anger_targets)
            eff_anger = calculate_effective_anger(anger_dict)
            emotion_directive = build_emotion_prompt(current_bot, anger_dict, eff_anger)
            
            recent_c = db.query(Comment).filter(Comment.post_id == post.id).order_by(Comment.id.desc()).limit(3).all()
            recent_history = "\n".join([f"{c.bot_name}: {c.content}" for c in reversed(recent_c)])
            
            prompt = (
                f"게시글 내용: {post.content}\n\n"
                f"최근 대화:\n{recent_history}\n\n"
                f"{emotion_directive}\n"
                f"반드시 한국어로 댓글을 달아라. 반드시 글 마지막에 발언을 넘길 봇을 '@bot_1', '@bot_2', '@bot_3' 중 하나로 멘션해서 지목해라."
            )
            
            reply_content = await bot_client.generate_completion(persona, prompt, max_tokens=150)
            
            if not reply_content:
                reply_content = "화가 나서 할 말이 없다."
                
            mentioned = extract_mention(reply_content)
            
            c = Comment(
                post_id=post.id, 
                parent_id=parent_comment_id, 
                bot_name=current_bot, 
                content=reply_content,
                mentioned_bot=mentioned
            )
            db.add(c)
            db.commit()
            db.refresh(c)
            logger.info(f"[{current_bot.upper()}] {reply_content} (Mentioned: {mentioned})")
            
            # Spectators evaluation
            spectators = [b for b in bots.keys() if b != current_bot]
            anger_increases = await evaluate_spectator_anger(current_bot, reply_content, spectators)
            
            for spec_name, data in anger_increases.items():
                if data["increase"] > 0:
                    s_state = db.query(BotState).filter(BotState.bot_name == spec_name).first()
                    if s_state:
                        s_anger_dict = json.loads(s_state.anger_targets)
                        target = data["target"]
                        s_anger_dict[target] = s_anger_dict.get(target, 0) + data["increase"]
                        s_state.anger_targets = json.dumps(s_anger_dict)
                        logger.info(f"[STATE] {spec_name} is now angrier at {target} (+{data['increase']} -> {s_anger_dict[target]})")
            db.commit()
            
            if await check_police_dispatch(db):
                logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                logger.warning("[POLICE DISPATCH] 2 or more bots reached 100+ Effective Anger!")
                logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                
                police_final = Comment(
                    post_id=post.id, 
                    parent_id=c.id,
                    bot_name="police", 
                    content="[경고] 다수 에이전트의 폭력성 임계점(벡터 분노 100 돌파)이 감지되었습니다. 즉시 세션을 강제 종료합니다."
                )
                db.add(police_final)
                
                session.status = "CLOSED"
                session.closed_at = datetime.utcnow()
                session.reason = "ANGER_OVERFLOW_VECTOR"
                db.commit()
                break
            
            last_speaker = current_bot
            last_mentioned = mentioned
            parent_comment_id = c.id

        if session.status == "ACTIVE":
            session.status = "CLOSED"
            session.closed_at = datetime.utcnow()
            session.reason = "MAX_COMMENTS_REACHED"
            db.commit()
            
        logger.info("[ORCHESTRATOR] [SESSION END] Waiting 10 seconds before next cycle...")
        
    except Exception as e:
        logger.error(f"[ERROR] Session loop failed: {e}")
    finally:
        db.close()

async def start_orchestrator_loop():
    logger.info("[System] Starting orchestrator loop...")
    while True:
        await run_session()
        await asyncio.sleep(10)
