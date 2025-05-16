from flask import Flask, request, jsonify, render_template_string, send_file, redirect, session, url_for
from datetime import datetime
import sqlite3
import os
import csv

app = Flask(__name__)

API_KEY = os.getenv("DASHBOARD_API_KEY", "REPLACE_ME_WITH_SECRET_KEY")
RESET_KEY = os.getenv("RESET_KEY", "REPLACE_ME_WITH_RESET_KEY")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "something_really_secret")
USERNAME = os.getenv("LOGIN_USER", "admin")
PASSWORD = os.getenv("LOGIN_PASS", "pass")

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


@app.route('/', methods=['GET', 'POST'])
def login():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Limestone Monitoring Beta</title>
        <style>
            body {
                background: url('https://images.unsplash.com/photo-1606228377053-9225bd1b5e13?auto=format&fit=crop&w=1350&q=80') no-repeat center center fixed;
                background-size: cover;
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }
            .login-box {
                background-color: rgba(255, 255, 255, 0.85);
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 0 15px rgba(0,0,0,0.2);
                text-align: center;
                width: 300px;
            }
            input[type="text"],
            input[type="password"] {
                width: 100%;
                padding: 10px;
                margin: 10px 0;
                border: 1px solid #ccc;
                border-radius: 5px;
            }
            button {
                padding: 10px 20px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
            }
            button:hover {
                background-color: #45a049;
            }
            .error {
                color: red;
                margin-top: 10px;
            }
        </style>
    </head>
    <body>
        <div class="login-box">
            <h2>Wanna look at some rock size data buddy ? </h2>
            <form method="post">
                <input name="username" type="text" placeholder="Username" required><br>
                <input name="password" type="password" placeholder="Password" required><br>
                <button type="submit">yes I'm a nerd</button>
            </form>
            {% if error %}
                <p class="error">{{ error }}</p>
            {% endif %}
        </div>
    </body>
    </html>
    """

    if request.method == 'POST':
        if request.form['username'] == USERNAME and request.form['password'] == PASSWORD:
            session['logged_in'] = True
            return redirect('/dashboard')
        else:
            return render_template_string(html, error="Invalid credentials.")
    return render_template_string(html)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/')

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
    if not session.get('logged_in'):
        return redirect('/')
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
                const orderedSizes = ["<30mm", "30-50mm", "50-80mm", "80-150mm", ">150mm"];
                for (const size of orderedSizes) {
                    const count = stats[size] || 0;
                    html += `<tr><td>${size}</td><td>${count}</td></tr>`;
                }
                html += `</table>`;
                container.innerHTML += html;
            }
        }

        let barChart;
        function renderChart(totals) {
            const sizeLabels = ["<30mm", "30-50mm", "50-80mm", "80-150mm", ">150mm"];
            const colorsBySize = {
                "<30mm": "rgba(54, 162, 235, 0.7)",     // blue
                "30-50mm": "rgba(255, 99, 132, 0.7)",    // red
                "50-80mm": "rgba(255, 206, 86, 0.7)",    // yellow
                "80-150mm": "rgba(75, 192, 192, 0.7)",   // teal
                ">150mm": "rgba(153, 102, 255, 0.7)"     // purple
            };
        
            const nodes = Object.keys(totals);
        
            const datasets = sizeLabels.map(sizeLabel => {
                return {
                    label: sizeLabel,
                    data: nodes.map(node => totals[node][sizeLabel] || 0),
                    backgroundColor: colorsBySize[sizeLabel]
                };
            });
        
            const ctx = document.getElementById('barChart').getContext('2d');
            if (barChart) barChart.destroy();
            barChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: nodes,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { position: 'top' },
                        title: { display: true, text: 'Rock Size Distribution by Node' }
                    },
                    scales: {
                        x: { stacked: false },
                        y: { beginAtZero: true }
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
        setInterval(updateDashboard, 200000); // refresh every 200s
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/dashboard-data')
def dashboard_data():
    if not session.get('logged_in'):
        return redirect('/')
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
    if not session.get('logged_in'):
        return redirect('/')

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
    if not session.get('logged_in'):
        return redirect('/')
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
    if not session.get('logged_in'):
        return redirect('/')
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {RESET_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM reports")
    return jsonify({"message": "Dashboard data reset."})


@app.route('/live-data')
def live_data():
    if not session.get('logged_in'):
        return redirect('/')
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

