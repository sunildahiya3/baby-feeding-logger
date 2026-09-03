import os
import sqlite3
import psycopg2
from flask import Flask, render_template, request, jsonify, session
from datetime import datetime
import pytz

app = Flask(__name__)

# Secret key for session management
app.secret_key = os.environ.get('SECRET_KEY', 'default-baby-logger-secret-key-12345')

# Admin password (Default: "baby" — change via APP_PASSWORD env variable on Render)
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'baby')

# Database Connection Helper (PostgreSQL on Render, SQLite locally)
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    if DATABASE_URL:
        # PostgreSQL on Render
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        # SQLite fallback for local running
        conn = sqlite3.connect('baby_logger.db')
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS feeding_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_type TEXT NOT NULL,
                date_str TEXT NOT NULL,
                time_str TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        ''')
    
    conn.commit()
    cursor.close()
    conn.close()

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
    return render_template('index.html')

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

    if not feed_type:
        return jsonify({"status": "error", "message": "Feeding type required"}), 400

    # Get current timestamp strictly in IST
    ist_now = get_ist_now()
    date_str = ist_now.strftime('%d %m %Y')  # DD MM YYYY
    time_str = ist_now.strftime('%H %M')     # HH MM

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        cursor.execute('''
            INSERT INTO feeding_logs (feed_type, date_str, time_str)
            VALUES (%s, %s, %s)
        ''', (feed_type, date_str, time_str))
    else:
        cursor.execute('''
            INSERT INTO feeding_logs (feed_type, date_str, time_str)
            VALUES (?, ?, ?)
        ''', (feed_type, date_str, time_str))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"status": "success", "entry": {"feed_type": feed_type, "date": date_str, "time": time_str}})

@app.route('/api/records', methods=['GET'])
def get_records():
    if not is_authenticated():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT feed_type, date_str, time_str FROM feeding_logs ORDER BY id DESC')
    rows = cursor.fetchall()
    
    cursor.close()
    conn.close()

    records = [{"feed_type": r[0], "date": r[1], "time": r[2]} for r in rows]
    return jsonify(records)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)