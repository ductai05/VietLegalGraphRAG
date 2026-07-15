import sqlite3

db_path = '/app/backend/data/webui.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Set the function to active and global so it appears as a selectable model
cursor.execute("UPDATE function SET is_active = 1, is_global = 1 WHERE id = 'vietlegal_rag'")
conn.commit()

print(f"Successfully activated function 'vietlegal_rag'. Rows updated: {cursor.rowcount}")
conn.close()
