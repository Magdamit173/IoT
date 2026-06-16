from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone
import sqlite3
import re
import os
import threading
from dotenv import load_dotenv
import pandas as pd
from sklearn.ensemble import IsolationForest

load_dotenv()

app = Flask(__name__)

CORS(app, origins="*",
     allow_headers=["Content-Type", "X-API-Key"],
     methods=["GET", "POST", "OPTIONS"])

DB_FILE    = os.getenv('DB_FILE',    'system.db')
API_KEY    = os.getenv('API_KEY',    '')
MAX_PAYLOAD = int(os.getenv('MAX_PAYLOAD', '2048'))
PORT       = int(os.getenv('PORT',   '5000'))

if not API_KEY:
    raise RuntimeError("API_KEY is not set. Add it to your .env file.")

def init_db():
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

    cursor.execute('''CREATE TABLE IF NOT EXISTS anomalies (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT NOT NULL,
        id_number   TEXT NOT NULL,
        description TEXT NOT NULL
    )''')

    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn

def validate_uid(uid):
    if not isinstance(uid, str):
        return False
    return bool(re.match(r'^[A-F0-9]{8,14}$', uid))

def validate_string(val, max_length=50):
    if not isinstance(val, str) or len(val) == 0 or len(val) > max_length:
        return False
    return bool(re.match(r'^[a-zA-Z0-9\s\-\.,]+$', val))

def validate_id_number(val):
    if not isinstance(val, str) or len(val) == 0 or len(val) > 50:
        return False, None
    return True, val

def validate_float(val, min_val, max_val):
    try:
        f = float(val)
        return min_val <= f <= max_val, f
    except (ValueError, TypeError):
        return False, None

# ---------------------------------------------------------------------------
# Machine Learning Background Task
# ---------------------------------------------------------------------------
def run_ml_background(db_path):
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        df = pd.read_sql_query("SELECT * FROM attendance", conn)
        
        # Require 50 entries to establish a baseline
        if len(df) < 50:
            conn.close()
            return
            
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['hour'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.dayofweek
        df['entry_numeric'] = df['entry_type'].map({'RFID': 0, 'Manual': 1})
        
        df = df.sort_values(by=['id_number', 'timestamp'])
        df['time_diff'] = df.groupby('id_number')['timestamp'].diff().dt.total_seconds().fillna(86400)
        
        features = ['hour', 'day_of_week', 'entry_numeric', 'time_diff']
        X = df[features].fillna(0)
        
        model = IsolationForest(contamination=0.05, random_state=42)
        df['anomaly'] = model.fit_predict(X)
        
        anomalies = df[df['anomaly'] == -1]
        cursor = conn.cursor()
        
        for _, row in anomalies.iterrows():
            desc = "Suspicious behavior detected."
            
            # Example 1: Rapid manual entry after a recent scan
            if row['time_diff'] < 120 and row['entry_numeric'] == 1:
                desc = "Suspicious: Rapid manual entry right after previous scan."
            # Example 2: Unusual manual shift (Isolation forest flags the deviation)
            elif row['entry_numeric'] == 1:
                desc = "Suspicious: Unusual shift to manual entry. Possible lost/broken RFID."
            # Example 3 is implicitly handled: ML won't flag normal lunchtime habits.
                
            cursor.execute(
                "SELECT 1 FROM anomalies WHERE timestamp = ? AND id_number = ?", 
                (row['timestamp'].isoformat(), row['id_number'])
            )
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO anomalies (timestamp, id_number, description) VALUES (?, ?, ?)",
                    (row['timestamp'].isoformat(), row['id_number'], desc)
                )
        
        conn.commit()
        conn.close()
    except Exception:
        pass # Fail silently so the main server never crashes

@app.before_request
def enforce_security():
    if request.method == 'OPTIONS':
        return    
    if request.content_length and request.content_length > MAX_PAYLOAD:
        return jsonify({"error": "Payload Too Large"}), 413
    if request.path in ['/scan', '/manual', '/environment']:
        if request.headers.get('X-API-Key') != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401

@app.route('/scan', methods=['POST'])
def scan():
    data = request.get_json(silent=True)
    if not data or 'uid' not in data:
        return jsonify({"error": "Bad Request"}), 400

    uid = str(data['uid']).strip().upper()
    if not validate_uid(uid):
        return jsonify({"error": "Invalid UID"}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, id_number, photo_path FROM users WHERE uid = ?", (uid,)
        )
        user = cursor.fetchone()

        if not user:
            return jsonify({"error": "Not Found"}), 404

        ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
        cursor.execute(
            "INSERT INTO attendance (timestamp, name, id_number, entry_type) VALUES (?, ?, ?, ?)",
            (ts, user['name'], user['id_number'], 'RFID')
        )
        conn.commit()
        
        # Trigger ML analysis in the background
        threading.Thread(target=run_ml_background, args=(DB_FILE,)).start()
        
        return jsonify(dict(user)), 200

    except sqlite3.Error:
        return jsonify({"error": "Server Error"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/manual', methods=['POST'])
def manual():
    data = request.get_json(silent=True)
    if not data or not all(k in data for k in ('name', 'id', 'purpose')):
        return jsonify({"error": "Bad Request"}), 400

    name    = str(data['name']).strip()
    purpose = str(data['purpose']).strip()

    ok, id_number = validate_id_number(str(data['id']).strip())
    if not ok:
        return jsonify({"error": "Invalid Input: id must be a non-empty string"}), 400

    if not validate_string(name) or not validate_string(purpose, 100):
        return jsonify({"error": "Invalid Input"}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
        cursor.execute(
            "INSERT INTO attendance (timestamp, name, id_number, entry_type, purpose) VALUES (?, ?, ?, ?, ?)",
            (ts, name, id_number, 'Manual', purpose)
        )
        conn.commit()
        
        # Trigger ML analysis in the background
        threading.Thread(target=run_ml_background, args=(DB_FILE,)).start()
        
        return jsonify({"status": "Success"}), 201

    except sqlite3.Error:
        return jsonify({"error": "Server Error"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/environment', methods=['POST'])
def environment():
    data = request.get_json(silent=True)
    if not data or not all(k in data for k in ('temperature', 'humidity')):
        return jsonify({"error": "Bad Request"}), 400

    ok_t, temperature = validate_float(data['temperature'], -50.0, 100.0)
    ok_h, humidity    = validate_float(data['humidity'],      0.0, 100.0)

    if not ok_t or not ok_h:
        return jsonify({"error": "Invalid sensor values"}), 400

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
        cursor.execute(
            "INSERT INTO environment (timestamp, temperature, humidity) VALUES (?, ?, ?)",
            (ts, temperature, humidity)
        )
        conn.commit()
        return jsonify({"status": "Success"}), 201

    except sqlite3.Error:
        return jsonify({"error": "Server Error"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/status', methods=['GET'])
def status():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT timestamp, temperature, humidity FROM environment ORDER BY timestamp DESC LIMIT 1"
        )
        env_latest = cursor.fetchone()

        cursor.execute(
            "SELECT timestamp, name, id_number, entry_type, purpose FROM attendance ORDER BY timestamp DESC LIMIT 5"
        )
        att_latest = cursor.fetchall()

        cursor.execute(
            "SELECT timestamp, id_number, description FROM anomalies ORDER BY timestamp DESC LIMIT 5"
        )
        anom_latest = cursor.fetchall()

        return jsonify({
            "environment":        dict(env_latest) if env_latest else None,
            "recent_attendance":  [dict(r) for r in att_latest],
            "recent_anomalies":   [dict(a) for a in anom_latest]
        }), 200

    except sqlite3.Error:
        return jsonify({"error": "Server Error"}), 500
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)