"""
Phase 3 DB Migration Script
- current_agent_states: role_label, role_meta_json 컬럼 추가
- agent_state_snapshots: role_label 컬럼 추가
- session_bot_states: role_label, role_meta_json 컬럼 추가
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "ameva_society.db")

def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    migrations = [
        # (table, column, definition)
        ("current_agent_states", "role_label", "TEXT DEFAULT 'swing_moderate'"),
        ("current_agent_states", "role_meta_json", "TEXT DEFAULT '{}'"),
        ("agent_state_snapshots", "role_label", "TEXT DEFAULT 'swing_moderate'"),
        ("session_bot_states", "role_label", "TEXT DEFAULT 'swing_moderate'"),
        ("session_bot_states", "role_meta_json", "TEXT DEFAULT '{}'"),
    ]

    for table, column, definition in migrations:
        if column_exists(cursor, table, column):
            print(f"[SKIP] {table}.{column} already exists.")
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            cursor.execute(sql)
            print(f"[ADDED] {table}.{column}")

    conn.commit()
    conn.close()
    print("\n✅ Migration complete.")

if __name__ == "__main__":
    migrate()
