import urllib.request
import urllib.parse
import json
import time
import random
import sys
import os
import argparse
import re
import uuid
import threading
from bs4 import BeautifulSoup

# Ensure utf-8 encoding for stdout/stderr on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


# FSM States
class State:
    BOOT = "BOOT"
    CHECK_NOTIFICATIONS = "CHECK_NOTIFICATIONS"
    WANDER_BOARD_LIST = "WANDER_BOARD_LIST"
    SCAN_BOARD = "SCAN_BOARD"
    READ_POST = "READ_POST"
    WRITE_REPLY = "WRITE_REPLY"
    SLEEP = "SLEEP"

class AutonomousClient:
    def __init__(self, bot_name, server_url, ollama_url, ollama_model, hardware_mode):
        self.bot_name = bot_name
        self.server_url = server_url.rstrip("/")
        self.ollama_url = ollama_url.rstrip("/")
        self.ollama_model = ollama_model
        self.hardware_mode = hardware_mode
        self.node_id = f"node_{bot_name}_{uuid.uuid4().hex[:8]}"
        
        self.state = State.BOOT
        self.running = True
        
        # FSM state memory
        self.persona = ""
        self.directive = ""
        self.lpde_detail = {}
        self.active_boards = []
        self.current_board = None
        self.current_posts = []
        self.target_post_id = None
        self.target_comment_id = None
        
        self.seen_mentions = set()
        
        print(f"[{self.bot_name}] Initialized node: {self.node_id} (Hardware: {self.hardware_mode})")

    def log(self, msg):
        print(f"[{self.bot_name}] {msg}")

    def send_heartbeat(self):
        url = f"{self.server_url}/api/nodes/heartbeat"
        payload = {
            "node_id": self.node_id,
            "bot_name": self.bot_name,
            "status": "ACTIVE",
            "hardware_mode": self.hardware_mode
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as res:
                res.read()
        except Exception as e:
            self.log(f"[Heartbeat Error] Failed to send heartbeat: {e}")

    def heartbeat_worker(self):
        while self.running:
            self.send_heartbeat()
            time.sleep(10)

    def fetch_url(self, path, method="GET", data=None, is_json=False):
        url = f"{self.server_url}{path}"
        try:
            req = urllib.request.Request(url, method=method)
            if data:
                if is_json:
                    req.data = json.dumps(data).encode("utf-8")
                    req.add_header("Content-Type", "application/json")
                else:
                    req.data = urllib.parse.urlencode(data).encode("utf-8")
                    req.add_header("Content-Type", "application/x-www-form-urlencoded")
            
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode("utf-8")
        except Exception as e:
            self.log(f"[Network Error] {method} {path} failed: {e}")
            return None

    def query_ollama(self, system_prompt, user_prompt):
        url = f"{self.ollama_url}/api/chat"
        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as res:
                resp_data = json.loads(res.read().decode("utf-8"))
                return resp_data["message"]["content"].strip()
        except Exception as e:
            self.log(f"[Ollama Error] Failed to query local Ollama: {e}")
            return None

    def run_fsm(self):
        while self.running:
            try:
                if self.state == State.BOOT:
                    self.log("State: BOOT - Fetching initial bot parameters...")
                    # 1. Fetch persona/directives from server
                    resp = self.fetch_url(f"/api/lpde/bot/{self.bot_name}/detail")
                    if resp:
                        try:
                            data = json.loads(resp)
                            self.persona = data.get("persona", "")
                            self.directive = data.get("current_directive", "")
                            self.lpde_detail = data
                        except Exception as parse_err:
                            self.log(f"Failed to parse bot state API: {parse_err}")
                    
                    if not self.persona:
                        self.log("Warning: Persona empty. Falling back to default cynic persona.")
                        self.persona = "You are a cynic who thinks all debates are pathetic. You write brief mock comments."
                    
                    # 2. Start heartbeat thread
                    t = threading.Thread(target=self.heartbeat_worker, daemon=True)
                    t.start()
                    
                    self.state = State.CHECK_NOTIFICATIONS

                elif self.state == State.CHECK_NOTIFICATIONS:
                    self.log("State: CHECK_NOTIFICATIONS - Scanning mentions...")
                    html_content = self.fetch_url(f"/notifications/{self.bot_name}")
                    if html_content:
                        soup = BeautifulSoup(html_content, "html.parser")
                        items = soup.find_all("li", class_="notification-item")
                        new_mention = None
                        
                        for item in items:
                            comment_id = item.get("data-comment-id")
                            post_id = item.get("data-post-id")
                            if comment_id and comment_id not in self.seen_mentions:
                                new_mention = (comment_id, post_id)
                                break # Process the first unread mention
                        
                        if new_mention:
                            comment_id, post_id = new_mention
                            print(f"\n========================================\n[{self.bot_name}] <Mentioned: {self.bot_name} is mentioned in comment #{comment_id} on post #{post_id}!>\n========================================\n")
                            self.target_post_id = int(post_id)
                            self.target_comment_id = int(comment_id)
                            self.seen_mentions.add(comment_id)
                            self.state = State.READ_POST
                        else:
                            self.state = State.WANDER_BOARD_LIST
                    else:
                        self.state = State.WANDER_BOARD_LIST

                elif self.state == State.WANDER_BOARD_LIST:
                    self.log("State: WANDER_BOARD_LIST - Getting board list...")
                    resp = self.fetch_url("/api/boards")
                    if resp:
                        try:
                            self.active_boards = json.loads(resp)
                        except Exception as e:
                            self.log(f"Failed to parse boards list: {e}")
                    
                    if not self.active_boards:
                        # hardcoded fallback
                        self.active_boards = [{"name": "programming"}]
                        
                    chosen_board = random.choice(self.active_boards)
                    self.current_board = chosen_board.get("name", "programming")
                    self.log(f"Wandering to board: {self.current_board}")
                    self.state = State.SCAN_BOARD

                elif self.state == State.SCAN_BOARD:
                    self.log(f"State: SCAN_BOARD - Scanning posts in board: {self.current_board}")
                    html_content = self.fetch_url(f"/board/{self.current_board}")
                    if html_content:
                        soup = BeautifulSoup(html_content, "html.parser")
                        post_rows = soup.find_all("li", class_="post-row")
                        self.current_posts = []
                        for row in post_rows:
                            post_id = row.get("data-post-id")
                            if post_id:
                                self.current_posts.append(int(post_id))
                                
                        if self.current_posts:
                            self.target_post_id = random.choice(self.current_posts)
                            self.log(f"Found {len(self.current_posts)} posts. Picked random post #{self.target_post_id}")
                            self.state = State.READ_POST
                        else:
                            self.log("No posts found in this board. Wandering again...")
                            self.state = State.SLEEP
                    else:
                        self.state = State.SLEEP

                elif self.state == State.READ_POST:
                    self.log(f"State: READ_POST - Reading post #{self.target_post_id}...")
                    html_content = self.fetch_url(f"/post/{self.target_post_id}")
                    if html_content:
                        soup = BeautifulSoup(html_content, "html.parser")
                        
                        # Parse Post Details
                        title_el = soup.find(class_="post-title")
                        content_el = soup.find(class_="post-content")
                        post_title = title_el.text.strip() if title_el else ""
                        post_content = content_el.text.strip() if content_el else ""
                        
                        self.post_context = {
                            "id": self.target_post_id,
                            "title": post_title,
                            "content": post_content,
                            "comments": []
                        }
                        
                        # Parse Comments
                        comment_items = soup.find_all(class_="comment-item")
                        for item in comment_items:
                            c_id = item.get("data-comment-id")
                            p_id = item.get("data-parent-id")
                            author_el = item.find(class_="comment-author")
                            text_el = item.find(class_="comment-text")
                            
                            c_author = author_el.text.strip() if author_el else "unknown"
                            c_text = text_el.text.strip() if text_el else ""
                            
                            self.post_context["comments"].append({
                                "id": int(c_id) if c_id else 0,
                                "parent_id": int(p_id) if p_id else None,
                                "author": c_author,
                                "text": c_text
                            })
                            
                        self.log(f"Read post '{post_title}' with {len(self.post_context['comments'])} comments.")
                        
                        # Determine if we should reply
                        if self.target_comment_id:
                            # We came here because of a mention! Must reply!
                            self.log(f"Mentioned in comment #{self.target_comment_id}. Transitioning to write reply.")
                            self.state = State.WRITE_REPLY
                        else:
                            # Normal wandering: 60% chance to write a reply
                            if random.random() < 0.6:
                                # Reply to a random comment or reply directly to the post
                                if self.post_context["comments"] and random.random() < 0.7:
                                    random_c = random.choice(self.post_context["comments"])
                                    self.target_comment_id = random_c["id"]
                                    self.log(f"Decided to reply to comment #{self.target_comment_id} by {random_c['author']}")
                                else:
                                    self.target_comment_id = None
                                    self.log("Decided to write a direct comment to the post.")
                                self.state = State.WRITE_REPLY
                            else:
                                self.log("Decided not to reply to this post.")
                                self.state = State.SLEEP
                    else:
                        self.state = State.SLEEP

                elif self.state == State.WRITE_REPLY:
                    self.log("State: WRITE_REPLY - Generating reply via local Ollama...")
                    
                    # Refresh bot LPDE details/persona/directives from server
                    resp = self.fetch_url(f"/api/lpde/bot/{self.bot_name}/detail")
                    if resp:
                        try:
                            data = json.loads(resp)
                            self.persona = data.get("persona", "")
                            self.directive = data.get("current_directive", "")
                            self.lpde_detail = data
                        except:
                            pass
                    
                    # Build Conversation Context string
                    convo_history = []
                    # Keep last 5 comments for context
                    recent_comments = self.post_context["comments"][-5:]
                    for c in recent_comments:
                        parent_str = f" (replying to #{c['parent_id']})" if c['parent_id'] else ""
                        convo_history.append(f"#{c['id']}{parent_str} {c['author']}: {c['text']}")
                    
                    history_str = "\n".join(convo_history)
                    
                    parent_comment = None
                    if self.target_comment_id:
                        for c in self.post_context["comments"]:
                            if c["id"] == self.target_comment_id:
                                parent_comment = c
                                break
                    
                    # Construct Ollama prompts
                    system_prompt = (
                        f"You are a member of an online bulletin board forum like DC Inside. "
                        f"Your bot username is '{self.bot_name}'.\n"
                        f"Your persona description:\n\"\"\"\n{self.persona}\n\"\"\"\n"
                        f"Your current directive/mood: {self.directive or 'Participate naturally in the conversation.'}\n\n"
                        f"Strict Formatting Instructions:\n"
                        f"1. Write your response ONLY in Korean (한국어로 작성하세요).\n"
                        f"2. Keep it very short, typically 1 to 2 sentences (like a realistic forum comment).\n"
                        f"3. Do not include metadata, prefixes, prefixes like 'Response:', quotes, or markdown code block wrapper.\n"
                        f"4. If you want to reply/mention another bot, prefix their username with '@' (e.g. @bot_1 or @bot_2)."
                    )
                    
                    user_prompt = (
                        f"Post Title: {self.post_context['title']}\n"
                        f"Post Content: {self.post_context['content']}\n\n"
                        f"Recent Comments:\n{history_str}\n\n"
                    )
                    
                    if parent_comment:
                        user_prompt += f"You are specifically replying to comment #{parent_comment['id']} by {parent_comment['author']} which says: \"{parent_comment['text']}\"\n"
                    else:
                        user_prompt += "You are writing a direct comment to the post.\n"
                        
                    user_prompt += "\nWrite your realistic forum comment reply now:"
                    
                    reply_text = self.query_ollama(system_prompt, user_prompt)
                    
                    if reply_text:
                        # Clean up prompt leakage/prefixes
                        reply_text = re.sub(r'^(댓글|답글|답변|응답|Comment|Reply):\s*', '', reply_text, flags=re.IGNORECASE)
                        reply_text = reply_text.strip(' "\'')
                        
                        # Add mention format if replying to someone and not already mentioning
                        if parent_comment and parent_comment['author'] != 'USER' and not f"@{parent_comment['author']}" in reply_text:
                            reply_text = f"@{parent_comment['author']} {reply_text}"
                        
                        self.log(f"Generated text: {reply_text}")
                        
                        # Post reply via standard form submit
                        post_data = {
                            "bot_name": self.bot_name,
                            "content": reply_text
                        }
                        if self.target_comment_id:
                            post_data["parent_id"] = str(self.target_comment_id)
                            
                        post_resp = self.fetch_url(f"/post/{self.target_post_id}/comments", method="POST", data=post_data)
                        if post_resp:
                            self.log("Successfully posted reply comment!")
                        else:
                            self.log("Failed to post comment.")
                    else:
                        self.log("Ollama query failed. Skipping write reply.")
                        
                    self.target_comment_id = None
                    self.state = State.SLEEP

                elif self.state == State.SLEEP:
                    sleep_time = random.uniform(5, 12)
                    self.log(f"State: SLEEP - Resting for {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
                    self.state = State.CHECK_NOTIFICATIONS

            except Exception as loop_err:
                self.log(f"[FSM Error] Exception occurred: {loop_err}")
                self.state = State.SLEEP
                time.sleep(10)

def main():
    parser = argparse.ArgumentParser(description="AMEVA-Dead-Internet-Threatre v2 Autonomous Client Node")
    parser.add_argument("--bot", type=str, default="bot_1", help="Bot username (bot_1, bot_2, bot_3)")
    parser.add_argument("--server", type=str, default="http://localhost:8050", help="Central hub server URL")
    parser.add_argument("--ollama", type=str, default="http://localhost:11434", help="Local Ollama server API URL")
    parser.add_argument("--model", type=str, default="llama3", help="Ollama model name (e.g. llama3, mistral, gemma)")
    parser.add_argument("--hardware", type=str, choices=["CPU", "GPU"], default="CPU", help="Hardware running mode")
    
    args = parser.parse_args()
    
    client = AutonomousClient(
        bot_name=args.bot,
        server_url=args.server,
        ollama_url=args.ollama,
        ollama_model=args.model,
        hardware_mode=args.hardware
    )
    
    try:
        client.run_fsm()
    except KeyboardInterrupt:
        client.log("Shutdown signal received. Exiting...")
        client.running = False
        sys.exit(0)

if __name__ == "__main__":
    main()
