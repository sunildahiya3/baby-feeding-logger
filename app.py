import os
import sqlite3
import psycopg
from flask import Flask, render_template, request, jsonify, session
from datetime import datetime
import pytz

app = Flask(__name__)
DB_NAME = 'baby_logger.db'

# Secret key for session management
app.secret_key = os.environ.get('SECRET_KEY', 'default-baby-logger-secret-key-12345')

# Admin password (Default: "baby" — change via APP_PASSWORD env variable on Render)
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'baby')

# Database Connection Helper (PostgreSQL on Render, SQLite locally)
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    if DATABASE_URL:
        # PostgreSQL on Render
        conn = psycopg.connect(DATABASE_URL, sslmode='require')
    else:
        # SQLite fallback for local running
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
    return conn

# Initialize Database Schema
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS feeding_logs (
                id SERIAL PRIMARY KEY,
                feed_type VARCHAR(50) NOT NULL,
                date_str VARCHAR(20) NOT NULL,
                time_str VARCHAR(20) NOT NULL,
                duration_minutes INTEGER,
                quantity_ml INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        cursor.execute('ALTER TABLE feeding_logs ADD COLUMN IF NOT EXISTS duration_minutes INTEGER')
        cursor.execute('ALTER TABLE feeding_logs ADD COLUMN IF NOT EXISTS quantity_ml INTEGER')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS feeding_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_type TEXT NOT NULL,
                date_str TEXT NOT NULL,
                time_str TEXT NOT NULL,
                duration_minutes INTEGER,
                quantity_ml INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        columns = {row[1] for row in cursor.execute('PRAGMA table_info(feeding_logs)')}
        if 'duration_minutes' not in columns:
            cursor.execute('ALTER TABLE feeding_logs ADD COLUMN duration_minutes INTEGER')
        if 'quantity_ml' not in columns:
            cursor.execute('ALTER TABLE feeding_logs ADD COLUMN quantity_ml INTEGER')

    if DATABASE_URL:
        cursor.execute('CREATE TABLE IF NOT EXISTS schema_migrations (migration_name VARCHAR(100) PRIMARY KEY)')
        cursor.execute("SELECT migration_name FROM schema_migrations WHERE migration_name = 'remove-latest-pumped-milk'")
    else:
        cursor.execute('CREATE TABLE IF NOT EXISTS schema_migrations (migration_name TEXT PRIMARY KEY)')
        cursor.execute("SELECT migration_name FROM schema_migrations WHERE migration_name = 'remove-latest-pumped-milk'")
    if cursor.fetchone() is None:
        cursor.execute("SELECT id FROM feeding_logs WHERE feed_type = 'Pumped Milk' ORDER BY id DESC LIMIT 1")
        latest_pumped = cursor.fetchone()
        if latest_pumped:
            if DATABASE_URL:
                cursor.execute('DELETE FROM feeding_logs WHERE id = %s', (latest_pumped[0],))
            else:
                cursor.execute('DELETE FROM feeding_logs WHERE id = ?', (latest_pumped[0],))
        if DATABASE_URL:
            cursor.execute("INSERT INTO schema_migrations (migration_name) VALUES ('remove-latest-pumped-milk')")
        else:
            cursor.execute("INSERT INTO schema_migrations (migration_name) VALUES ('remove-latest-pumped-milk')")

    cursor.execute("SELECT id FROM feeding_logs WHERE feed_type = 'Breast Milk' AND time_str IN ('21 42', '21:42') ORDER BY id")
    duplicate_ids = [row[0] for row in cursor.fetchall()][1:]
    for duplicate_id in duplicate_ids:
        if DATABASE_URL:
            cursor.execute('DELETE FROM feeding_logs WHERE id = %s', (duplicate_id,))
        else:
            cursor.execute('DELETE FROM feeding_logs WHERE id = ?', (duplicate_id,))
    
    conn.commit()
    cursor.close()
    conn.close()

init_db()

# Helper function to get current time in Indian Standard Time (IST)
def get_ist_now():
    ist_tz = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist_tz)

def is_authenticated():
    return session.get('logged_in', False)

# ----------------- ROUTES -----------------

@app.route('/')
def home():
    if not is_authenticated():
        return render_template('login.html')
    ist_now = get_ist_now()
    return render_template('index.html', default_date=ist_now.strftime('%Y-%m-%d'), default_time=ist_now.strftime('%H:%M'))

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    password = data.get('password', '')

    if password == APP_PASSWORD:
        session['logged_in'] = True
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": "Incorrect password"}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return jsonify({"status": "success"})

@app.route('/api/feed', methods=['POST'])
def add_feed():
    if not is_authenticated():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json()
    feed_type = data.get('feed_type')
    duration_minutes = data.get('duration_minutes')
    quantity_ml = data.get('quantity_ml')
    date_value = data.get('date')
    time_value = data.get('time')

    if not feed_type:
        return jsonify({"status": "error", "message": "Feeding type required"}), 400

    valid_types = {'Breast Milk', 'Formula Milk', 'Pumped Milk', 'Urination', 'Potty'}
    if feed_type not in valid_types:
        return jsonify({"status": "error", "message": "Invalid event type"}), 400

    try:
        duration_minutes = int(duration_minutes) if duration_minutes not in (None, '') else None
        quantity_ml = int(quantity_ml) if quantity_ml not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Measurements must be whole numbers"}), 400

    if duration_minutes is not None and duration_minutes <= 0:
        return jsonify({"status": "error", "message": "Duration must be greater than zero"}), 400
    if quantity_ml is not None and quantity_ml <= 0:
        return jsonify({"status": "error", "message": "Quantity must be greater than zero"}), 400
    if feed_type == 'Breast Milk' and duration_minutes is None:
        return jsonify({"status": "error", "message": "Duration is required for Breast Milk"}), 400
    if feed_type in {'Formula Milk', 'Pumped Milk'} and quantity_ml is None:
        return jsonify({"status": "error", "message": "Quantity is required for milk"}), 400

    ist_now = get_ist_now()
    try:
        selected_date = datetime.strptime(date_value, '%Y-%m-%d').date() if date_value else ist_now.date()
        selected_time = datetime.strptime(time_value, '%H:%M').time() if time_value else ist_now.time().replace(second=0, microsecond=0)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Enter a valid date and time"}), 400

    date_str = selected_date.strftime('%d %m %Y')
    time_str = selected_time.strftime('%H %M')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        cursor.execute('''
            INSERT INTO feeding_logs (feed_type, date_str, time_str, duration_minutes, quantity_ml)
            VALUES (%s, %s, %s, %s, %s)
        ''', (feed_type, date_str, time_str, duration_minutes, quantity_ml))
    else:
        cursor.execute('''
            INSERT INTO feeding_logs (feed_type, date_str, time_str, duration_minutes, quantity_ml)
            VALUES (?, ?, ?, ?, ?)
        ''', (feed_type, date_str, time_str, duration_minutes, quantity_ml))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status": "success", "entry": {"feed_type": feed_type, "date": date_str, "time": time_str, "duration_minutes": duration_minutes, "quantity_ml": quantity_ml}})

@app.route('/api/records', methods=['GET'])
def get_records():
    if not is_authenticated():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT feed_type, date_str, time_str, duration_minutes, quantity_ml FROM feeding_logs ORDER BY id DESC')
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()

    records = [{"feed_type": r[0], "date": r[1], "time": r[2], "duration_minutes": r[3], "quantity_ml": r[4]} for r in rows]
    return jsonify(records)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)