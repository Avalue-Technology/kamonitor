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

The AI text is pre-generated and shipped with the demo data, so no LLM is needed to run the demo. Connect an LLM (see below) to turn on the "Regenerate" buttons and generate the summaries yourself.

## Quick start (Docker)

Requires Docker with Compose v2.

1. Download `kamonitor_demo.sql.gz` from the [Releases](../../releases) page and put it in the `db/` folder.
2. Start everything:

   ```bash
   docker compose up --build
   ```

3. Open http://localhost:8111

The first start imports the demo data into MySQL, which takes about a minute. To reset the data, run `docker compose down -v` and start again.

## Regenerating AI summaries (optional)

The "Regenerate" buttons appear when the app is connected to an OpenAI-compatible chat completions endpoint, such as a local [vLLM](https://github.com/vllm-project/vllm) server. Create a `.env` file next to `docker-compose.yml`:

```bash
# A server on the same machine as Docker: use host.docker.internal instead of localhost
LLM_API_BASE=http://host.docker.internal:8000/v1
LLM_MODEL=<the model name your server reports at /v1/models>
```

Then run `docker compose up -d` again. Regenerating writes the new text into the database; `docker compose down -v` restores the original demo data.

The prompts and the checks that validate each answer were tuned with Qwen models. Other models may need more retries or fail the checks; the page then keeps the previous text and shows the error.

The generation code is in `datagen/` (`narrate_ai*.py` for summaries, `narrate_clue_qa.py` for clue Q&A, `translate_narratives.py` for translations).

## Project layout

```
backend/    FastAPI API (read-only), also serves the built frontend
frontend/   Vue 3 + Vite + ECharts
datagen/    AI summary generation (prompts, fact lists, answer checks)
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
