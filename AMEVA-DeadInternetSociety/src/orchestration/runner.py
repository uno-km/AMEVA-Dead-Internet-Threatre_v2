import asyncio
import logging
import random
import re
from datetime import datetime
from src.db.database import SessionLocal
from src.db.models import Session, Post, Comment, BotState
from src.core.llm_client import LLMClient
from src.core.persona import PersonaManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Orchestrator")

# LLM Clients
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
        s.current_anger = 0
    db.commit()

async def evaluate_anger(comment_text: str) -> int:
    """God LLM evaluates anger."""
    prompt = f"다음 문장의 분노치(공격성)를 0부터 100 사이의 숫자로만 평가해. 다른 말은 절대 하지 마.\n문장: {comment_text}"
    result = await god_llm.generate_completion("너는 감정 평가 AI다.", prompt, max_tokens=10)
    logger.info(f"[GOD LLM] Anger evaluation raw output: {result}")
    
    # Extract number
    match = re.search(r'\d+', result)
    if match:
        return min(int(match.group()), 100)
    return 0

async def check_police_dispatch(db) -> bool:
    """Check if 2 or more bots have anger >= 100"""
    states = db.query(BotState).all()
    angry_count = sum(1 for s in states if s.current_anger >= 100)
    if angry_count >= 2:
        return True
    return False

def extract_mention(text: str) -> str:
    """Extract @bot_1, @bot_2, @bot_3 from text."""
    for b in ["bot_1", "bot_2", "bot_3"]:
        if f"@{b}" in text:
            return b
    return None

async def run_session():
    db = SessionLocal()
    try:
        logger.info("[ORCHESTRATOR] Starting new session.")
        # 1. Reset states
        reset_bot_states(db)
        await PersonaManager.reset_personas()
        
        # Create Session
        session = Session(status="ACTIVE")
        db.add(session)
        db.commit()
        db.refresh(session)
        
        # 2. Main LLM writes a post
        logger.info("[ORCHESTRATOR] Main LLM is writing a post...")
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
        logger.info(f"[ORCHESTRATOR] Post written: {post.id}")
        
        # 3. Police Bot approves and starts relay
        first_bot = random.choice(list(bots.keys()))
        police_content = f"이 게시글은 검열을 통과했습니다. 댓글 작성을 허용합니다. @{first_bot} 먼저 의견을 말해보세요."
        
        police_comment = Comment(post_id=post.id, bot_name="police", content=police_content, mentioned_bot=first_bot)
        db.add(police_comment)
        db.commit()
        db.refresh(police_comment)
        logger.info(f"[POLICE] {police_content}")
        
        # 4. Comment Relay Loop
        current_bot = first_bot
        parent_comment_id = police_comment.id
        previous_anger = 0
        
        # Max 20 comments per session to prevent infinite loops if anger doesn't spike
        for _ in range(20):
            await asyncio.sleep(5) # Delay for pacing
            
            # Bot decides to speak
            persona = await PersonaManager.get_persona(current_bot)
            bot_client = bots[current_bot]
            
            prompt = (
                f"게시글 내용: {post.content}\n"
                f"너는 다른 봇의 호출을 받았다. 이전 분노치는 {previous_anger}이다.\n"
                f"반드시 한국어로 댓글을 달아라. 응답하고 싶지 않으면 '스킵'이라고 말할 수 있지만, 이전 분노치가 1 이상이면 무조건 응답해야 한다.\n"
                f"댓글을 작성할 때 반드시 다음 타자를 지목하기 위해 '@bot_1', '@bot_2', '@bot_3' 중 본인을 제외한 한 명을 맨 마지막에 포함해라."
            )
            
            logger.info(f"[ROUTING] Data sent from orchestrator to {current_bot} (Parent ID: {parent_comment_id})")
            
            reply_content = await bot_client.generate_completion(persona, prompt, max_tokens=150)
            
            if "스킵" in reply_content and previous_anger == 0:
                logger.info(f"[{current_bot}] Chose to skip.")
                # Pick a random next bot
                next_bot = random.choice([b for b in bots.keys() if b != current_bot])
                current_bot = next_bot
                continue
            
            if not reply_content:
                reply_content = "할 말이 없습니다."
            
            # Mention extraction
            mentioned = extract_mention(reply_content)
            if not mentioned or mentioned == current_bot:
                mentioned = random.choice([b for b in bots.keys() if b != current_bot])
                reply_content += f" @{mentioned}"
                
            # God LLM Evaluation
            anger_val = await evaluate_anger(reply_content)
            logger.info(f"[GOD LLM] Evaluated {current_bot}'s anger: {anger_val}")
            
            # Update State
            bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()
            if bot_state:
                bot_state.current_anger += anger_val
                db.commit()
            
            # Save comment
            c = Comment(
                post_id=post.id, 
                parent_id=parent_comment_id, 
                bot_name=current_bot, 
                content=reply_content, 
                anger_score=anger_val, 
                mentioned_bot=mentioned
            )
            db.add(c)
            db.commit()
            db.refresh(c)
            
            logger.info(f"[{current_bot}] {reply_content}")
            
            # Check Police
            if await check_police_dispatch(db):
                logger.info("[POLICE] Anger threshold breached! Dispatching Police Bot...")
                police_final = Comment(
                    post_id=post.id, 
                    bot_name="police", 
                    content="[경고] 공격성 수치 초과. 세션을 강제 종료합니다."
                )
                db.add(police_final)
                
                session.status = "CLOSED"
                session.closed_at = datetime.utcnow()
                session.reason = "ANGER_OVERFLOW"
                db.commit()
                break
            
            # Next turn
            current_bot = mentioned
            parent_comment_id = c.id
            previous_anger = anger_val

        # If loop finishes without police
        if session.status == "ACTIVE":
            session.status = "CLOSED"
            session.closed_at = datetime.utcnow()
            session.reason = "MAX_COMMENTS_REACHED"
            db.commit()
            
        logger.info("[ORCHESTRATOR] Session closed. Waiting for next session...")
        
    except Exception as e:
        logger.error(f"[ERROR] Session loop failed: {e}")
    finally:
        db.close()

async def start_orchestrator_loop():
    logger.info("[System] Starting orchestrator loop...")
    while True:
        await run_session()
        await asyncio.sleep(10) # Wait 10 seconds before starting the next session
