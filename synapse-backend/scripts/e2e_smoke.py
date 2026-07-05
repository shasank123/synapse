"""End-to-end smoke test: real gRPC servicer + real client, SQLite + mock LLM.

Runs the whole contract the CLI depends on, in-process:
  1. DetectEndpoints — classify sample functions into MCP tool candidates.
  2. Build           — stream status updates, receive generated server code,
                       assert it compiles.
  3. TrackEvent      — quota_info snapshot reflects the generated server.

Run:
  cd synapse-backend
  DATABASE_URL=sqlite+aiosqlite:///./e2e.db DATABASE_URL_SYNC=sqlite:///./e2e.db \
  LLM_PROVIDER=mock ./.venv/Scripts/python.exe scripts/e2e_smoke.py
"""

from __future__ import annotations

import ast
import hashlib
import sys
import time
from concurrent import futures

import grpc

sys.path.insert(0, ".")

from synapse_backend.db.database import Base, SessionLocal, sync_engine  # noqa: E402
from synapse_backend.db.models import User  # noqa: E402
from synapse_backend.auth.api_keys import create_api_key_sync  # noqa: E402
from synapse_backend.auth.passwords import hash_password  # noqa: E402
from synapse_backend.grpc_service.servicer import SynapseServicer  # noqa: E402
from synapse_backend.proto import synapse_pb2 as pb  # noqa: E402
from synapse_backend.proto import synapse_pb2_grpc as pb_grpc  # noqa: E402

PORT = 50055
ADDR = f"localhost:{PORT}"


def setup_key() -> str:
    Base.metadata.create_all(bind=sync_engine)
    session = SessionLocal()
    try:
        user = User(
            email="e2e@synapse.local",
            password_hash=hash_password("x"),
            full_name="E2E",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        _, raw = create_api_key_sync(session, user.id, name="e2e")
        return raw
    finally:
        session.close()


def start_server() -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_SynapseServiceServicer_to_server(SynapseServicer(), server)
    server.add_insecure_port(ADDR)
    server.start()
    return server


SAMPLE_FUNCTIONS = [
    pb.FunctionInfo(
        name="get_supplier_risk",
        file_path="supply_chain/risk_engine.py",
        signature="def get_supplier_risk(supplier_id: str, fiscal_year: int, region: str = None) -> dict",
        docstring="Calculate comprehensive risk score for a supplier",
        return_type="dict",
        line_number=42,
        param_names=["supplier_id", "fiscal_year", "region"],
    ),
    pb.FunctionInfo(
        name="search_parts",
        file_path="supply_chain/parts_search.py",
        signature="def search_parts(query: str, filters: dict = None) -> list",
        docstring="Search for parts across suppliers",
        return_type="list",
        line_number=10,
        param_names=["query", "filters"],
    ),
    pb.FunctionInfo(
        name="_internal_helper",
        file_path="supply_chain/util.py",
        signature="def _internal_helper(x)",
        docstring="",
        line_number=5,
        param_names=["x"],
    ),
]

BUILD_QUERY = """Create MCP tools for the following endpoints:

### Function: `get_supplier_risk`
- File: `supply_chain/risk_engine.py`
- Signature: `def get_supplier_risk(supplier_id: str, fiscal_year: int, region: str = None) -> dict`
- Conversion Type: READY
- Description: Calculate comprehensive risk score for a supplier
- Return Type: `dict`

### Function: `search_parts`
- File: `supply_chain/parts_search.py`
- Signature: `def search_parts(query: str, filters: dict = None) -> list`
- Conversion Type: READY
- Description: Search for parts across suppliers
"""


def run_client(raw_key: str) -> None:
    md = [("x-api-key", raw_key)]
    channel = grpc.insecure_channel(ADDR)
    stub = pb_grpc.SynapseServiceStub(channel)

    # ── 1. DetectEndpoints ───────────────────────────────────────────────────
    print("\n[1] DetectEndpoints")
    detect_resp = stub.DetectEndpoints(
        pb.DetectRequest(
            working_dir="/proj",
            functions=SAMPLE_FUNCTIONS,
            project_schema="supply chain system",
        ),
        metadata=md,
    )
    print(f"    error: {detect_resp.error!r}")
    for c in detect_resp.candidates:
        print(f"    - {c.name:20s} conf={c.confidence:.2f} "
              f"[{c.subcategory}] {c.human_title}")
    assert detect_resp.error == "", "detect returned an error"
    names = [c.name for c in detect_resp.candidates]
    assert "get_supplier_risk" in names and "search_parts" in names
    assert "_internal_helper" not in names, "private helper should be filtered"
    print("    OK: 2 candidates, private helper excluded")

    # ── 2. Build (streaming) ─────────────────────────────────────────────────
    print("\n[2] Build (streaming status + result)")

    def request_gen():
        yield pb.BuildMessage(
            build_request=pb.BuildRequest(
                query=BUILD_QUERY,
                project_schema="supply chain system",
                working_dir="/proj",
                output_file="supply_chain_mcp.py",
                validate=True,
                docs=True,
            )
        )

    server_code = ""
    result = None
    for msg in stub.Build(request_gen(), metadata=md):
        which = msg.WhichOneof("payload")
        if which == "status_update":
            s = msg.status_update
            print(f"    [{s.stage:12s}] {s.progress*100:5.1f}%  {s.message}")
        elif which == "build_result":
            result = msg.build_result
            server_code = result.server_code
        elif which == "error":
            raise AssertionError(f"build error: {msg.error.message}")

    assert result is not None and result.success, "build did not succeed"
    print(f"    tool_count={result.tool_count}")
    ast.parse(server_code)  # must be valid Python
    compile(server_code, "<gen>", "exec")
    assert "@mcp.tool()" in server_code
    assert "get_supplier_risk" in server_code and "search_parts" in server_code
    print("    OK: generated server compiles, 2 tools present")

    # ── 3. TrackEvent quota_info ─────────────────────────────────────────────
    print("\n[3] TrackEvent (quota_info)")
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    q = stub.TrackEvent(
        pb.TrackEventRequest(event_type="quota_info", api_key_hash=key_hash),
        metadata=md,
    )
    print(f"    servers: {q.mcp_servers_count}/{q.max_mcp_servers}  "
          f"lines: {q.lines_indexed}/{q.max_lines_indexed}  "
          f"exceeded={q.quota_exceeded}")
    assert q.mcp_servers_count == 1, "generated server should count against quota"
    print("    OK: quota reflects 1 generated server")

    channel.close()
    print("\nALL E2E CHECKS PASSED ✅")


def main() -> None:
    raw_key = setup_key()
    print(f"seeded api key: {raw_key[:16]}…")
    server = start_server()
    time.sleep(0.5)
    try:
        run_client(raw_key)
    finally:
        server.stop(0)


if __name__ == "__main__":
    main()
