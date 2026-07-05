# Synapse — The Complete Project Guide

> A from-first-principles, end-to-end explanation of the entire Synapse platform:
> what it does, how every piece works, why each technology was chosen over the
> alternatives, and how it holds up on scalability, robustness, and security.
>
> This guide assumes **no prior knowledge**. Whenever a technical concept appears
> (gRPC, AST parsing, embeddings, containers…), it is explained in plain language
> before it is used. Read it top to bottom to build a complete mental model.

---

## Table of contents

1. [The one-paragraph mental model](#1-the-one-paragraph-mental-model)
2. [The problem Synapse solves](#2-the-problem-synapse-solves)
3. [The three people in the story](#3-the-three-people-in-the-story)
4. [Core concepts explained from scratch](#4-core-concepts-explained-from-scratch)
   - [4.1 LLMs and AI agents](#41-llms-and-ai-agents)
   - [4.2 MCP — the Model Context Protocol](#42-mcp--the-model-context-protocol)
   - [4.3 AST parsing](#43-ast-parsing)
   - [4.4 Embeddings, vectors, and semantic search](#44-embeddings-vectors-and-semantic-search)
   - [4.5 gRPC, protobuf, and streaming](#45-grpc-protobuf-and-streaming)
   - [4.6 Agentic pipelines and graphs](#46-agentic-pipelines-and-graphs)
   - [4.7 Containers, Docker, and docker-compose](#47-containers-docker-and-docker-compose)
5. [The two repositories](#5-the-two-repositories)
6. [The system at a glance](#6-the-system-at-a-glance)
7. [The end-to-end flow, step by step](#7-the-end-to-end-flow-step-by-step)
8. [Component deep-dives](#8-component-deep-dives)
9. [Why these frameworks (and not the alternatives)](#9-why-these-frameworks-and-not-the-alternatives)
10. [System-design concepts used here](#10-system-design-concepts-used-here)
11. [Scalability](#11-scalability)
12. [Robustness](#12-robustness)
13. [Security](#13-security)
14. [The data model](#14-the-data-model)
15. [Deployment and infrastructure](#15-deployment-and-infrastructure)
16. [Glossary](#16-glossary)

---

## 1. The one-paragraph mental model

**Synapse takes a codebase full of functions that only engineers can call, and
turns it into a set of "tools" that an AI assistant (like Claude) can call on
behalf of a non-technical person speaking plain English.** A developer runs a
CLI that reads their code, a backend uses AI agents to generate a small server
(an "MCP server") wrapping the useful functions, and then business users chat
with that system through Claude/Slack — "What's the risk score for supplier
SUP-45678?" — and get answers, because behind the scenes the AI called the
generated tool. The whole platform is: **a CLI + a backend that runs the agents
+ a website/dashboard + a demo assistant**.

---

## 2. The problem Synapse solves

Every company has valuable systems locked inside code:

- A supply-chain platform with 500 functions: `get_supplier_risk`, `search_parts`…
- An EHR with appointment and patient-history APIs.
- A CRM + MLS + scheduler in a real-estate brokerage.

The people who **need** those answers (a supply-chain manager, a front-desk
clerk, a recruiter) **cannot call Python functions**. So today they email an
engineer and wait days. The engineering cost of building a custom "chat over our
system" integration is **4–6 weeks per system**.

Synapse compresses that to **~1 day** and **zero changes to the original code**.
It reads the code, figures out which functions are worth exposing, and generates
a standard **MCP server** that any AI host can use. The original system is never
modified — Synapse only *reads* it and emits a separate wrapper.

> **The core promise:** *"Your system stays untouched. The AI handles the rest."*

---

## 3. The three people in the story

Keep these three roles straight — the entire product is organized around them.

| Role | Technical? | What they touch | What they get |
|------|-----------|-----------------|---------------|
| **Developer** | Yes | The CLI / Playground; runs `analyze` + `build` | A generated `mcp_server.py` |
| **End user** (business) | No | Claude / Slack / the **Assistant** chat | Plain-English answers |
| **Buyer / admin** | Mixed | The **website + dashboard** | Accounts, API keys, quota, billing |

A frequent point of confusion: **the generated code is for the developer, once.**
The end user never sees code — they just chat. The website is the account layer.

---

## 4. Core concepts explained from scratch

If you already know a concept, skip its subsection. Each one is written so a
non-engineer can follow it.

### 4.1 LLMs and AI agents

An **LLM** (Large Language Model, e.g. Claude, GPT) is a program that predicts
text. You give it words, it produces words. Modern LLMs can also **decide to
call a tool**: if you tell the model "here are some tools you can use, and here's
a JSON description of each," the model can respond with "call `get_supplier_risk`
with `supplier_id='SUP-45678'`." Your program runs that function and hands the
result back, and the model turns it into a sentence.

An **agent** is an LLM placed in a loop with tools and a goal. Instead of
answering in one shot, it can: think → call a tool → look at the result → call
another tool → … → produce a final answer. Synapse uses agents in two places:

1. To **generate** the MCP server (the "build" agents: Planner, Generator,
   Validator, Fix).
2. To **answer** end-user questions (the Assistant, which picks a tool and
   phrases the result).

### 4.2 MCP — the Model Context Protocol

**MCP** is an open standard (created by Anthropic) that defines *how an AI
assistant talks to external tools*. Think of it like USB: before USB, every
device had its own connector; after USB, everything speaks one protocol.

- An **MCP server** is a small program that exposes some **tools** (functions the
  AI can call) and describes them in a standard way (name, description, inputs).
- An **MCP host** is the AI application (Claude Desktop, Cursor, ChatGPT…) that
  connects to MCP servers and lets the model call their tools.

So when Synapse "generates an MCP server," it writes a Python file that:
- imports the customer's real functions,
- wraps each in an MCP **tool** with a typed signature and error handling,
- and can be plugged into any MCP host.

Because it's a **standard**, one generated server works with Claude, Cursor,
ChatGPT, Gemini, etc. — you don't build a separate integration per AI product.

A generated tool looks like this (simplified):

```python
from mcp.server.fastmcp import FastMCP
from supply_chain.risk_engine import get_supplier_risk

mcp = FastMCP("supply_chain_mcp")

@mcp.tool()
def get_supplier_risk_tool(supplier_id: str, region: str = "", fiscal_year: int = 2026) -> dict:
    """Calculate a comprehensive risk score for a supplier."""
    try:
        result = get_supplier_risk(supplier_id, region, fiscal_year)
        return {"success": True, "data": result, "error": None}
    except Exception as exc:
        return {"success": False, "data": None, "error": str(exc)}
```

`@mcp.tool()` is a **decorator** — it registers the function with the MCP server
so the host can discover and call it. `FastMCP` is the modern helper class from
the official `mcp` Python library that handles the protocol plumbing for you.

### 4.3 AST parsing

To wrap functions, Synapse must first *find* them and understand their shape.
Two ways to read code:

- **Text/regex** (naïve): search for the letters `def name(`. This breaks
  constantly — it misses decorators, type hints, default values, async
  functions, nested functions, multi-line signatures, and comments that look
  like code.
- **AST parsing** (correct): an **Abstract Syntax Tree** is the *structured*
  representation a Python interpreter itself builds from source. Python's
  built-in `ast` module turns text into a tree of typed nodes.

Example. This source:

```python
def get_supplier_risk(supplier_id: str, region: str = "") -> dict:
    """Calculate risk."""
    ...
```

parsed by `ast.parse(...)` becomes (conceptually):

```
FunctionDef(
  name = "get_supplier_risk",
  args = [ arg(supplier_id, annotation=str),
           arg(region, annotation=str, default="") ],
  returns = dict,
  docstring = "Calculate risk.",
  lineno = 1,
)
```

Now you have **exact** structured facts: the name, each parameter with its type
and default, the return type, the docstring, the line number. Synapse walks this
tree (`for node in tree.body: if isinstance(node, ast.FunctionDef)`) to extract
every function precisely. This is why the doc says *"AST parsing, not surface
scanning."* You can see it in `scripts/build_from_dir.py` and
`api/routes_playground.py` (`_extract_functions`), which use `ast` to pull
functions out of real code.

`ast.unparse(node)` does the reverse — turns a node back into source text — which
Synapse uses to reconstruct a clean signature string.

### 4.4 Embeddings, vectors, and semantic search

When a user asks "find at-risk suppliers in Europe," Synapse must find the
*relevant* functions even if the words don't match exactly (the function might be
called `get_supplier_risk`, not `find_at_risk`). This is **semantic search**, and
it works with **embeddings**.

- An **embedding** is a list of numbers (a **vector**, e.g. 384 numbers) that
  represents the *meaning* of a piece of text. A model is trained so that texts
  with similar meaning get vectors that are close together in space.
- "supplier risk" and "at-risk vendors" produce **nearby** vectors; "supplier
  risk" and "user login" produce **far-apart** vectors.
- To search, you embed the query, then find the stored function-vectors that are
  **closest** (by cosine similarity). Those are your most relevant functions.

A **vector database** (Synapse uses **Qdrant**) stores these vectors and answers
"give me the N closest vectors to this one" very fast, even over millions of
items. Synapse embeds each function's name + signature + docstring, stores the
vectors namespaced per project, and searches them when there are more candidate
functions than fit in the AI's context.

The embedding model here is **fastembed** with `BAAI/bge-small-en-v1.5`, which
runs **locally on CPU** and produces 384-dimensional vectors — no external API,
no key, no data leaving the machine.

### 4.5 gRPC, protobuf, and streaming

The CLI (on the developer's laptop) and the backend (in the cloud) need to talk.
There are a few ways to do that:

- **REST** (the usual web API): the client sends an HTTP request, the server
  sends one response. Simple, but **one-shot** — awkward for long, interactive
  workflows where the server wants to send many progress updates and occasionally
  ask the client to do something.
- **WebSockets**: two-way, but untyped and low-level — you invent your own message
  format and validation.
- **gRPC** (what Synapse uses for the build workflow): a high-performance RPC
  framework from Google.

**RPC** = *Remote Procedure Call*: calling a function on another machine as if it
were local. With gRPC you define your service's functions and message shapes in a
`.proto` file, and a code generator produces typed client and server "stubs" in
your language.

**Protobuf** (Protocol Buffers) is the *format* gRPC uses to serialize messages:
a compact **binary** encoding (much smaller and faster than JSON) with a strict
**schema**. You describe messages once:

```proto
message DetectedEndpoint {
  string name = 1;
  float  confidence = 3;
  string human_title = 4;
  // ...
}
```

and both sides agree on exactly those fields and types. The numbers (`= 1`) are
field tags used in the binary wire format.

**Why gRPC here specifically?** The `build` operation is a long, chatty,
**bidirectional** conversation:

- The server streams **status updates** ("planning… 40%… generating…") so the
  CLI can show a live progress UI.
- The server can send **tool requests** back down to the CLI ("read this file for
  me") and get responses — because the *code lives on the developer's machine*,
  not the server.

gRPC's **bidirectional streaming** models this natively: one long-lived
connection, messages flowing both ways, all strongly typed. Doing this over plain
REST would mean polling or many separate requests; over raw WebSockets you'd
rebuild typing and codegen yourself.

The Synapse contract has four RPCs (see `proto/synapse.proto`):

| RPC | Shape | Purpose |
|-----|-------|---------|
| `DetectEndpoints` | unary (1 req → 1 resp) | classify functions into tool candidates |
| `Build` | bidi stream | run the agent pipeline, stream progress, return code |
| `TrackEvent` | unary | quota checks + telemetry |
| `Analyze` | bidi stream | legacy (analysis now runs locally in the CLI) |

A subtle but important detail: **the backend reuses the exact compiled protobuf
stubs from the CLI** (`synapse_pb2.py`, `synapse_pb2_grpc.py`). Because both sides
share the identical schema descriptor, their binary wire formats are guaranteed
to match — no drift, no "works on my machine."

### 4.6 Agentic pipelines and graphs

Generating a correct server isn't a single AI call — it's a **pipeline** of steps
where later steps depend on earlier ones, with loops for self-correction. This is
naturally a **graph**: nodes are steps, edges are "what runs next," and some edges
are **conditional** ("if the code is invalid, go fix it; else finish").

Synapse's build graph:

```
search → planner → generator → validator ──(valid?)──▶ complete
                       ▲                    │
                       └──────── fix ◀──────┘ (if invalid & attempts remain)
```

- **search**: gather the relevant functions (from the query + provided context).
- **planner**: decide which functions become which tools (a to-do list).
- **generator**: write the server code.
- **validator**: does the code actually parse/compile? count the tools.
- **fix**: if invalid, repair and loop back to validate (bounded retries).
- **complete**: finalize counts, docs, and result.

The industry tool for this is **LangGraph**. Synapse implements the *same shape*
with a tiny **dependency-free** graph runner (`agents/graph.py`) — see
[§9](#9-why-these-frameworks-and-not-the-alternatives) for why.

### 4.7 Containers, Docker, and docker-compose

A **container** is a lightweight, isolated box that packages an app with
everything it needs to run (Python version, libraries, OS bits) so it runs the
same on any machine. **Docker** builds and runs containers from a recipe called a
**Dockerfile**.

A real system is many services (a database, a cache, the app…). **docker-compose**
is a single YAML file describing all of them and how they connect, so
`docker compose up` starts the *whole* system with one command. Synapse's
`docker-compose.yml` runs 8 services (database, cache, vector DB, object storage,
the gRPC server, the web API, a background worker, and a one-time initializer)
wired together on a private network.

---

## 5. The two repositories

Synapse is split across two codebases:

| Repo | What it is | In this repo? |
|------|-----------|---------------|
| `2ndbrainpartners/synapse-cli` | The **client** the developer installs (`pip install synapse-cli`). Reads code locally, calls the backend. | Cloned for reference; **git-ignored** (it's a separate upstream). |
| `shasank123/synapse` (**this repo**) | The **backend + platform**: gRPC service, agent pipeline, REST API, web dashboard, assistant, infra. | Yes — `synapse-backend/`. |

**Why split?** The CLI must run on the developer's machine (that's where the code
is), while the heavy AI work, database, and account management run centrally. The
CLI is thin (gather context, execute file tools, show UI); the backend is where
the intelligence and state live. This is a classic **thin-client / smart-server**
split.

Key insight that shaped the whole build: the CLI already existed and already
*expected* a backend at `grpc.synaps3.ai`. Our job was to **build the backend the
CLI was already talking to** — so we reverse-engineered the exact contract from
the CLI's compiled protobuf stubs and implemented a server that satisfies it.

---

## 6. The system at a glance

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              DEVELOPER'S MACHINE                            │
│   synapse-cli  ──AST parse local code, gather context──┐                    │
└─────────────────────────────────┬──────────────────────┼───────────────────┘
                 gRPC :50051 (x-api-key)         REST :8000 (Bearer key)
                                  │                       │
┌─────────────────────────────────▼───────────────────────▼──────────────────┐
│                         SYNAPSE BACKEND (this repo)                          │
│                                                                             │
│  grpc service ──▶ agent pipeline (search→plan→gen→validate→fix)             │
│     │                    │                                                   │
│     │                    ├─▶ LLM provider (mock | anthropic | openai)        │
│     │                    ├─▶ Qdrant  (semantic search over functions)        │
│     │                    └─▶ MinIO/S3 (archive generated server code)        │
│     │                                                                        │
│  FastAPI api  ──▶ marketing site · dashboard · Playground · Assistant        │
│     │             └─▶ auth (API keys, JWT), quota, telemetry                 │
│     │                                                                        │
│  Celery worker  ──▶ background jobs (Redis broker)                           │
│                                                                             │
│  Postgres (accounts/keys/servers/quota/leads) · Redis (cache/broker)         │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                       (end users, separately)
                                  ▼
                 Claude Desktop / Cursor / Slack  ──▶ run the generated MCP server
```

Two independent "planes":

- **Build plane** (developer): CLI → gRPC → agents → generated server.
- **Use plane** (end user): AI host → generated MCP server → answers. Our
  **Assistant** page simulates this plane in the browser for demos.

---

## 7. The end-to-end flow, step by step

Here is the entire journey, in order, with what happens and where.

### Step 0 — The developer signs up (website)
On `http://localhost:8000` they register an account. The password is hashed with
**PBKDF2** and stored; a **JWT** session cookie is set. On the dashboard they
click **Generate API key** — a random key `syn-api-…` is created. We store only
its **SHA-256 hash** and a short prefix; the raw key is shown **once**.

### Step 1 — `synapse init` (CLI, local)
Creates a `.synapse/` config folder and stores the API key (encrypted with
**Fernet**, machine-specific). The key is how the backend knows *who* is calling.

### Step 2 — `synapse analyze` (CLI, local — no backend)
This runs **entirely on the developer's machine**:
- **AST-parse** every Python file → extract functions, classes, signatures.
- Write `.synapse/project_schema.txt` and `statistics.json`.
- **Embed + index** code chunks into a local Qdrant for semantic search.

Only a **telemetry** ping (event type + a *hashed* working directory + a line
count) is sent to the backend's REST `/telemetry/cli`, which updates the key's
"lines indexed" quota. **The source code itself never leaves the machine.**

### Step 3 — `synapse build` (CLI ↔ backend)
This is the heart of the system.

1. **Local scan.** The CLI AST-extracts *all* functions from the project.
2. **DetectEndpoints (gRPC unary).** The CLI sends the function metadata (not the
   whole code) to the backend. The backend **classifies** each function into an
   MCP tool candidate — assigning a confidence, a human title/description, a
   category, and whether it's directly callable or needs a wrapper. Private
   helpers (leading `_`) are filtered out. On the **mock** provider this is a
   heuristic (`agents/detector.py`); with a real LLM it's a classification prompt.
   Results are cached per-file so unchanged files aren't re-sent.
3. **Selection.** The CLI shows the detected tools; the developer ticks which to
   expose. The CLI builds a **context bundle** (the selected functions + code
   context) and a query.
4. **Build (gRPC bidi stream).** The CLI opens a streaming call and sends a
   `build_request` (query + project schema + context bundle). Then:
   - The backend runs the **agent graph**. As each node runs, it emits a
     `status_update` message (stage, message, progress) — the CLI renders a live
     progress UI from these.
   - The **planner** turns the functions into a to-do list of tools. The
     **generator** writes the server code. The **validator** `ast.parse` +
     `compile`s it and counts `@mcp.tool()`s. If it doesn't compile, the **fix**
     node repairs it (bounded retries) — on the mock path it simply regenerates
     from the deterministic template, which is always valid.
   - The backend sends a final `build_result` containing the full generated
     `server_code`, tool count, docs, and to-do list.
5. **Accounting.** On success the backend records an `MCPServer` row, increments
   the key's "servers built" quota, and **archives the code to MinIO/S3** — all
   fail-soft (if S3 is down, the build still succeeds; the code is also returned
   inline).
6. **Write.** The CLI writes the returned `server_code` to `mcp_server.py` and
   prints an MCP host config snippet.

> The backend is effectively **server-streaming** for the POC: the CLI provides
> all context up front (schema + bundle), so the server rarely needs to call back
> for files. The bidirectional *capability* remains (the `tool_request` channel
> exists), which is why gRPC is the right transport.

### Step 4 — Connect to an MCP host (developer, one-time)
The dashboard's **"Connect to an MCP host"** card gives a ready-to-paste config:

```json
{ "mcpServers": { "mcp_server": { "command": "python", "args": ["/abs/path/mcp_server.py"] } } }
```

Paste into Claude Desktop / Cursor config, restart, and the tools are live.

### Step 5 — The end user asks questions (Assistant / Claude)
Now the non-technical user just chats. In our **Assistant** demo
(`/app/assistant`) or in real Claude:
- User: *"What's the risk score for supplier SUP-45678?"*
- The host/agent maps this to `get_supplier_risk(supplier_id="SUP-45678")`, runs
  it, and phrases the result: *"Supplier SUP-45678 has a risk score of 72/100…"*
- The Assistant shows the **trace** (`Assistant → MCP Server → get_supplier_risk(...)`)
  so you can demo both the answer and the mechanism.

That's the full loop: **code → generated tools → natural-language answers.**

---

## 8. Component deep-dives

File paths below are under `synapse-backend/synapse_backend/` unless noted.

### 8.1 The gRPC service (`grpc_service/`)
- `server.py` — starts a threaded gRPC server on `:50051` with the same
  keepalive/message-size options the CLI expects.
- `servicer.py` — implements the four RPCs:
  - **Auth**: `Build`/`DetectEndpoints` read the raw key from the `x-api-key`
    metadata header and resolve it to an `ApiKey` row by hashing it;
    `TrackEvent` receives the already-hashed key. Invalid → clean error.
  - **Build orchestration**: the pipeline runs in a **worker thread** and pushes
    status/result items onto a thread-safe **queue**; the RPC generator drains the
    queue and yields protobuf messages. This lets a synchronous pipeline stream
    progress through a gRPC generator cleanly.
  - **Finalize**: on success, archive to S3 + record the server + quota (wrapped
    in try/except so accounting can never fail a successful build).

### 8.2 The agent pipeline (`agents/`)
- `graph.py` — a minimal `StateGraph` (nodes, edges, conditional edges, a run
  loop with a max-steps guard). Mirrors LangGraph's shape with zero dependencies.
- `state.py` — `BuildState`, the dataclass carried between nodes (inputs,
  working data, validation status, callbacks for `emit`/`call_tool`).
- `nodes.py` — the five nodes (`search`, `planner`, `generator`, `validator`,
  `fix`, `complete`), each `(state) -> state`. Mock path uses heuristics; real
  path uses prompts, with automatic fallback to the deterministic path on any LLM
  error.
- `detector.py` — `DetectEndpoints` logic: heuristic scoring (verb category,
  docstring, params, return type; filters privates/dunders/tests) or LLM
  classification.
- `codegen.py` — the deterministic code generator. Notable tricks: it emits
  `from __future__ import annotations` so exotic parameter/return types never
  crash on import, and it reuses each function's parameter list **verbatim** and
  forwards arguments by keyword.
- `parsing.py` — pure, dependency-free helpers to extract functions from the
  CLI's query blocks / context bundle (kept separate so they're easily testable).
- `pipeline.py` — assembles the graph and exposes `run_build(...)`, returning a
  `BuildResult`-shaped dict and streaming status via an `emit` callback.
- `prompts.py` — the LLM prompt templates (used only on the real-LLM path).

### 8.3 The LLM provider abstraction (`llm/`)
- `base.py` — `LLMProvider` interface with `complete()` and `complete_json()`
  (which appends a JSON-only instruction and repairs/extracts JSON from the
  reply).
- `mock_provider.py` — a safe offline stub. The *intelligence* on the mock path
  lives in the domain heuristics (detector, codegen, assistant), selected when
  `LLM_PROVIDER=mock`.
- `anthropic_provider.py`, `openai_provider.py` — real providers.
- `factory.py` — `get_llm()` returns the configured provider (cached) and
  **degrades to mock** if a key/import is missing; `is_mock()` tells domain code
  to use heuristics.

**Why an abstraction?** So the entire product can be built and demoed **without
any API key or cost**, and switching to a real model is a one-line env change
with no code edits. It also makes the system testable and provider-agnostic.

### 8.4 Vector store (`vector/qdrant_store.py`)
Embeds functions with fastembed (384-dim) and upserts them to Qdrant, namespaced
per project (a hash of the working directory). `search()` embeds a query and
returns the closest functions. **Everything fails soft**: if Qdrant or the
embedder is unavailable, callers fall back to lexical handling.

### 8.5 Object storage (`storage/s3.py`)
Stores each generated `mcp_server.py` in MinIO (S3-compatible) under
`<api_key_id>/<server_id>.py`, keeping the `s3://` URI on the `MCPServer` row.
Also fail-soft — archival never blocks a build.

### 8.6 Database + quota (`db/`)
- `database.py` — **both** an async engine (for FastAPI) and a sync engine (for
  gRPC/Celery) over the same Postgres.
- `models.py` — `User`, `ApiKey`, `MCPServer`, `Event`, `Lead`.
- `quota.py` — snapshots and usage accounting (servers built, lines indexed),
  keyed by `sha256(api_key)`.

### 8.7 REST API + web (`api/`, `web/`)
- `app.py` — the FastAPI app; mounts routers, static files, health probes,
  creates tables on startup. Built-in Swagger `/docs` is disabled so the
  marketing **Docs** page can own `/docs`.
- `routes_telemetry.py` — `POST /telemetry/cli` (Bearer key) records events and
  adds analyze line-deltas to quota.
- `routes_auth.py` — register/login/logout (cookie JWT), PBKDF2 passwords.
- `routes_keys.py` — create/list/revoke API keys.
- `routes_web.py` — public marketing pages (landing, pricing, usecases, docs,
  legal), the demo-lead endpoint, and the authed `/app` dashboard.
- `routes_playground.py` — `/app/playground` + `POST /api/playground/build`:
  runs the **same** detect+build pipeline **in-process** (no gRPC round-trip) so
  the whole thing works from the browser.
- `routes_assistant.py` — `/app/assistant` + `POST /api/assistant/chat`: the
  end-user chat.
- `web/static/synapse.css` — the design system (light/dark, responsive).
- `web/templates/*.html` — Jinja2 pages.

### 8.8 The Assistant (`demo/`)
- `tools.py` — a *deployed* supply-chain MCP server represented as executable
  demo tools (risk, parts, delivery, availability, purchase orders), each with a
  JSON schema. Scores are deterministic (SUP-45678 → 72, matching the doc).
- `agent.py` — natural-language → tool routing (keyword intent + entity
  extraction) → execute → templated natural-language answer, plus the
  `Assistant → MCP Server → tool(args)` trace. With a real LLM it uses
  tool-routing + phrasing instead.

**Why does the Assistant call functions directly instead of speaking real MCP?**
For a browser demo, importing and calling the tool functions is behaviorally
identical to what an MCP host does, without the overhead of spawning the server
as a subprocess and negotiating the protocol. In production the end user's *real*
host (Claude Desktop) speaks MCP to the generated server.

### 8.9 Background jobs (`tasks/celery_app.py`)
A Celery app on a Redis broker with a background "index functions" task and a
health `ping`. The synchronous gRPC path returns results inline; Celery is where
heavier async work (index warming, analytics rollups) would live.

---

## 9. Why these frameworks (and not the alternatives)

Each choice, with the trade-off that decided it.

| Area | Chosen | Alternatives | Why chosen |
|------|--------|--------------|-----------|
| Build transport | **gRPC** | REST, WebSockets | Long, chatty, **bidirectional** workflow with typed messages + streaming progress; codegen keeps client/server in lockstep. REST is one-shot; WebSockets are untyped. |
| Wire format | **Protobuf** | JSON | Compact **binary**, strict schema, generated types. JSON is larger, untyped, and drifts. |
| Web API | **FastAPI** | Flask, Django | Async (needed for many concurrent connections), automatic validation via type hints, fast, minimal boilerplate. Django is heavy for an API; Flask lacks async/validation out of the box. |
| Relational DB | **PostgreSQL** | MySQL, MongoDB | ACID correctness for accounts/quota/billing, rich types + JSON, the de-facto SaaS default. Mongo (document) is a poor fit for relational account data. |
| Vector DB | **Qdrant** | Pinecone, pgvector, FAISS | Open-source, **self-hostable** (no vendor lock-in/cost), fast, supports metadata filtering (namespaces). Pinecone is hosted-only; FAISS is a library, not a service; pgvector is fine but a dedicated engine scales better for pure vector workloads. |
| Embeddings | **fastembed (bge-small)** | OpenAI embeddings, sentence-transformers | Runs **locally on CPU**, no API key, no per-call cost, keeps code private. OpenAI embeddings cost money and send text out. sentence-transformers pulls in heavy torch. |
| Object storage | **MinIO** | AWS S3 | S3-**compatible** API but runs locally in Docker for the POC; swap the endpoint for real S3 in prod with zero code change. |
| Queue/broker | **Celery + Redis** | RQ, Kafka, Dramatiq | Mature, Python-native, simple for task queues; Redis doubles as cache + broker. Kafka is an event-streaming platform — overkill here. |
| Agent graph | **custom StateGraph** | LangGraph | The doc calls for LangGraph's *shape*; a ~60-line dependency-free runner gives the exact node/edge/conditional structure with **no external dependency risk**, full control, and trivial testing. Swappable for real LangGraph later (same node functions). |
| Frontend | **server-rendered Jinja** | React/Next SPA | Ships inside the existing FastAPI app with **no separate build pipeline**, cohesive with the backend, good for a marketing site (SEO, fast first paint). A SPA adds Node tooling and a second deploy for little POC benefit. |
| Password hash | **PBKDF2 (stdlib)** | bcrypt, argon2 | Zero extra dependency for the POC; salted + 200k iterations. Production should prefer argon2/bcrypt (noted in the security section). |
| Auth (web) | **JWT cookie** | server sessions | Stateless — no session store needed; scales horizontally. |
| LLM access | **provider abstraction + mock default** | hard-wire one SDK | Build/demo with **no key or cost**, switch providers via env, testable, and graceful fallback if a provider fails. |

---

## 10. System-design concepts used here

- **Thin client / smart server.** The CLI does only what *must* be local (read
  code, execute file tools, render UI); all intelligence + state is central. Keeps
  the client simple and the server independently upgradable.
- **Contract-first with shared codegen.** The `.proto` is the single source of
  truth; both sides use identical generated stubs → zero schema drift.
- **Stateless services.** The gRPC service and the API hold no per-user state in
  memory — everything is in Postgres/Redis. Any request can hit any instance,
  which is what makes horizontal scaling possible.
- **Streaming with a producer/consumer queue.** A background worker thread
  produces status events; the RPC generator consumes them — decoupling the
  (synchronous) pipeline from the (streaming) transport.
- **Graph-structured control flow.** Explicit nodes + conditional edges make the
  build's loops and branches (validate→fix) auditable and easy to change.
- **Strategy pattern for the LLM.** One interface, many implementations
  (mock/anthropic/openai), chosen at runtime.
- **Fail-soft side effects.** Non-critical work (S3, Qdrant, telemetry,
  accounting) is wrapped so it can fail without breaking the core operation.
- **Graceful degradation / fallback chains.** LLM → heuristic; LLM-codegen →
  deterministic codegen; Qdrant → lexical. The system always produces *an* answer.
- **Idempotency.** `init`/seed and table creation are safe to run repeatedly.

---

## 11. Scalability

How each layer grows, and where the limits are.

- **Stateless horizontal scaling.** Because the gRPC service and the API keep no
  in-memory session state, you can run **N replicas** of each behind a load
  balancer and add more under load. gRPC works with L7 load balancers (e.g.
  Envoy) that understand HTTP/2 streams.
- **Database.** Postgres scales vertically first (bigger box), then with
  **connection pooling** (already `pool_pre_ping`ed), **read replicas** for
  read-heavy dashboard/quota queries, and partitioning of the high-volume
  `events` table by time if needed.
- **Vector search.** Qdrant scales horizontally via **sharding/replication** and
  is namespaced per project, so one tenant's index never scans another's.
- **Background work.** Celery **workers scale out** independently — add workers to
  absorb spikes in indexing/analytics without touching the request path. Redis can
  be clustered.
- **Object storage.** MinIO/S3 is effectively unbounded and offloads large blobs
  (generated code) out of the database.
- **Quotas as a scaling control.** Per-key limits (`max_mcp_servers`,
  `max_lines_indexed`) bound per-tenant resource use and protect shared services.
- **Streaming reduces round-trips.** One long-lived gRPC connection carries the
  whole build instead of dozens of polling requests.

**Primary bottleneck:** **LLM latency/cost** on the real-model path. Mitigations:
the detect cache (don't re-classify unchanged files), the deterministic mock path,
and moving long jobs to Celery. **Embedding** and **DB writes** are secondary
bottlenecks addressed by batching and pooling.

---

## 12. Robustness

Why the system keeps working when things go wrong.

- **Fail-soft everywhere.** Qdrant down? search returns lexical results. MinIO
  down? build still succeeds, code returned inline. Telemetry down? the CLI fails
  open. Accounting error? wrapped so it never fails a successful build.
- **Fallback chains.** A missing/erroring LLM key degrades to the mock provider;
  a bad LLM generation falls back to the deterministic generator, which is
  **guaranteed to compile**.
- **Self-correcting build.** The validator `ast.parse` + `compile`s generated
  code and, on failure, routes to a **fix** node with bounded retries — the system
  doesn't emit broken servers.
- **Health checks + restart policies.** docker-compose defines healthchecks
  (Postgres/Redis/MinIO) and dependency ordering; services `depends_on` healthy
  infra. A crashed service restarts.
- **Idempotent setup.** Re-running init/seed/table-creation is safe.
- **Input guards.** The Playground/Assistant handle syntax errors, empty input,
  and unauthenticated calls with clean messages, not stack traces.
- **Verified end-to-end.** Two independent test harnesses exist: an in-process
  gRPC smoke test over SQLite (`scripts/e2e_smoke.py`) and a client that drives
  the live Docker stack (`scripts/e2e_client.py`), plus a real-codebase build
  (`scripts/build_from_dir.py`).

---

## 13. Security

What's protected, how, and what a production hardening pass should add.

**Implemented:**
- **API keys never stored raw.** Only `sha256(key)` + a short prefix are kept;
  the raw key is shown once. The CLI sends the raw key as `x-api-key` gRPC
  metadata (or a pre-hashed value for telemetry), and the backend resolves it by
  hashing.
- **Passwords** hashed with salted **PBKDF2** (200k iterations); never stored or
  logged in plaintext.
- **Sessions** are stateless **JWTs** in httponly, samesite cookies.
- **Source-code privacy.** Analysis (AST + embeddings) runs **locally in the
  CLI**; only function *metadata* and the *selected* context bundle are sent —
  not the whole repository. Telemetry sends a **hash** of the working directory,
  not its path.
- **Transport.** The CLI uses a **secure (TLS) channel** automatically for
  cloud/HTTPS backends; local dev uses an insecure channel.
- **Tenant isolation.** Data is scoped per user/key; Qdrant is namespaced per
  project; quotas bound each tenant's footprint.
- **Secrets via environment** (`.env`, git-ignored), not committed. The personal
  push token lives only in `.git/config`, never in a tracked file.

**Known POC gaps to close for production (called out honestly):**
- **Rate limiting / WAF** on the API and gRPC endpoints (prevent brute-force and
  abuse) — not yet added.
- **Stronger password hashing** (argon2id/bcrypt) over PBKDF2.
- **Executing user-provided code.** The Playground/Assistant run functions
  server-side; for arbitrary tenant code this needs a **sandbox** (isolated
  process, seccomp/gVisor, resource limits). The demo restricts this to trusted
  sample/demo code.
- **Generated-code trust.** The doc envisions a **dual-signature** scheme
  (developer signs the code hash; the platform signs after scanning) so an MCP
  host can verify a server is authentic and vetted before executing it — a strong
  future addition.
- **Secret management** should move from `.env` to a managed vault (GCP Secret
  Manager / AWS Secrets Manager) with rotation.
- **JWT secret + DB/MinIO credentials** are dev defaults in compose — replace for
  any shared/hosted deployment.
- **Audit logging, RBAC, SSO, SOC2/GDPR** controls (multi-tenant enterprise
  features) are roadmap items in the understanding doc.

---

## 14. The data model

Postgres tables (`db/models.py`) and their relationships:

```
User ──1:N──▶ ApiKey ──1:N──▶ MCPServer
                 │
                 └──1:N──▶ Event
Lead   (standalone — marketing/demo requests)
```

| Table | Key columns | Purpose |
|-------|------------|---------|
| `users` | id, email, password_hash | dashboard accounts |
| `api_keys` | id, user_id, key_prefix, **key_hash**, servers_generated, lines_indexed, max_* | CLI auth **and** quota counters/limits, in one row for fast checks |
| `mcp_servers` | id, api_key_id, name, tool_count, line_count, storage_uri | a record of each generated server (with its S3 URI) |
| `events` | id, api_key_id, event_type, working_dir_hash, counts | telemetry for quota + analytics |
| `leads` | id, name, email, company, message | "Book a demo" submissions |

Quota lives **on the `api_keys` row** (not a separate table) so the CLI's quota
questions are answered by a single indexed read on `key_hash`.

---

## 15. Deployment and infrastructure

`docker compose up --build` starts everything:

| Service | Image | Port | Role |
|---------|-------|------|------|
| `postgres` | postgres:16 | 5432 | metadata (accounts, keys, servers, quota, leads) |
| `redis` | redis:7 | 6379 | cache + Celery broker |
| `qdrant` | qdrant/qdrant | 6333 | vector search |
| `minio` | minio/minio | 9000/9001 | S3-compatible object storage |
| `init` | app image | — | one-shot: create tables, seed a dev key, ensure bucket + collection |
| `grpc` | app image | 50051 | `SynapseService` (Build/Detect/TrackEvent/Analyze) |
| `api` | app image | 8000 | REST + marketing site + dashboard + Playground + Assistant |
| `worker` | app image | — | Celery background jobs |

All four app services share **one image** (`synapse-backend:local`), built once
by `grpc` and reused — this avoids a Docker build race where four services
building the same context in parallel collide.

**Config** is entirely env-driven (`config.py` + `.env`). The most important
switch is `LLM_PROVIDER` (`mock` by default; set to `anthropic`/`openai` + a key
for real generation — no code change).

**Ports recap:** the **frontend and REST API are the same app on `:8000`**; the
gRPC backend is separate on `:50051`.

---

## 16. Glossary

- **AST (Abstract Syntax Tree):** the structured, typed tree form of source code
  that a parser produces; lets you read code precisely instead of via text search.
- **Agent:** an LLM in a loop with tools and a goal.
- **Bidirectional streaming:** a single connection where both sides send many
  messages over time (gRPC feature).
- **Container / Docker:** an isolated, portable box packaging an app + its deps.
- **Embedding:** a numeric vector representing the meaning of text; near vectors =
  similar meaning.
- **Fail-soft:** designed so a non-critical failure degrades gracefully instead of
  crashing the whole operation.
- **gRPC:** a high-performance, schema-typed RPC framework with streaming.
- **JWT:** a signed token proving who a user is, stored in a cookie; stateless.
- **LLM:** a model that predicts text and can call tools.
- **MCP (Model Context Protocol):** the open standard for how AI hosts talk to
  tool servers.
- **MCP host / server:** the AI app (host) that connects to tool programs
  (servers).
- **Protobuf:** compact binary, schema-typed message format used by gRPC.
- **Quota:** per-key limits on usage (servers built, lines indexed).
- **RPC (Remote Procedure Call):** calling a function on another machine as if
  local.
- **Semantic search:** finding results by *meaning* (via embeddings) rather than
  exact keywords.
- **Stateless service:** holds no per-request state in memory, enabling horizontal
  scaling.
- **Vector database:** a store optimized for "find the nearest vectors" queries
  (Synapse uses Qdrant).

---

*This guide describes the Synapse platform as implemented in this repository. For
the product-level overview and use cases, see
[`synapse-backend/docs/understanding_doc.md`](../synapse-backend/docs/understanding_doc.md).
For run instructions, see [`synapse-backend/README.md`](../synapse-backend/README.md).*
