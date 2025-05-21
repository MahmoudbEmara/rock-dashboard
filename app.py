from flask import Flask, request, jsonify, render_template_string, send_file, redirect, session, url_for, Response
from datetime import datetime, timedelta, timezone
import psycopg2
import os
import pytz
from dateutil import parser
from urllib.parse import urlparse
from collections import defaultdict
import queue
import re

app = Flask(__name__)

# Config
EGYPT_TZ = pytz.timezone("Africa/Cairo")
app.secret_key = os.getenv("FLASK_SECRET_KEY")
API_KEY = os.getenv("DASHBOARD_API_KEY")
RESET_KEY = os.getenv("RESET_KEY")
USERNAME = os.getenv("LOGIN_USER")
PASSWORD = os.getenv("LOGIN_PASS")
subscribers = []

# PostgreSQL Connection
def get_db_conn():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set")
    result = urlparse(db_url)
    return psycopg2.connect(
        dbname=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )

# Init tables
def init_db():
    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS realdata (
                    id SERIAL PRIMARY KEY,
                    node TEXT,
                    status TEXT,
                    timestamp TIMESTAMPTZ,
                    size_range TEXT,
                    count INTEGER
                );
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            ''')
            conn.commit()

def setup():
    init_db()

# Login HTML (you can replace this with your full template later)
@app.route('/', methods=['GET', 'POST'])
def login():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Limestone Monitoring Beta</title>
        <style>
            body {
                background: url('/static/imgs/dashboard.jpg') no-repeat center center fixed;
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
            <h2>Welcome, Please Enter The Provided Username and Password</h2>
            <form method="post">
                <input name="username" type="text" placeholder="Username" required><br>
                <input name="password" type="password" placeholder="Password" required><br>
                <button type="submit">Login</button>
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


@app.route('/stream')
def stream():
    def event_stream():
        q = queue.Queue()
        subscribers.append(q)
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                    yield f"data: {data}\n\n"
                except queue.Empty:
                    # Keep connection alive
                    yield "data: ping\n\n"
        except GeneratorExit:
            subscribers.remove(q)

    return Response(event_stream(), content_type='text/event-stream')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/')

@app.route('/update', methods=['POST'])
def update():
    if request.headers.get("Authorization", "") != f"Bearer {API_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json or {}
    node = data.get("node", "unknown-node")
    status = data.get("status", "unknown")
    rock_stats = data.get("rock_stats", {})

    if not isinstance(rock_stats, dict):
        return jsonify({"error": "rock_stats must be a dictionary"}), 400

    allowed_sizes = {"<30mm", "30-50mm", "50-80mm", "80-150mm", ">150mm"}
    if any(size not in allowed_sizes for size in rock_stats.keys()):
        return jsonify({"error": "Invalid size_range in rock_stats"}), 400

    timestamp = datetime.now(timezone.utc)

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                for size_range, count in rock_stats.items():
                    cur.execute(
                        "INSERT INTO realdata (node, status, timestamp, size_range, count) VALUES (%s, %s, %s, %s, %s)",
                        (node, status, timestamp, size_range, count)
                    )
                cur.execute("INSERT INTO meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                            ("last_update", timestamp.isoformat()))
                conn.commit()
    except Exception as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500

    for q in subscribers:
        q.put("update")  # Sends to /stream listeners

    return jsonify({"message": "Data saved.", "timestamp": timestamp.isoformat()}), 200


@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect('/')
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Limestone Monitoring Dashboard Beta</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
        <style>
            /* Background image on body */
            body {
                background: url('/static/imgs/dashboard.jpg') no-repeat center center fixed;
                background-size: cover;
                font-family: Arial, sans-serif;
                margin: 20px;
                color: #333;
            }

            /* Add a semi-transparent white overlay container to keep content readable */
            #content-wrapper {
                background-color: rgba(255, 255, 255, 0.9);
                border-radius: 10px;
                padding: 20px 30px;
                max-width: 1200px;
                margin: 0 auto; /* centers horizontally */
                box-shadow: 0 0 15px rgba(0,0,0,0.15);
            }

            h1 {
                color: #222;
                text-align: center;
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

            #barChart {
                max-width: 1200px;
                max-height: 900px;
                width: 100%;
                height: auto;
                background: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 0 12px rgba(0,0,0,0.1);
            }

            /* Style the logout link as a button */
            a.logout-link {
                background-color: #555;
                color: white;
                padding: 8px 16px;
                text-decoration: none;
                border-radius: 4px;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div id="content-wrapper">
            <h1>Limestone Detection Dashboard</h1>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <div style="display: flex; gap: 10px;">
                    <button onclick="resetDashboard()">Reset Dashboard</button>
                    <button onclick="location.href='/history'">History</button>
                    <button onclick="location.href='/dailytrend'">Daily Trend</button>
                    <button onclick="location.href='/export'">Download CSV</button>
                </div>
                <a href="/logout" class="logout-link">Logout</a>
            </div>
            <div id="tables"></div>
            <canvas id="barChart"></canvas>
            <p id="last-updated" style="font-style: italic; color: #555;"></p>
        </div>
        <script>
        // Colors per size category for bars
        const categoryColors = {
            "<30mm": "#4CAF50",
            "30-50mm": "#2196F3",
            "50-80mm": "#FF9800",
            "80-150mm": "#9C27B0",
            ">150mm": "#F44336"
        };
        
        async function fetchDashboardData() {
            try {
                const res = await fetch("/dashboard-data");
                const data = await res.json();
        
                const totals = data.totals || {};
                const lastUpdated = data.last_updated || "Never";
        
                document.getElementById("last-updated").textContent = `Last updated: ${new Date(lastUpdated).toLocaleString()}`;
        
                const tablesContainer = document.getElementById("tables");
                tablesContainer.innerHTML = "";
        
                const labels = Object.keys(totals);  // Node names as labels (x-axis)
                const sizeCategories = ["<30mm", "30-50mm", "50-80mm", "80-150mm", ">150mm"];
        
                // Create tables as before (optional)
                for (const node of labels) {
                    const nodeData = totals[node];
                    const table = document.createElement("table");
        
                    let header = `<tr><th colspan="2">Node: ${node}</th></tr><tr><th>Size Range</th><th>Count</th></tr>`;
                    let total = 0;
                    let rows = sizeCategories.map(size => {
                        const count = nodeData[size] || 0;
                        total += count;
                        return `<tr><td>${size}</td><td>${count}</td></tr>`;
                    }).join("");
                    
                    // Add total row
                    rows += `<tr><td><strong>Total</strong> <small>(since 21/May/2025)</small></td><td><strong>${total}</strong></td></tr>`;

        
                    table.innerHTML = header + rows;
                    tablesContainer.appendChild(table);
                }
        
                // Build datasets per size category
                const datasets = sizeCategories.map(category => {
                    return {
                        label: category,
                        data: labels.map(node => totals[node][category] || 0),
                        backgroundColor: categoryColors[category],
                    };
                });
        
                const ctx = document.getElementById("barChart").getContext("2d");
                if (window.barChartInstance) {
                    window.barChartInstance.destroy();
                }
        
                window.barChartInstance = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: labels,  // nodes on x-axis
                        datasets: datasets
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: { position: 'top' },
                            datalabels: {
                                anchor: 'end',
                                align: 'top',
                                formatter: function (value, context) {
                                    const nodeIndex = context.dataIndex;
                                    const allDatasets = context.chart.data.datasets;
                                    
                                    // Sum all categories' values for the current node
                                    let nodeTotal = 0;
                                    for (let i = 0; i < allDatasets.length; i++) {
                                        nodeTotal += allDatasets[i].data[nodeIndex] || 0;
                                    }
                                
                                    if (nodeTotal === 0) return "0%";
                                
                                    const percent = (value / nodeTotal * 100).toFixed(1);
                                    return `${percent}%`;
                                },
                                font: { weight: 'bold' },
                                color: '#000'
                            }
                        },
                        scales: {
                            y: { beginAtZero: true }
                        }
                    },
                    plugins: [ChartDataLabels]
                });
        
            } catch (error) {
                console.error("Failed to load dashboard data", error);
                document.getElementById("tables").innerHTML = "<p style='color: red;'>Error loading data.</p>";
            }
        }
        
        function resetDashboard() {
            fetchDashboardData();
        }
        
        window.onload = () => {
            fetchDashboardData();
        
            const source = new EventSource("/stream");
            source.onmessage = function(event) {
                if (event.data === "update") {
                    console.log("New update received from server. Refreshing dashboard.");
                    fetchDashboardData();
                }
            };
        };
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route('/dashboard-data')
def dashboard_data():
    with get_db_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT node, size_range, SUM(count) FROM realdata GROUP BY node, size_range")
            rows = cursor.fetchall()

            cursor.execute("SELECT value FROM meta WHERE key='last_update'")
            row = cursor.fetchone()
            if row:
                dt = parser.isoparse(row[0])  # handles ISO8601 including Z and fractions
                last_updated = dt.isoformat()
            else:
                last_updated = None

    totals = {}
    for node, size, count in rows:
        if node not in totals:
            totals[node] = {}
        totals[node][size] = count

    return jsonify({
        "totals": totals,
        "last_updated": last_updated
    })

@app.route('/reset', methods=['POST'])
def reset():
    if not session.get('logged_in'):
        return redirect('/')
    if request.headers.get("Authorization", "") != f"Bearer {RESET_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM realdata")
            cur.execute("DELETE FROM meta WHERE key = 'last_update'")
            conn.commit()

    return jsonify({"message": "Dashboard data reset."})

@app.route('/dailytrend')
def dailytrend():
    if not session.get('logged_in'):
        return redirect('/')
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <title>Daily Size Distribution Trend</title>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
      <style>
        body {
          font-family: Arial, sans-serif;
          padding: 0;
          margin: 0;
          background: url('/static/imgs/dailytrend.jpg') no-repeat center center fixed;
          background-size: cover;
          display: flex;
          justify-content: center;
          min-height: 100vh;
          align-items: flex-start;
        }
        .container {
          background-color: rgba(255, 255, 255, 0.85);
          padding: 30px;
          border-radius: 10px;
          box-shadow: 0 0 15px rgba(0,0,0,0.2);
          max-width: 1200px;
          margin: 40px 20px;
          width: 100%;
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        #chart-container {
          max-width: 1100px;
          width: 100%;
          max-height: 900px;
          background: white;
          padding: 20px;
          border-radius: 10px;
          box-shadow: 0 0 12px rgba(0,0,0,0.1);
          overflow: visible;
        }

        canvas {
          width: 100% !important;
          height: 600px !important; /* fix canvas height explicitly */
          display: block;
        }

        #last-updated {
          font-style: italic;
          color: #555;
          margin-top: 10px;
          text-align: center;
        }
        h1 {
          margin-bottom: 20px;
        }
        .topbar button {
          margin: 0 5px 20px 0;
          padding: 8px 15px;
          border: none;
          border-radius: 5px;
          background-color: #4CAF50;
          color: white;
          cursor: pointer;
        }
        .topbar button:hover {
          background-color: #45a049;
        }
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Size Distribution Trend</h1>
        <div class="topbar">
          <button onclick="location.href='/dashboard'">Back to Dashboard</button>
          <button onclick="location.href='/history'">History</button>
        </div>

        <div id="chart-container">
          <canvas id="dailyChart"></canvas>
        </div>
        <p id="last-updated"></p>
      </div>

        <script>
          let dailyChartInstance = null;
        
          async function fetchTrendData() {
            const res = await fetch('/api/daily-trend');
            return await res.json();
          }
        
          function renderChart(data) {
            const ctx = document.getElementById('dailyChart').getContext('2d');
        
            // Destroy existing chart instance if it exists
            if (dailyChartInstance) {
              dailyChartInstance.destroy();
            }
        
            dailyChartInstance = new Chart(ctx, {
              type: 'line',
              data: {
                labels: data.timestamps.map(t => {
                  const dt = new Date(t);
                  return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                }),
                datasets: data.datasets.map(ds => ({
                  label: ds.label,
                  data: ds.values,
                  fill: false,
                  borderColor: ds.color,
                  tension: 0.1
                }))
              },
              options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                  legend: {
                    position: 'top'
                  },
                  title: {
                    display: true,
                    text: 'Category Percentages Over Time'
                  }
                },
                scales: {
                  y: {
                    beginAtZero: true,
                    max: 100,
                    title: {
                      display: true,
                      text: '% of Total Count'
                    }
                  },
                  x: {
                    title: {
                      display: true,
                      text: 'Time (hh:mm)'
                    }
                  }
                }
              }
            });
          }
        
          async function updateChart(updateTimestamp = false) {
            console.log("Fetching trend data...");
            const data = await fetchTrendData();
            renderChart(data);
        
            if (updateTimestamp && data.last_updated) {
              const dt = new Date(data.last_updated);
              document.getElementById("last-updated").innerText = `Last updated: ${dt.toLocaleTimeString()}`;
            }
          }
        
          // Initial chart load
          updateChart(false);
        
          // SSE updates
          const source = new EventSource("/stream");
          source.onmessage = function (event) {
            if (event.data === "update") {
              console.log("New update received from server (daily trend). Refreshing chart.");
              updateChart(true);
            }
          };
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route('/api/daily-trend')
def api_daily_trend():
    now_precise = datetime.now(timezone.utc)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=24)

    categories = ['<30mm', '30-50mm', '50-80mm', '80-150mm', '>150mm']
    color_map = {
        '<30mm': '#1f77b4',
        '30-50mm': '#ff7f0e',
        '50-80mm': '#2ca02c',
        '80-150mm': '#d62728',
        '>150mm': '#9467bd',
    }

    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(""" 
            SELECT 
                DATE_TRUNC('minute', timestamp AT TIME ZONE 'UTC') AS minute,
                size_range,
                SUM(count) AS total
            FROM realdata
            WHERE timestamp >= %s AND timestamp < %s
            GROUP BY minute, size_range
            ORDER BY minute;
        """, (start_time, end_time))
        rows = cursor.fetchall()

    # Organize data into a dictionary
    minute_bins = {}
    for minute, size_range, total in rows:
        key = minute.replace(tzinfo=timezone.utc).isoformat()
        if key not in minute_bins:
            minute_bins[key] = defaultdict(int)
        minute_bins[key][size_range] += total

    sorted_times = sorted(minute_bins.keys())

    # Build dataset per category
    datasets = []
    for cat in categories:
        values = []
        for t in sorted_times:
            total_count = sum(minute_bins[t].values())
            percent = (minute_bins[t][cat] / total_count * 100) if total_count else 0
            values.append(round(percent, 2))
        datasets.append({
            "label": cat,
            "values": values,
            "color": color_map.get(cat, "#000000")
        })

    return jsonify({
        "timestamps": sorted_times,
        "datasets": datasets,
        "last_updated": now_precise.isoformat()  # send precise current time
    })

# --- Add this route to serve the history chart page ---
@app.route('/history')
def history():
    if not session.get('logged_in'):
        return redirect('/')
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <title>Weekly Size Distribution Trend</title>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
      <style>
        body {
          font-family: Arial, sans-serif;
          padding: 0;
          margin: 0;
          background: url('/static/imgs/history.jpg') no-repeat center center fixed;
          background-size: cover;
          display: flex;
          justify-content: center;
          min-height: 100vh;
          align-items: flex-start;
        }
        .container {
          background-color: rgba(255, 255, 255, 0.85);
          padding: 30px;
          border-radius: 10px;
          box-shadow: 0 0 15px rgba(0,0,0,0.2);
          max-width: 1200px;
          margin: 40px 20px;
          width: 100%;
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        #chart-container {
          max-width: 1100px;
          width: 100%;
          max-height: 900px;
          background: white;
          padding: 20px;
          border-radius: 10px;
          box-shadow: 0 0 12px rgba(0,0,0,0.1);
          overflow: hidden;
        }
        canvas {
          width: 100% !important;
          height: 100% !important;
          display: block;
        }
        h1 {
          margin-bottom: 20px;
        }
        .topbar button {
          margin: 0 5px 20px 0;
          padding: 8px 15px;
          border: none;
          border-radius: 5px;
          background-color: #4CAF50;
          color: white;
          cursor: pointer;
        }
        .topbar button:hover {
          background-color: #45a049;
        }
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Size Distribution Percentages (Past 7 Days)</h1>
        <div class="topbar">
          <button onclick="location.href='/dashboard'">Back to Dashboard</button>
          <button onclick="location.href='/dailytrend'">Daily Trend</button>
        </div>
        <div id="chart-container">
          <canvas id="historyChart"></canvas>
        </div>
      </div>

      <script>
        async function fetchHistory() {
          const res = await fetch('/api/history');
          return await res.json();
        }

        function renderChart(data) {
          const ctx = document.getElementById('historyChart').getContext('2d');
          new Chart(ctx, {
            type: 'line',
            data: {
              labels: data.dates,
              datasets: [
                {
                  label: 'Small (<= 50mm) %',
                  data: data.small,
                  borderColor: 'rgba(75, 192, 192, 1)',
                  backgroundColor: 'rgba(75, 192, 192, 0.2)',
                  fill: false,
                  tension: 0.2
                },
                {
                  label: 'Large (> 50mm) %',
                  data: data.large,
                  borderColor: 'rgba(255, 99, 132, 1)',
                  backgroundColor: 'rgba(255, 99, 132, 0.2)',
                  fill: false,
                  tension: 0.2
                }
              ]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              scales: {
                y: {
                  beginAtZero: true,
                  max: 100,
                  title: {
                    display: true,
                    text: 'Percentage (%)'
                  }
                },
                x: {
                  title: {
                    display: true,
                    text: 'Date (dd/mm/yy)'
                  }
                }
              }
            }
          });
        }

        fetchHistory().then(renderChart);
      </script>
    </body>
    </html>
    """
    return render_template_string(html)

# --- Add this API endpoint to return JSON data for the past 7 days ---
@app.route('/api/history')
def api_history():
    today = datetime.now(tz=EGYPT_TZ).date()
    seven_days_ago = today - timedelta(days=6)  # including today = 7 days

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            # Query counts grouped by date and size_range, filter last 7 days
            cur.execute("""
                SELECT
                    DATE(timestamp AT TIME ZONE 'Africa/Cairo') as day,
                    size_range,
                    SUM(count) as total_count
                FROM realdata
                WHERE DATE(timestamp AT TIME ZONE 'Africa/Cairo') >= %s
                GROUP BY day, size_range
                ORDER BY day;
            """, (seven_days_ago,))
            rows = cur.fetchall()

    # Initialize a dict to hold counts per day
    day_data = {}
    for i in range(7):
        day = seven_days_ago + timedelta(days=i)
        day_data[day] = {"small": 0, "large": 0}

    # Aggregate counts
    for day, size_range, total_count in rows:
        # Determine small or large
        # Assume size_range string contains a number, e.g. "30-50mm", "80-150mm"
        # Extract lower bound or midpoint for classification
        size_range_clean = size_range.lower().replace(" ", "")

        # Extract all numbers from the string, as a list of ints
        numbers = [int(num) for num in re.findall(r'\d+', size_range_clean)]

        classification = "large"  # default

        if numbers:
            # For '>30mm', numbers = [30]
            # For '30-50mm', numbers = [30, 50]
            # Logic: if the upper bound or the average is <= 50, classify as small

            # If only one number, like >30, check if it's <= 50
            if len(numbers) == 1:
                if numbers[0] <= 50:
                    classification = "small"
            else:
                # multiple numbers (e.g., 30 and 50), take average
                avg = sum(numbers) / len(numbers)
                if avg <= 50:
                    classification = "small"

        if day in day_data:
            day_data[day][classification] += total_count

    # Prepare data for JSON response
    dates = []
    small_percents = []
    large_percents = []

    for day in sorted(day_data.keys()):
        small_count = day_data[day]["small"]
        large_count = day_data[day]["large"]
        total = small_count + large_count
        if total > 0:
            small_pct = round((small_count / total) * 100, 2)
            large_pct = round((large_count / total) * 100, 2)
        else:
            small_pct = 0
            large_pct = 0
        dates.append(day.strftime("%d/%m/%y"))
        small_percents.append(small_pct)
        large_percents.append(large_pct)

    return jsonify({
        "dates": dates,
        "small": small_percents,
        "large": large_percents
    })


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
