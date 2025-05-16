# Rock Dashboard

This Flask app receives detection results from Raspberry Pis, stores them in SQLite, and displays them on a public dashboard.

## Routes

- `/update` – POST endpoint for Pis
- `/dashboard` – live totals per node
- `/history` – recent logs
- `/export` – download CSV

## Setup

1. Clone repo
2. Set your API key in `.env`
3. Run locally: `gunicorn app:app`
4. Deploy to [Railway](https://railway.app)
