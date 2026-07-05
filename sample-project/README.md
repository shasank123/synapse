# Sample project — supply chain

A tiny "locked-in enterprise system" to test Synapse end-to-end. It has a handful
of clearly toolable functions (supplier risk, parts search, purchase orders) plus
one private helper that should be filtered out.

Test it two ways:

**A. Automated (no CLI install)** — from `synapse-backend/`:
```bash
SYNAPSE_E2E_KEY=<key from the dashboard> \
  ./.venv/Scripts/python.exe scripts/build_from_dir.py ../sample-project
```
This AST-extracts the functions, calls DetectEndpoints + Build on the running
backend, and writes `mcp_server.py` here. The server then appears on your
dashboard at http://localhost:8000/app.

**B. Real CLI** (authentic user flow) — see the backend README for pointing the
CLI's `config.json` at `localhost:50051` / `localhost:8000`, then:
```bash
cd sample-project
synapse init && synapse config --key <key> && synapse analyze && synapse build
```
