"""Client-only E2E: drive an ALREADY-RUNNING backend (e.g. docker compose).

    SYNAPSE_E2E_ADDR=localhost:50051 SYNAPSE_E2E_KEY=syn-api-... \
        ./.venv/Scripts/python.exe scripts/e2e_client.py

Runs Detect → Build → TrackEvent against the real gRPC service and asserts the
generated server compiles. Unlike e2e_smoke.py it starts no server and touches
no DB directly — it exercises the deployed stack exactly like the CLI does.
"""

from __future__ import annotations

import ast
import hashlib
import os
import sys

import grpc

sys.path.insert(0, ".")

from synapse_backend.proto import synapse_pb2 as pb  # noqa: E402
from synapse_backend.proto import synapse_pb2_grpc as pb_grpc  # noqa: E402

ADDR = os.environ.get("SYNAPSE_E2E_ADDR", "localhost:50051")
KEY = os.environ.get("SYNAPSE_E2E_KEY", "")

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
]

BUILD_QUERY = """Create MCP tools for the following endpoints:

### Function: `get_supplier_risk`
- File: `supply_chain/risk_engine.py`
- Signature: `def get_supplier_risk(supplier_id: str, fiscal_year: int, region: str = None) -> dict`
- Conversion Type: READY
- Description: Calculate comprehensive risk score for a supplier

### Function: `search_parts`
- File: `supply_chain/parts_search.py`
- Signature: `def search_parts(query: str, filters: dict = None) -> list`
- Conversion Type: READY
- Description: Search for parts across suppliers
"""


def main() -> None:
    if not KEY:
        raise SystemExit("Set SYNAPSE_E2E_KEY to a valid API key")
    md = [("x-api-key", KEY)]
    channel = grpc.insecure_channel(ADDR)
    stub = pb_grpc.SynapseServiceStub(channel)

    print(f"target: {ADDR}  key: {KEY[:16]}…")

    print("\n[1] DetectEndpoints")
    dr = stub.DetectEndpoints(
        pb.DetectRequest(working_dir="/proj", functions=SAMPLE_FUNCTIONS,
                         project_schema="supply chain"),
        metadata=md,
    )
    assert dr.error == "", dr.error
    print("    candidates:", [f"{c.name}({c.confidence:.2f})" for c in dr.candidates])
    assert len(dr.candidates) == 2

    print("\n[2] Build")

    def gen():
        yield pb.BuildMessage(
            build_request=pb.BuildRequest(
                query=BUILD_QUERY, project_schema="supply chain",
                working_dir="/proj", output_file="supply_chain_mcp.py",
                validate=True, docs=True,
            )
        )

    result = None
    for msg in stub.Build(gen(), metadata=md):
        which = msg.WhichOneof("payload")
        if which == "status_update":
            s = msg.status_update
            print(f"    [{s.stage:12s}] {s.progress*100:5.1f}%  {s.message}")
        elif which == "build_result":
            result = msg.build_result
        elif which == "error":
            raise AssertionError(msg.error.message)
    assert result and result.success, "build failed"
    ast.parse(result.server_code)
    assert result.tool_count == 2
    print(f"    OK: {result.tool_count} tools, code compiles, "
          f"{len(result.server_code.splitlines())} lines")

    print("\n[3] TrackEvent quota_info")
    kh = hashlib.sha256(KEY.encode()).hexdigest()
    q = stub.TrackEvent(
        pb.TrackEventRequest(event_type="quota_info", api_key_hash=kh), metadata=md
    )
    print(f"    servers={q.mcp_servers_count}/{q.max_mcp_servers} "
          f"lines={q.lines_indexed}/{q.max_lines_indexed}")
    assert q.mcp_servers_count >= 1

    channel.close()
    print("\nDOCKER STACK E2E PASSED ✅")


if __name__ == "__main__":
    main()
