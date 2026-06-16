import os
import csv
import sqlite3
from dotenv import load_dotenv

load_dotenv()

DB_FILE = os.getenv('DB_FILE', 'system.db')
ALLOWLIST_FILE = os.getenv('ALLOWLIST_FILE', 'allowlist.csv')

if not os.path.exists(ALLOWLIST_FILE):
    with open(ALLOWLIST_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['uid', 'name', 'id_number', 'photo_path'])
    print(f"Created template file: {ALLOWLIST_FILE}")

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    uid        TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    id_number  TEXT NOT NULL,
    photo_path TEXT
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS attendance (
    timestamp  TEXT NOT NULL,
    name       TEXT NOT NULL,
    id_number  TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    purpose    TEXT
)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS environment (
    timestamp   TEXT NOT NULL,
    temperature REAL NOT NULL,
    humidity    REAL NOT NULL
)''')

conn.execute('PRAGMA journal_mode=WAL')
conn.commit()

with open(ALLOWLIST_FILE, mode='r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        uid = row['uid'].strip().upper()
        name = row['name'].strip()
        id_number = row['id_number'].strip()
        photo_path = row['photo_path'].strip() if row['photo_path'] else ""

        cursor.execute("SELECT uid FROM users WHERE name = ? COLLATE NOCASE AND id_number = ? COLLATE NOCASE", (name, id_number))
        existing_user = cursor.fetchone()

        if existing_user:
            cursor.execute("UPDATE users SET photo_path = ? WHERE name = ? COLLATE NOCASE AND id_number = ? COLLATE NOCASE", (photo_path, name, id_number))
        else:
            cursor.execute("SELECT 1 FROM users WHERE uid = ?", (uid,))
            if cursor.fetchone():
                cursor.execute("UPDATE users SET name = ?, id_number = ?, photo_path = ? WHERE uid = ?", (name, id_number, photo_path, uid))
            else:
                cursor.execute("INSERT INTO users (uid, name, id_number, photo_path) VALUES (?, ?, ?, ?)", (uid, name, id_number, photo_path))

conn.commit()
conn.close()
print("Database updated successfully.")