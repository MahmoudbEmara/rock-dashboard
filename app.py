from flask import Flask, request, jsonify, render_template_string, send_file
from datetime import datetime
import sqlite3
import os
import csv

app = Flask(__name__)

API_KEY = os.getenv("DASHBOARD_API_KEY", "REPLACE_ME_WITH_SECRET_KEY")
RESET_KEY = os.getenv("RESET_API_KEY", "REPLACE_ME_WITH_RESET_KEY")
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
@app.route('/dashboard')
def dashboard():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Limestone Detection Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 20px;
                background-color: #f7f7f7;
            }
            h1 {
                color: #333;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 40px;
                background-color: white;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }
            th, td {
                border: 1px solid #ddd;
                padding: 8px;
                text-align: center;
            }
            th {
                background-color: #4CAF50;
                color: white;
            }
            tr:nth-child(even) {
                background-color: #f2f2f2;
            }
            button {
                margin-bottom: 20px;
                padding: 10px 20px;
                background-color: #f44336;
                color: white;
                border: none;
                cursor: pointer;
                border-radius: 4px;
            }
            button:hover {
                background-color: #d32f2f;
            }
        </style>
    </head>
    <body>
        <h1>Limestone Detection Dashboard</h1>
        <button onclick="resetDashboard()">Reset Dashboard</button>
        <div id="tables"></div>
        <canvas id="barChart" width="800" height="400"></canvas>
        <p><a href="/history">View Full History</a> | <a href="/export">Export CSV</a></p>

        <script>
        async function fetchDashboardData() {
            const res = await fetch('/dashboard-data');
            return await res.json();
        }

        function renderTables(totals) {
            const container = document.getElementById('tables');
            container.innerHTML = '';

            for (const node in totals) {
                const stats = totals[node];
                let html = `<h3>${node}</h3>`;
                html += `<table><tr><th>Size Range</th><th>Total Count</th></tr>`;
                for (const size in stats) {
                    html += `<tr><td>${size}</td><td>${stats[size]}</td></tr>`;
                }
                html += `</table>`;
                container.innerHTML += html;
            }
        }

        let barChart;
        function renderChart(totals) {
            const labels = Array.from(new Set([].concat(...Object.values(totals).map(stats => Object.keys(stats)))));
            const datasets = Object.entries(totals).map(([node, stats]) => {
                return {
                    label: node,
                    data: labels.map(label => stats[label] || 0),
                    backgroundColor: 'rgba(' + Math.floor(Math.random()*255) + ',' +
                                               Math.floor(Math.random()*255) + ',' +
                                               Math.floor(Math.random()*255) + ',0.5)'
                };
            });

            const ctx = document.getElementById('barChart').getContext('2d');
            if (barChart) barChart.destroy();
            barChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { position: 'top' },
                        title: { display: true, text: 'Rock Size Distribution by Node' }
                    }
                }
            });
        }

        async function updateDashboard() {
            const data = await fetchDashboardData();
            renderTables(data);
            renderChart(data);
        }

        async function resetDashboard() {
            if (!confirm("Are you sure you want to reset all current dashboard data?")) return;

            const key = prompt("Enter the RESET KEY to confirm:");
            if (!key) return;

            try {
                const res = await fetch('/reset', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${key}`
                    }
                });
                const data = await res.json();
                if (res.ok) {
                    alert(data.message);
                    updateDashboard();
                } else {
                    alert(data.error || "Reset failed.");
                }
            } catch (err) {
                console.error(err);
                alert("Request failed.");
            }
        }

        updateDashboard();
        setInterval(updateDashboard, 10000); // refresh every 10s
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/dashboard-data')
def dashboard_data():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT node, size_range, SUM(count) FROM reports GROUP BY node, size_range")
        rows = cursor.fetchall()

    totals = {}
    for node, size, count in rows:
        if node not in totals:
            totals[node] = {}
        totals[node][size] = count

    return jsonify(totals)


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

@app.route('/reset', methods=['POST'])
def reset():
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {RESET_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM reports")
    return jsonify({"message": "Dashboard data reset."})


@app.route('/live-data')
def live_data():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT node, size_range, SUM(count) FROM reports GROUP BY node, size_range")
        rows = cursor.fetchall()

    totals = {}
    size_totals = {}
    for node, size, count in rows:
        if node not in totals:
            totals[node] = {}
        totals[node][size] = count

        if size not in size_totals:
            size_totals[size] = 0
        size_totals[size] += count

    return jsonify({
        "totals": totals,
        "size_totals": size_totals
    })

# call this once when the app is imported
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

