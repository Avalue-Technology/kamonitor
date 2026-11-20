# KAMonitor ELI5

A demo of a key-account monitoring dashboard: sales growth and product quality for VIP customers, explained in plain language by a locally hosted LLM.

KAMonitor 是一套 VIP 客戶經營儀表板的展示版：把銷售成長與產品品質放在同一個畫面，並由地端 LLM 用白話解讀。

> **All data is simulated.** Customers, orders, quality events and product models in this demo are fictional and do not represent any real company or product.
>
> **本專案所有資料皆為模擬資料**：客戶、訂單、品質事件與機種皆為虛構，不代表任何真實公司或產品。

## What you can see

- **Overview** — a quality bubble chart, a model × customer risk matrix, a risk ranking, and a growth matrix (revenue share × growth vs. the company), each with a short AI reading.
- **Customer page** — a *Sales* tab and a *Quality* tab. Each finding is a card you can open to see the underlying numbers.
- **Traceable AI text** — every number in the AI text comes from a fact list computed with SQL and rules; the model only rewrites the facts into sentences.
- English, Traditional Chinese and Simplified Chinese UI. Simplified Chinese is converted from Traditional Chinese with [OpenCC](https://github.com/BYVoid/OpenCC) at runtime.

The AI text is pre-generated and shipped with the demo data, so no LLM is needed to run the demo. The "regenerate" buttons are therefore hidden.

## Quick start (Docker)

Requires Docker with Compose v2.

1. Download `kamonitor_demo.sql.gz` from the [Releases](../../releases) page and put it in the `db/` folder.
2. Start everything:

   ```bash
   docker compose up --build
   ```

3. Open http://localhost:8111

The first start imports the demo data into MySQL, which takes about a minute. To reset the data, run `docker compose down -v` and start again.

## Project layout

```
backend/    FastAPI API (read-only), also serves the built frontend
frontend/   Vue 3 + Vite + ECharts
db/         put the demo data dump here
```

## Running without Docker

You need MySQL 8, Python 3.12 and Node.js 20+.

```bash
# Import the demo data into a database named kamonitor
gunzip -c db/kamonitor_demo.sql.gz | mysql -u <user> -p kamonitor

# Build the frontend
cd frontend && npm ci && npm run build && cd ..

# Start the backend (serves the frontend too)
pip install -r backend/requirements.txt
export MYSQL_CRM_HOST=127.0.0.1 MYSQL_CRM_DATABASE=kamonitor MYSQL_CRM_USERNAME=<user> MYSQL_CRM_PASSWORD=<password>
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8111
```

## License

Copyright 2026 Avalue Technology

Licensed under the [Apache License 2.0](LICENSE).
