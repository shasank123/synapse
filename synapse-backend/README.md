# Synapse Backend (POC / MVP)

The full-stack platform that the [`synapse-cli`](https://github.com/2ndbrainpartners/synapse-cli)
talks to — the piece that isn't in the CLI repo. It implements the gRPC service,
the agentic build pipeline, auth/quota, a REST API, and a web dashboard, matching
the architecture in [`docs/understanding_doc.md`](docs/understanding_doc.md).

> Turn any codebase into production-ready MCP servers. The CLI gathers local
> context; this backend runs the agents and returns the generated server.

---

## What it implements

The CLI speaks a specific gRPC contract (`proto/synapse.proto`). This backend
implements all of it:

| RPC | Type | What it does |
|-----|------|--------------|
| `DetectEndpoints` | unary | Classifies functions into MCP tool candidates (heuristic on the mock path, LLM otherwise). |
| `Build` | bidi stream | Runs the agent pipeline, streams status (`initializing → planning → task_list → generating → complete`), returns generated `mcp_server.py`. |
| `TrackEvent` | unary | `quota_check` / `quota_info` + telemetry, keyed by `sha256(api_key)`. |
| `Analyze` | bidi stream | Legacy — analyze runs locally in the CLI now, so this just acks. |

Plus a REST API (`POST /telemetry/cli`, health) and a web dashboard to sign up,
mint API keys, and view quota + generated servers.

### Architecture (per the doc)

```
 CLI ──gRPC (x-api-key)──▶  grpc service ──▶ agent pipeline (LangGraph-style)
     ──REST (Bearer)────▶  FastAPI api        search→planner→generator→validator→fix
                                  │
     Postgres (metadata) · Redis (Celery) · Qdrant (vectors) · MinIO (S3 code store)
```

### Agent pipeline

A dependency-free `StateGraph` mirrors the doc's LangGraph nodes:

```
search → planner → generator → validator ─(valid?)─▶ complete
                       ▲                    │
                       └──────── fix ◀──────┘
```

* **mock path** (default, no API key): heuristic detector + deterministic
  `FastMCP` codegen. The whole pipeline runs offline.
* **real path**: set `LLM_PROVIDER=anthropic|openai` + a key; the same nodes call
  the model, and fall back to the deterministic path if the model errors.

---

## Run it

### Option A — Docker Compose (full stack, matches the doc)

```bash
cd synapse-backend
cp .env.example .env          # (optional) add ANTHROPIC_API_KEY + set LLM_PROVIDER=anthropic
docker compose up --build
```

This starts Postgres, Redis, Qdrant, MinIO, the gRPC service (`:50051`), the REST
API + dashboard (`:8000`), and a Celery worker. The one-shot `init` service
creates tables, seeds a **dev API key** (printed in its logs), and provisions the
S3 bucket + Qdrant collection.

Grab the seeded key:

```bash
docker compose logs init | grep "syn-api-"
```

Or mint another anytime:

```bash
docker compose run --rm init python -m synapse_backend.scripts_entry new-key
```

Open the dashboard at **http://localhost:8000** (register an account, create keys,
watch quota).

### Option B — Local smoke test (no Docker, SQLite + mock LLM)

Proves the whole gRPC contract in-process:

```bash
cd synapse-backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install grpcio protobuf sqlalchemy pydantic \
    pydantic-settings python-dotenv aiosqlite qdrant-client boto3 pyjwt
DATABASE_URL=sqlite+aiosqlite:///./e2e.db DATABASE_URL_SYNC=sqlite:///./e2e.db \
LLM_PROVIDER=mock ./.venv/Scripts/python.exe scripts/e2e_smoke.py
```

Expected tail: `ALL E2E CHECKS PASSED ✅` (Detect → Build → quota, with generated
code that compiles). The S3 line failing is expected without MinIO — it fails soft.

---

## Point the CLI at this backend

The CLI reads its backend address from `config.json` (or `.synapse/config.json`).
Set it to your local services:

```json
{
  "backend_url": "http://localhost:50051",
  "backend_host": "localhost",
  "backend_port": "50051",
  "api_url": "http://localhost:8000"
}
```

Then, in a project you want to expose:

```bash
synapse init
synapse config --key <syn-api-... from the dashboard or init logs>
synapse analyze          # local: AST + embeddings
synapse build            # → talks to THIS backend → writes mcp_server.py
synapse info             # → quota from THIS backend
```

---

## Configuration

All via env (`.env`). Highlights (see `.env.example` for the full list):

| Var | Default | Notes |
|-----|---------|-------|
| `LLM_PROVIDER` | `mock` | `mock` \| `anthropic` \| `openai` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | – | required for the matching provider |
| `DATABASE_URL` / `DATABASE_URL_SYNC` | postgres | async (API) / sync (gRPC, worker) |
| `QDRANT_URL`, `REDIS_URL`, `S3_*` | compose services | |
| `DEFAULT_MAX_MCP_SERVERS` / `DEFAULT_MAX_LINES_INDEXED` | 25 / 1e6 | per-key quota |

### Adding a real LLM key later

The product runs today on the mock provider. To switch on a real model, set in
`.env`:

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

and restart the `grpc` service. No code changes.

---

## Layout

```
synapse-backend/
├── docker-compose.yml            # postgres · redis · qdrant · minio · grpc · api · worker · init
├── proto/synapse.proto           # human-readable contract (stubs reused from the CLI)
├── synapse_backend/
│   ├── config.py                 # env-driven settings
│   ├── proto/                    # generated pb2 stubs (identical to the CLI's)
│   ├── db/                       # SQLAlchemy models, engines, quota accounting
│   ├── auth/                     # API-key hashing, PBKDF2 passwords, JWT
│   ├── llm/                      # provider interface + mock/anthropic/openai + factory
│   ├── vector/                   # Qdrant + fastembed semantic index (fail-soft)
│   ├── storage/                  # MinIO/S3 archival of generated servers (fail-soft)
│   ├── agents/                   # detector + graph/state/nodes/codegen/pipeline
│   ├── grpc_service/             # servicer + server entrypoint
│   ├── api/                      # FastAPI app + routes (telemetry/auth/keys/web)
│   ├── tasks/                    # Celery app
│   └── web/                      # dashboard templates
└── scripts/
    ├── e2e_smoke.py              # in-process gRPC E2E test
    └── gen_proto.sh              # regenerate stubs (normally unnecessary)
```
