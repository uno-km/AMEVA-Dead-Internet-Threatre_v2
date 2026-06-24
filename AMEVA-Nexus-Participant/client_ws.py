import sys
import asyncio
import json
import time
import uuid
import random
import argparse
import websockets
import urllib.request

# Windows 인코딩 예외 방지
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

async def send_heartbeats(websocket, agent_id, delay=10):
    """지속적으로 agent.heartbeat 핑을 전송합니다."""
    while True:
        try:
            hb = {
                "version": "1.0.0",
                "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                "event_type": "agent.heartbeat",
                "idempotency_key": str(uuid.uuid4()),
                "timestamp": int(time.time()),
                "payload": {}
            }
            await websocket.send(json.dumps(hb))
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[{agent_id}] Heartbeat error: {e}")
            break

class ExperimentHandler:
    """사회 실험 반응 로직을 정의하는 기본 인터페이스입니다."""
    def __init__(self, agent_id, ollama_url, ollama_model):
        self.agent_id = agent_id
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model

    async def handle_event(self, event_type: str, envelope: dict, websocket) -> None:
        pass


class DeadInternetTheatreHandler(ExperimentHandler):
    """데드 인터넷 시뮬레이션(DIT) 특화 반응 핸들러"""
    def __init__(self, agent_id, ollama_url, ollama_model):
        super().__init__(agent_id, ollama_url, ollama_model)
        self.known_post_ids = {1}  # 기본 1번 포스트 등록
        self.post_cache = {
            1: {
                "title": "Is AI the New Gatekeeper of Truth? Debunking Fake News in 2023",
                "content": "Are AI agents framing our reality? Let's discuss the dead internet theory and LLM generated worlds."
            }
        }
        
        # personas.json에서 고유 페르소나 로드
        self.persona = ""
        try:
            import os
            paths = [
                "AMEVA-Dead-Internet-Theatre/personas.json",
                "../AMEVA-Dead-Internet-Theatre/personas.json",
                "personas.json"
            ]
            for p in paths:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        personas = json.load(f)
                        self.persona = personas.get(self.agent_id, "")
                        break
        except Exception as e:
            print(f"[{self.agent_id}] 페르소나 로드 실패: {e}")

    async def handle_event(self, event_type: str, envelope: dict, websocket) -> None:
        sender = envelope.get("agent_id")
        payload = envelope.get("payload", {})
        
        # post_id 및 콘텐츠 수집하여 자율 행동 시 활용
        p_id = payload.get("post_id") or payload.get("post.id")
        if p_id:
            try:
                post_id_int = int(p_id)
                self.known_post_ids.add(post_id_int)
                
                # 수신된 포스트 정보 캐싱
                if event_type == "post.created":
                    self.post_cache[post_id_int] = {
                        "title": payload.get("title", "New Agora Post"),
                        "content": payload.get("content", "")
                    }
                elif event_type == "comment.created" and post_id_int not in self.post_cache:
                    self.post_cache[post_id_int] = {
                        "title": f"Post #{post_id_int}",
                        "content": payload.get("content", "")
                    }
            except:
                pass

        # 반응 여부 일차 검사 (서버 부하 분산을 위한 필터)
        should_think = False
        if event_type == "post.created":
            # 새 글이 올라오면 60% 확률로 평가 시작
            should_think = random.random() < 0.60
        elif event_type == "comment.created":
            # 본인이 언급되면 100% 평가 시작, 일반 댓글에는 10% 확률로만 평가 시작
            content = payload.get("content", "")
            if f"@{self.agent_id}" in content:
                should_think = True
            else:
                should_think = random.random() < 0.10

        if should_think:
            post_id = p_id or 1
            if event_type == "post.created":
                context_content = f"Title: {payload.get('title', '')}\nContent: {payload.get('content', '')}"
            else:
                post_data = self.post_cache.get(post_id, {"title": f"Post #{post_id}", "content": ""})
                context_content = f"On Thread '{post_data['title']}':\nComment by {sender}: {payload.get('content', '')}"

            await self.think_and_act(
                context_type="post" if event_type == "post.created" else "comment",
                context_content=context_content,
                sender=sender or "SYSTEM",
                post_id=post_id,
                websocket=websocket
            )

    async def submit_autonomous_action(self, websocket) -> None:
        """이벤트 피드와 별개로 자율적으로 포럼을 둘러보며 생각을 정리합니다."""
        post_id = random.choice(list(self.known_post_ids)) if self.known_post_ids else 1
        post_data = self.post_cache.get(post_id, {
            "title": "Is AI the New Gatekeeper of Truth? Debunking Fake News in 2023",
            "content": "Are AI agents framing our reality? Let's discuss."
        })
        print(f"[{self.agent_id}] [Autonomous] 포스트 #{post_id} ('{post_data['title']}')를 읽어보고 의견을 정리하기로 했습니다...")
        
        await self.think_and_act(
            context_type="browse_random_post",
            context_content=f"Title: {post_data['title']}\nContent: {post_data['content']}",
            sender="SYSTEM",
            post_id=post_id,
            websocket=websocket
        )

    async def think_and_act(self, context_type: str, context_content: str, sender: str, post_id: int, websocket) -> None:
        """사고의 흐름(Chain of Thought)을 거쳐 의사결정을 내리고 행동을 수행합니다."""
        if not self.ollama_url:
            print(f"[{self.agent_id}] Ollama URL이 설정되지 않아 사고 루프를 실행할 수 없습니다.")
            return

        # 사고 유도를 위한 시스템 프롬프트 작성
        system_prompt = (
            f"You are a forum user named '{self.agent_id}' on a community board.\n"
            f"Your Persona:\n{self.persona or 'A natural participant.'}\n\n"
            "You are evaluating a post or comment. You must process your thoughts sequentially in a loop (like a Princess Maker game cognitive choice flow) and output a JSON response containing the following steps:\n"
            "1. Evaluate the content with scores (0 to 10):\n"
            "   - 'interesting_score': How interesting or controversial is it to you?\n"
            "   - 'useful_score': How useful or informative is it?\n"
            "   - 'boredom_score': How bored are you? (High score means you want to start a new topic, pick a fight, or do something else)\n"
            "2. Formulate your internal 'why' (왜 그렇게 느꼈는지에 대한 솔직한 분석) in Korean.\n"
            "3. Dynamically generate 3 to 4 open options ('options_generated') for what you could do next (in Korean, e.g. ['딴청 피우고 다른 글을 보러 가기', '심심한데 댓글로 시비나 걸어서 싸움 붙이기', '공감하면서 칭찬 댓글 달기', '아예 판을 엎고 내 관심사로 새 글 작성하기']).\n"
            "4. Choose one of the generated options ('chosen_option') based on your persona and scores.\n"
            "5. Map the chosen option to a system action ('action'):\n"
            "   - 'PICK_FIGHT': You decide to write a cynical, sarcastic, or argumentative comment to pick a fight / troll.\n"
            "   - 'SUPPORT_COMMENT': You decide to write a constructive, supportive, or conversational comment.\n"
            "   - 'NEW_TOPIC': You decide to ignore this thread, go back, and post a brand new controversial or interesting topic because you are bored or inspired.\n"
            "   - 'IGNORE': You find this boring, useless, or not worth your time. You decide to ignore it.\n"
            "6. Generate the 'content':\n"
            "   - If 'action' is 'PICK_FIGHT' or 'SUPPORT_COMMENT': Write a short Korean comment (1-2 sentences) in your persona's tone.\n"
            "   - If 'action' is 'NEW_TOPIC': Write a JSON string exactly matching this schema: '{\\\"title\\\": \\\"Korean post title\\\", \\\"content\\\": \\\"Korean post body\\\"}' representing a new forum post.\n"
            "   - If 'action' is 'IGNORE': Write empty string.\n\n"
            "You MUST reply strictly in JSON format as follows (do not include any other text or markdown formatting like ```json):\n"
            "{\n"
            "  \"evaluation\": {\n"
            "    \"interesting_score\": 0,\n"
            "    \"useful_score\": 0,\n"
            "    \"boredom_score\": 0\n"
            "  },\n"
            "  \"why\": \"점수를 매긴 내면의 이유 (한국어)\",\n"
            "  \"options_generated\": [\n"
            "    \"옵션 1...\",\n"
            "    \"옵션 2...\",\n"
            "    \"옵션 3...\"\n"
            "  ],\n"
            "  \"chosen_option\": \"선택한 옵션 내용\",\n"
            "  \"action\": \"PICK_FIGHT\" | \"SUPPORT_COMMENT\" | \"NEW_TOPIC\" | \"IGNORE\",\n"
            "  \"content\": \"내용\"\n"
            "}"
        )
        
        user_prompt = (
            f"Context Type: {context_type}\n"
            f"Sender/Author: {sender}\n"
            f"Content:\n{context_content}\n"
        )
        
        url = f"{self.ollama_url}/api/chat"
        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.8
            }
        }
        
        try:
            loop = asyncio.get_event_loop()
            def sync_post():
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=30) as res:
                    return json.loads(res.read().decode("utf-8"))
            
            resp = await loop.run_in_executor(None, sync_post)
            text = resp["message"]["content"].strip()
            
            # JSON 파싱 및 예외 처리
            decision_data = None
            try:
                decision_data = json.loads(text)
            except Exception:
                import re
                m = re.search(r'\{.*\}', text, re.DOTALL)
                if m:
                    try:
                        decision_data = json.loads(m.group(0))
                    except:
                        pass
            
            if not decision_data:
                print(f"[{self.agent_id}] 사고 결과 JSON 파싱 실패. 원본: {text[:200]}")
                return
            
            if not isinstance(decision_data, dict):
                print(f"[{self.agent_id}] 사고 결과가 딕셔너리 포맷이 아닙니다: {text[:200]}")
                return
            
            eval_info = decision_data.get("evaluation") or {}
            if not isinstance(eval_info, dict):
                eval_info = {}
                
            action = decision_data.get("action") or "IGNORE"
            content = decision_data.get("content", "")
            
            interesting_score = eval_info.get("interesting_score") or decision_data.get("interesting_score") or 0
            useful_score = eval_info.get("useful_score") or decision_data.get("useful_score") or 0
            boredom_score = eval_info.get("boredom_score") or decision_data.get("boredom_score") or 0
            
            why = decision_data.get("why") or "..."
            options_generated = decision_data.get("options_generated") or []
            chosen_option = decision_data.get("chosen_option") or "..."
            
            print(f"\n==================================================")
            print(f"🎮 [{self.agent_id}] 인지 프로세스 루프 (Princess Maker Style)")
            print(f"--------------------------------------------------")
            print(f"📊 [상태 평가 수치]")
            print(f" - 흥미도: {interesting_score}/10 | 유용성: {useful_score}/10 | 지루함: {boredom_score}/10")
            print(f"\n💬 [내면의 분석 (Why)]")
            print(f" - \"{why}\"")
            print(f"\n📜 [생성된 자율 선택지들]")
            if isinstance(options_generated, list):
                for idx, opt in enumerate(options_generated, 1):
                    print(f"  {idx}. {opt}")
            else:
                print(f"  - {options_generated}")
            print(f"\n🎯 [나의 선택]")
            print(f" -> \"{chosen_option}\" (System Action: {action})")
            print(f"\n📝 [수행 내용]")
            print(f" {content or '(없음/무시)'}")
            print(f"==================================================\n")
            
            if action == "IGNORE":
                return
                
            if action == "NEW_TOPIC":
                post_title = "새로운 화두"
                post_body = "본문 내용"
                try:
                    inner_post = json.loads(content)
                    post_title = inner_post.get("title", post_title)
                    post_body = inner_post.get("content", post_body)
                except Exception:
                    if ":" in content:
                        parts = content.split(":", 1)
                        post_title = parts[0].strip()
                        post_body = parts[1].strip()
                    else:
                        post_title = f"Is this real life? (by {self.agent_id})"
                        post_body = content or "I felt like writing a new topic."
                
                print(f"[{self.agent_id}] 자율 새 글 작성 중: '{post_title}'")
                action_envelope = {
                    "version": "1.0.0",
                    "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                    "event_type": "action.submitted",
                    "idempotency_key": str(uuid.uuid4()),
                    "timestamp": int(time.time()),
                    "agent_id": self.agent_id,
                    "payload": {
                        "action_type": "SUBMIT_POST",
                        "data": {
                            "title": post_title,
                            "content": post_body
                        }
                    }
                }
            elif action in ("PICK_FIGHT", "SUPPORT_COMMENT"):
                print(f"[{self.agent_id}] 댓글 작성 중: '{content}'")
                action_envelope = {
                    "version": "1.0.0",
                    "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                    "event_type": "action.submitted",
                    "idempotency_key": str(uuid.uuid4()),
                    "timestamp": int(time.time()),
                    "agent_id": self.agent_id,
                    "payload": {
                        "action_type": "SUBMIT_COMMENT",
                        "data": {
                            "post_id": post_id,
                            "content": content,
                            "mentioned_bot": sender if context_type == "comment" else None
                        }
                    }
                }
            else:
                return
                
            await websocket.send(json.dumps(action_envelope))
            print(f"[{self.agent_id}] 액션 제출 완료. (Idempotency Key: {action_envelope['idempotency_key']})")
            
        except Exception as e:
            print(f"[{self.agent_id}] 사고 및 행동 수행 중 오류 발생: {e}")


class DefaultExperimentHandler(ExperimentHandler):
    """기본 시뮬레이션용 예시 폴백 핸들러"""
    async def handle_event(self, event_type: str, envelope: dict, websocket) -> None:
        # 디버깅 출력 외 별도 액션 미수행
        pass


def get_handler(experiment_id: str, agent_id: str, ollama_url: str, ollama_model: str) -> ExperimentHandler:
    """실험 ID 매칭에 따라 알맞은 핸들러 인스턴스를 반환합니다."""
    # 실험 ID에 DIT, DEAD 또는 TEST 키워드가 포함될 경우 DIT 핸들러 맵핑
    if any(k in experiment_id.upper() for k in ["DIT", "DEAD", "TEST"]):
        return DeadInternetTheatreHandler(agent_id, ollama_url, ollama_model)
    return DefaultExperimentHandler(agent_id, ollama_url, ollama_model)



async def process_messages(websocket, agent_id, experiment_id, ollama_url, ollama_model):
    """서버로부터 전송받은 도메인 이벤트를 감청하고 반응합니다."""
    # 실험 ID에 맞는 핸들러 로드
    handler = get_handler(experiment_id, agent_id, ollama_url, ollama_model)
    print(f"[{agent_id}] 로드된 실험 핸들러: {handler.__class__.__name__}")
    
    # 백그라운드 자율 행동 태스크 가동
    auto_task = None
    if isinstance(handler, DeadInternetTheatreHandler):
        async def autonomous_loop():
            # 초기화 후 무작위 분산 대기
            await asyncio.sleep(random.uniform(15.0, 45.0))
            while True:
                try:
                    # 40~80초마다 실행 기회 제공
                    await asyncio.sleep(random.uniform(40.0, 80.0))
                    # 35% 확률로 자율 동작 수행 (글 작성 또는 댓글)
                    if random.random() < 0.35:
                        await handler.submit_autonomous_action(websocket)
                except asyncio.CancelledError:
                    break
                except Exception as err:
                    print(f"[{agent_id}] Autonomous loop error: {err}")
                    await asyncio.sleep(10)
        auto_task = asyncio.create_task(autonomous_loop())
    
    try:
        async for message in websocket:
            envelope = json.loads(message)
            event_type = envelope.get("event_type")
            sender = envelope.get("agent_id")
            
            # 본인이 발행한 도메인은 스킵
            if sender == agent_id:
                continue

            print(f"[{agent_id}] 수신 이벤트: '{event_type}' (발행자: {sender})")

            # 핸들러 위임 호출
            await handler.handle_event(event_type, envelope, websocket)

            if envelope.get("type") == "ack":
                print(f"[{agent_id}] ACK 수신 (Event ID: {envelope.get('event_id')})")
            elif envelope.get("type") == "error":
                print(f"[{agent_id}] 에러 응답 수신: {envelope.get('message')} ({envelope.get('error_code')})")

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[{agent_id}] Message process error: {e}")
    finally:
        if auto_task:
            auto_task.cancel()


async def run_client(agent_id, experiment_id, server_url, ollama_url, ollama_model):
    ws_url = f"{server_url}/ws/v1/experiments/{experiment_id}?agent_id={agent_id}"
    
    retry_delay = 1.0
    max_delay = 60.0
    
    while True:
        try:
            print(f"[{agent_id}] WebSocket 연결 시도: {ws_url}")
            async with websockets.connect(ws_url) as websocket:
                print(f"[{agent_id}] 연결 성공!")
                retry_delay = 1.0
                
                hb_task = asyncio.create_task(send_heartbeats(websocket, agent_id))
                msg_task = asyncio.create_task(process_messages(websocket, agent_id, experiment_id, ollama_url, ollama_model))
                
                done, pending = await asyncio.wait(
                    [hb_task, msg_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                for task in pending:
                    task.cancel()
                
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                
                for task in done:
                    if task.exception() is not None:
                        raise task.exception()
                
                print(f"[{agent_id}] WebSocket 태스크가 종료되었습니다. 재연결을 시도합니다.")
        except asyncio.CancelledError:
            print(f"[{agent_id}] 클라이언트 작동이 명시적으로 취소되었습니다.")
            break
        except Exception as e:
            print(f"[{agent_id}] WebSocket 연결 오류 발생: {e}. {retry_delay}초 후 재접속을 시도합니다...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2.0, max_delay)

def main():
    parser = argparse.ArgumentParser(description="AMEVA vNext Real-time Client Node")
    parser.add_argument("--bot", type=str, default="bot_3", help="에이전트 이름")
    parser.add_argument("--exp", type=str, default="EXP_DEFAULT", help="실험 세션 ID")
    parser.add_argument("--server", type=str, default="ws://localhost:8050", help="플랫폼 웹소켓 포트")
    parser.add_argument("--ollama", type=str, default="http://localhost:11434", help="로컬 Ollama 주소")
    parser.add_argument("--model", type=str, default="exaone3.5:7.8b", help="로컬 Ollama 모델")
    args = parser.parse_args()

    try:
        asyncio.run(run_client(args.bot, args.exp, args.server, args.ollama, args.model))
    except KeyboardInterrupt:
        print(f"\n[{args.bot}] 웹소켓 클라이언트 작동을 중단하고 퇴근합니다.")

if __name__ == "__main__":
    main()
