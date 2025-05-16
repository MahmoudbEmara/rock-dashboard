from flask import Flask, request, jsonify, render_template_string, send_file
from datetime import datetime
import sqlite3
import os
import csv

app = Flask(__name__)

API_KEY = os.getenv("DASHBOARD_API_KEY", "REPLACE_ME_WITH_SECRET_KEY")
DB_FILE = "reports.db"

# --- DB SETUP ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node TEXT,
                status TEXT,
                timestamp TEXT,
                size_range TEXT,
                count INTEGER
            )
        ''')

# --- UPDATE ENDPOINT ---
@app.route('/update', methods=['POST'])
def update():
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {API_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    node = data.get("node", "unknown-node")
    status = data.get("status", "unknown")
    rock_stats = data.get("rock_stats", {})
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_FILE) as conn:
        for size_range, count in rock_stats.items():
            conn.execute(
                "INSERT INTO reports (node, status, timestamp, size_range, count) VALUES (?, ?, ?, ?, ?)",
                (node, status, timestamp, size_range, count)
            )

    return jsonify({"message": "Data saved."}), 200

# --- DASHBOARD ---
@app.route('/')
@app.route('/dashboard')
def dashboard():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT node, size_range, SUM(count) FROM reports GROUP BY node, size_range")
        rows = cursor.fetchall()

    totals = {}
    for node, size, count in rows:
        if node not in totals:
            totals[node] = {}
        totals[node][size] = count

    html = """
    <h1>Limestone Detection Dashboard</h1>
    {% for node, stats in totals.items() %}
        <h3>{{ node }}</h3>
        <table border="1">
            <tr><th>Size Range</th><th>Total Count</th></tr>
            {% for size, count in stats.items() %}
                <tr><td>{{ size }}</td><td>{{ count }}</td></tr>
            {% endfor %}
        </table>
    {% endfor %}
    <p><a href="/history">View Full History</a> | <a href="/export">Export CSV</a></p>
    """
    return render_template_string(html, totals=totals)

# --- HISTORY VIEW ---
@app.route('/history')
def history():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, node, status, size_range, count FROM reports ORDER BY timestamp DESC LIMIT 100")
        rows = cursor.fetchall()

    html = """
    <h1>Recent Detection History</h1>
    <table border="1">
        <tr><th>Timestamp</th><th>Node</th><th>Status</th><th>Size Range</th><th>Count</th></tr>
        {% for row in rows %}
        <tr>
            <td>{{ row[0] }}</td><td>{{ row[1] }}</td><td>{{ row[2] }}</td><td>{{ row[3] }}</td><td>{{ row[4] }}</td>
        </tr>
        {% endfor %}
    </table>
    <p><a href='/dashboard'>Back to Dashboard</a></p>
    """
    return render_template_string(html, rows=rows)

# --- CSV EXPORT ---
@app.route('/export')
def export():
    filename = "report_export.csv"
    with sqlite3.connect(DB_FILE) as conn, open(filename, "w", newline="") as csvfile:
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, node, status, size_range, count FROM reports ORDER BY timestamp DESC")
        writer = csv.writer(csvfile)
        writer.writerow(["Timestamp", "Node", "Status", "Size Range", "Count"])
        writer.writerows(cursor.fetchall())

    return send_file(filename, as_attachment=True)

# call this once when the app is imported
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

