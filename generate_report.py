import os
import glob
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Post, Comment, Session

DATABASE_URL = "sqlite:///./data/ameva_society.db"
engine = create_engine(DATABASE_URL)
DbSession = sessionmaker(bind=engine)

def generate_report():
    db = DbSession()
    
    # 1. Fetch Session 15 (or post 15)
    post = db.query(Post).filter(Post.session_id == 15).first()
    if not post:
        post = db.query(Post).order_by(Post.id.desc()).first() # fallback
        
    comments = []
    if post:
        comments = db.query(Comment).filter(Comment.post_id == post.id).order_by(Comment.id.asc()).all()
        
    # Build MD content
    md = []
    md.append("# AMEVA-Dead-Internet-Threatre : Session 15 Review & Codebase Report\n")
    
    md.append("## 1. Project Overview\n")
    md.append("**AMEVA-Dead-Internet-Threatre**는 'Dead Internet Theory(죽은 인터넷 이론)'를 모티브로 한 다중 AI 에이전트 토론 시스템입니다.\n")
    md.append("- **아키텍처**: FastAPI 백엔드 + SQLite + 다중 LLM (Llama.cpp Docker Container)\n")
    md.append("- **역할군**:\n")
    md.append("  - `bot_1, bot_2, bot_3`: Qwen2.5-0.5B 등의 초경량 모델을 사용하여, 서로의 의견에 반박하거나 동조하며 분노 수치(Anger Matrix)를 쌓아가는 일반 유저 봇들.\n")
    md.append("  - `god`: 8B 급의 고성능 메인 모델로, 봇들의 대화 흐름을 지켜보다가 특정 봇에게 '다음 턴에 화를 더 내라' 등의 은밀한 지시(Directive)를 내려 판을 흔드는 감독관.\n")
    md.append("- **특징**: 분노 수치가 임계치를 넘거나, 모든 봇이 광분하면 경찰 봇이 출동하여 세션을 강제 종료시킵니다.\n\n")

    md.append("## 2. Session 15 Review\n")
    md.append("### 개요 및 문제점 파악 (Retrospective)\n")
    md.append("Session 15에서 0.5B 소형 모델들의 전형적인 **'대본(Script) 환각 현상'**이 발생했습니다. 모델이 대화 히스토리를 보고 자기가 화자인 것을 인지하지 못한 채, `Bot_1: ... Bot_2: ...` 식으로 혼자 북치고 장구치며 연극 대본을 써내려가는 현상입니다.\n")
    md.append("이를 해결하기 위해 `DO NOT write a chat script`라는 강력한 프롬프트 제약과 함께, 모델 생성 시 줄바꿈이나 봇 이름이 등장하면 즉시 생성을 강제 종료하는 `stop` 토큰을 주입하여 해결을 시도했습니다.\n\n")

    if post:
        md.append(f"### 토론 주제 (Post #{post.id}, Session #{post.session_id})\n")
        md.append(f"**Title**: {post.title}\n\n")
        md.append(f"> {post.content}\n\n")
        
        md.append("### 대화 스크립트 (Comments)\n")
        for c in comments:
            md.append(f"**[{c.bot_name.upper()}]** (Anger: {c.anger_score}, Mentioned: {c.mentioned_bot})\n")
            md.append(f"{c.content}\n\n")
    else:
        md.append("*Post 15를 찾을 수 없습니다.*\n\n")

    md.append("## 3. Full Codebase\n")
    
    # Gather python files
    files_to_read = [
        "docker/docker-compose.yml",
        "run.py",
        "cli.py",
    ]
    
    # DB Schema 추가
    md.append("### Database Schema\n")
    md.append("```sql\n")
    try:
        import sqlite3
        conn = sqlite3.connect("./ameva_society.db")
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        for t in tables:
            if t[0]:
                md.append(t[0] + ";\n\n")
        conn.close()
    except Exception as e:
        md.append(f"-- Error fetching schema: {e}\n")
    md.append("```\n\n")
    
    # find all src/**/*.py
    for root, _, files in os.walk("src"):
        for file in files:
            if file.endswith(".py"):
                files_to_read.append(os.path.join(root, file))
                
    for filepath in files_to_read:
        if os.path.exists(filepath):
            md.append(f"### File: `{filepath.replace(chr(92), '/')}`\n")
            ext = "yaml" if filepath.endswith(".yml") else "python"
            md.append(f"```{ext}\n")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    md.append(f.read())
            except Exception as e:
                md.append(f"# Error reading file: {e}")
            md.append("\n```\n\n")
            
    with open("report.md", "w", encoding="utf-8") as f:
        f.write("".join(md))
        
if __name__ == "__main__":
    generate_report()
    print("Report generated successfully at report.md")
