# Synapse

**Agentic MCP Server Generator** — a full-stack platform that turns any codebase
into production-ready [MCP](https://modelcontextprotocol.io) servers so AI
assistants can call its functions as tools.

This repo contains the **backend/platform** (the part that runs the AI agents),
built to serve the existing [`synapse-cli`](https://github.com/2ndbrainpartners/synapse-cli)
client over gRPC.

## Repos & how they fit

| Piece | Where | Role |
|-------|-------|------|
| **CLI** | `2ndbrainpartners/synapse-cli` (cloned separately, git-ignored here) | Analyzes a codebase locally, gathers context, calls the backend. |
| **Backend / platform** | [`synapse-backend/`](synapse-backend/) *(this repo)* | gRPC service + agent pipeline + REST API + web dashboard + infra. |

The CLI clone is intentionally **not** committed here (it's a separate upstream).
Clone it next to this repo if you want to run the full loop:

```bash
git clone https://github.com/2ndbrainpartners/synapse-cli.git
```

## Quick start

```bash
cd synapse-backend
docker compose up --build          # full stack: postgres/redis/qdrant/minio/grpc/api/worker
# dashboard → http://localhost:8000 ,  gRPC → localhost:50051
```

Then point the CLI at `localhost` and run `synapse init / analyze / build`.
See [`synapse-backend/README.md`](synapse-backend/README.md) for the full guide,
including a no-Docker SQLite smoke test and how to plug in a real LLM key.

## Status

MVP POC. Runs end-to-end on a **mock LLM provider** by default (no API key
needed); set `LLM_PROVIDER=anthropic|openai` + a key to use a real model. See
[`synapse-backend/docs/understanding_doc.md`](synapse-backend/docs/understanding_doc.md)
for the product overview this was built from.
