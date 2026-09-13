# AgentOS Dashboard

Vue 3 + Vite + TypeScript + Element Plus + ECharts observability dashboard for AgentOS.

## Pages

| Route | Purpose |
| --- | --- |
| `/dashboard` | Runtime overview, trends, outcomes, quota |
| `/agents` | Agent roster and execution health |
| `/runs` | Filterable run history |
| `/runs/:id` | Execution trace timeline |
| `/tools` | Tool inventory and call analytics |
| `/evaluation` | Evaluation summary and dataset runs |
| `/usage` | Runs / token quota usage |

Run Detail only renders request, tool metadata, truncated tool payloads and final answer. System prompts, API keys and sensitive memory are filtered.

## Development

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

Open <http://localhost:5173>.

Demo mode is enabled by default in `.env.example` and Docker Compose. It serves mock Runs, Agents, Traces and Evaluation data without a real LLM.

```text
VITE_DEMO_MODE=false
VITE_API_BASE_URL=/api/v1
VITE_BACKEND_URL=http://127.0.0.1:8000
```

## Build and test

```powershell
npm run build
npm test
```

## Docker

```powershell
docker compose up --build
```

Open <http://localhost:5173>. Nginx serves the SPA and proxies `/api` and `/health` to the `agentos` service.
