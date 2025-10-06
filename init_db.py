# init_db.py
import sqlite3
import hashlib

DB = "payup.db"

def hashpw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

conn = sqlite3.connect(DB)
c = conn.cursor()

# users table
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    email TEXT,
    password TEXT,
    referral_code TEXT UNIQUE,
    referred_by TEXT,
    balance REAL DEFAULT 0.0,
    is_admin INTEGER DEFAULT 0
)
""")

# videos watched log (user_id, video_id, watched_seconds)
c.execute("""
CREATE TABLE IF NOT EXISTS watched (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    video_id TEXT,
    watched_seconds INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

# withdrawals
c.execute("""
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    status TEXT DEFAULT 'pending',
    request_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    processed_time DATETIME
)
""")

# create a default admin user if not present
admin_user = ("admin", "admin@example.com", hashpw("adminpass"), "admincode", None, 0.0, 1)
try:
    c.execute("INSERT INTO users (username, email, password, referral_code, referred_by, balance, is_admin) VALUES (?, ?, ?, ?, ?, ?, ?)",
              admin_user)
    print("Admin user created: username=admin password=adminpass")
except Exception as e:
    print("Admin already exists or error:", e)

conn.commit()
conn.close()
 