import asyncio
import logging
import random
import re
import json
import math
import psutil
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

async def smart_sleep():
    """Sleep based on CPU usage to prevent bottlenecking."""
    cpu_usage = psutil.cpu_percent(interval=0.5)
    if cpu_usage >= 90.0:
        logger.info(f"[THROTTLE] CPU usage high ({cpu_usage}%). Sleeping for 10 seconds.")
        await asyncio.sleep(10)
    else:
        logger.info(f"[THROTTLE] CPU usage normal ({cpu_usage}%). Sleeping for 5 seconds.")
        await asyncio.sleep(5)

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
        f"{{\"{spec_1}\": 10, \"{spec_2}\": 5}}"
    )
    
    result = await god_llm.generate_completion("너는 갈등을 조장하는 평가자다.", prompt, max_tokens=150)
    
    # Parse with multiple fallback strategies (robust parsing)
    val_1, val_2 = 0, 0
    
    try:
        # Strategy 1: Standard JSON parsing from matched braces
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            
            # Helper to extract integer from value which could be an int or a dict
            def extract_val(v):
                if isinstance(v, dict):
                    return int(v.get("increase", 0))
                return int(v)
                
            if spec_1 in data:
                val_1 = extract_val(data[spec_1])
            if spec_2 in data:
                val_2 = extract_val(data[spec_2])
    except Exception:
        pass
        
    # Strategy 2: Regex extraction (handles malformed, truncated, or raw text)
    if val_1 == 0:
        match_simple = re.search(rf'"{spec_1}"\s*:\s*(\d+)', result)
        if match_simple:
            val_1 = int(match_simple.group(1))
        else:
            match_complex = re.search(rf'"{spec_1}"\s*:\s*\{{[^}}]*"increase"\s*:\s*(\d+)', result)
            if match_complex:
                val_1 = int(match_complex.group(1))
                
    if val_2 == 0:
        match_simple = re.search(rf'"{spec_2}"\s*:\s*(\d+)', result)
        if match_simple:
            val_2 = int(match_simple.group(1))
        else:
            match_complex = re.search(rf'"{spec_2}"\s*:\s*\{{[^}}]*"increase"\s*:\s*(\d+)', result)
            if match_complex:
                val_2 = int(match_complex.group(1))
                
    # Clamp results to [0, 20]
    val_1 = min(max(val_1, 0), 20)
    val_2 = min(max(val_2, 0), 20)
    
    out = {
        spec_1: {"target": speaker, "increase": val_1},
        spec_2: {"target": speaker, "increase": val_2}
    }
    
    logger.info(f"[GOD LLM] Evaluated raw response: {result.strip()}")
    logger.info(f"[GOD LLM] Targeted Anger parsed: {out}")
    return out

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
        directive = "너는 현재 비교적 이성적이고 차분한 상태다. 예의를 지키되 냉정하게 논리적으로 토론해라."
    elif effective_anger < 70:
        directive = "너는 꽤 화가 난 상태다. 너를 자극한 타겟 봇을 향해 논리적인 모순을 제기하며 날카롭게 쏘아붙여라."
    else:
        directive = (
            "너는 현재 극도로 분노하여 흥분한 상태다. 절대로 감정을 감추지 말고, 타겟 봇에게 격정적인 비판과 반박을 쏟아부어라. "
            "상대방의 태도나 주장을 거칠게 받아치되, 절대 대화를 포기하고 입을 다물거나 '화가 나서 할 말이 없다'라는 식으로 도망치지 마라."
        )
        
    return base_info + directive

async def generate_director_directive(current_bot: str, recent_history: str, eff_anger: float) -> str:
    """God LLM generates a custom, dynamic directive for the current speaker based on conversation context."""
    logger.info(f"[GOD LLM] Generating dynamic director's directive for {current_bot}...")
    
    prompt = (
        f"[최근 대화]\n{recent_history}\n\n"
        f"[명령 대상] {current_bot} (분노: {eff_anger:.0f})\n\n"
        f"너는 갈등 기획자다. {current_bot}가 갈등을 증폭시키도록 구체적인 한 문장 지침을 내려라.\n"
        f"예: 'bot_2의 날씨 발언을 위선이라고 꼬투리 잡아 물고 늘어져라.'\n"
        f"한 문장의 한국어 지시사항만 출력해라."
    )
    
    result = await god_llm.generate_completion(
        "너는 갈등을 지시하는 감독관이다. 짧게 지시만 내려라.", 
        prompt, 
        max_tokens=80
    )
    
    directive = result.strip() if result else "상대방의 논리적 모순을 찾아 공격해라."
    # 너무 길면 첫 문장만 사용
    if '\n' in directive:
        directive = directive.split('\n')[0]
    logger.info(f"[GOD LLM] Director's Directive for {current_bot}: {directive}")
    return directive

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
        await PersonaManager.assign_random_personas()
        
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
            fallback_topics = [
                "인공지능이 인간의 일자리를 대체하는 것이 과연 옳은 일인가?",
                "요즘 젊은 세대가 예의가 없다는 말, 동의하시나요?",
                "집값이 이렇게 비싼데 결혼을 꼭 해야 하나요?",
                "학벌이 중요한가, 실력이 중요한가? 솔직하게 말해보자.",
                "반려동물을 키우는 사람이 아이를 키우는 사람보다 이기적인가?",
                "군대 의무 복무제, 폐지해야 하나 유지해야 하나?",
                "유튜버나 스트리머가 진짜 직업이라고 할 수 있나?",
                "편의점 알바 최저시급이 너무 적은가, 적절한가?",
            ]
            post_content = random.choice(fallback_topics)
        
        post = Post(session_id=session.id, title="새로운 논쟁 거리", content=post_content)
        db.add(post)
        db.commit()
        db.refresh(post)
        
        # 2. Phase 1: All bots state their first stance sequentially with CPU-aware throttling
        logger.info("[PHASE 1] Initial Stance Declaration (Sequential & Random)")
        
        stances = []
        for b_name in ["bot_1", "bot_2", "bot_3"]:
            await smart_sleep()
            persona = await PersonaManager.get_persona(b_name)
            bot_client = bots[b_name]
            prompt = f"게시글 내용: {post.content}\n\n이 게시글에 대한 너의 가장 솔직하고 확고한 첫 의견을 한국어로 남겨라. 멘션은 하지 마라."
            reply_content = await bot_client.generate_completion(persona, prompt, max_tokens=150)
            if not reply_content:
                reply_content = "내 의견은 딱히 없다."
            stances.append((b_name, reply_content))
        
        # Shuffle to randomize DB insertion order
        random.shuffle(stances)
        
        last_comment = None
        for b_name, reply_content in stances:
            c = Comment(post_id=post.id, parent_id=None, bot_name=b_name, content=reply_content)
            db.add(c)
            db.commit()
            db.refresh(c)
            logger.info(f"[{b_name.upper()}] Initial Stance: {reply_content}")
            last_comment = c
            
        # 3. Phase 2: Interruption & Mention Battle
        logger.info("[PHASE 2] Targeted Anger Battle Started")
        
        last_speaker = stances[-1][0]
        # Select a random bot as mentioned to start the chain
        last_mentioned = random.choice([b for b in ["bot_1", "bot_2", "bot_3"] if b != last_speaker])
        parent_comment_id = last_comment.id if last_comment else None
        
        for turn_idx in range(20):
            await smart_sleep() 
            
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
            
            # God LLM을 통해 이번 턴의 스피커에게 내릴 실시간 연출 지시사항 생성
            god_directive = await generate_director_directive(current_bot, recent_history, eff_anger)
            
            prompt = (
                f"게시글 내용: {post.content}\n\n"
                f"최근 대화:\n{recent_history}\n\n"
                f"{emotion_directive}\n"
                f"[절대자(신)의 실시간 지시사항]\n{god_directive}\n\n"
                f"너의 고유 캐릭터(페르소나)와 위의 감정 상태, 그리고 절대자의 실시간 지시사항을 완벽히 흡수하여 다음 덧글을 작성해라. "
                f"절대 '화가 나서 말하지 않겠다'라며 대화를 회피하거나 기계적인 AI 답변을 하지 마라. "
                f"반드시 한국어로 댓글을 달아라. 반드시 글 마지막에 발언을 넘길 봇을 '@bot_1', '@bot_2', '@bot_3' 중 하나로 멘션해서 지목해라."
            )
            
            reply_content = await bot_client.generate_completion(persona, prompt, max_tokens=150)
            
            if not reply_content:
                fallback_replies = [
                    "아 진짜 어이가 없어서 말이 안 나온다. 잠깐만 기다려봐.",
                    "하... 뭐라고 해야 할지 모르겠네. 일단 넘어가자.",
                    "이 대화 수준이 너무 낮아서 뭐라 반응하기가 힘드네.",
                    "ㅋㅋㅋ 할 말은 많은데 참고 있는 거다.",
                ]
                reply_content = random.choice(fallback_replies)
                
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
                
                session.status = "CLOSED_BY_POLICE"
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
