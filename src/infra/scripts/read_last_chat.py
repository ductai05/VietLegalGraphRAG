import sqlite3
import json

db_path = '/app/backend/data/webui.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute('SELECT chat FROM chat ORDER BY updated_at DESC LIMIT 1')
row = cursor.fetchone()
if row:
    chat_data = json.loads(row[0])
    messages = chat_data.get("messages", [])
    print(f"Total messages in last chat: {len(messages)}")
    for i, msg in enumerate(messages[-3:]):
        print(f"--- Msg {i} | Role: {msg.get('role')} ---")
        print(msg.get('content'))
else:
    print("No chat history found.")
conn.close()
