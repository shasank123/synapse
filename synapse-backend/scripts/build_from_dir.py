"""Build an MCP server from a REAL codebase directory — CLI-style, automated.

Mimics what `synapse build` does: AST-extract functions from a directory, call
DetectEndpoints to classify them, then Build to generate the server. Lets you
test the whole backend against an actual codebase without installing the CLI.

    SYNAPSE_E2E_KEY=<dashboard key> SYNAPSE_E2E_ADDR=localhost:50051 \
        ./.venv/Scripts/python.exe scripts/build_from_dir.py ../sample-project

Writes <dir>/mcp_server.py and prints a summary; the server appears on the
owning user's dashboard.
"""

from __future__ import annotations

import ast
import os
import sys

import grpc

sys.path.insert(0, ".")

from synapse_backend.proto import synapse_pb2 as pb  # noqa: E402
from synapse_backend.proto import synapse_pb2_grpc as pb_grpc  # noqa: E402

ADDR = os.environ.get("SYNAPSE_E2E_ADDR", "localhost:50051")
KEY = os.environ.get("SYNAPSE_E2E_KEY", "")


def extract_functions(root: str) -> list[pb.FunctionInfo]:
    """Walk .py files and extract top-level functions as FunctionInfo protos."""
    funcs: list[pb.FunctionInfo] = []
    for dirpath, _dirs, files in os.walk(root):
        if any(part in dirpath for part in (".venv", "__pycache__", ".git")):
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            abspath = os.path.join(dirpath, fname)
            rel = os.path.relpath(abspath, root).replace("\\", "/")
            try:
                with open(abspath, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
            except (SyntaxError, OSError):
                continue
            for node in tree.body:  # top-level defs only
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                params = [a.arg for a in node.args.args]
                arg_src = ", ".join(ast.unparse(a) for a in node.args.args)
                ret = ast.unparse(node.returns) if node.returns else ""
                sig = f"def {node.name}({arg_src})" + (f" -> {ret}" if ret else "")
                funcs.append(
                    pb.FunctionInfo(
                        name=node.name,
                        file_path=rel,
                        signature=sig,
                        docstring=ast.get_docstring(node) or "",
                        return_type=ret,
                        is_async=isinstance(node, ast.AsyncFunctionDef),
                        line_number=node.lineno,
                        param_names=params,
                    )
                )
    return funcs


def _fmt_candidate_block(c: pb.DetectedEndpoint) -> str:
    return (
        f"### Function: `{c.name}`\n"
        f"- File: `{c.file_path}`\n"
        f"- Signature: `{c.signature}`\n"
        f"- Conversion Type: {c.conversion_type.upper()}\n"
        f"- Description: {c.human_description or c.docstring.splitlines()[0] if c.docstring else c.name}"
    )


def main() -> None:
    if not KEY:
        raise SystemExit("Set SYNAPSE_E2E_KEY to an API key from the dashboard.")
    root = sys.argv[1] if len(sys.argv) > 1 else "../sample-project"
    root = os.path.abspath(root)
    print(f"codebase : {root}")
    print(f"backend  : {ADDR}   key: {KEY[:16]}…")

    functions = extract_functions(root)
    print(f"\nExtracted {len(functions)} function(s): "
          f"{', '.join(f.name for f in functions)}")
    if not functions:
        raise SystemExit("No functions found.")

    md = [("x-api-key", KEY)]
    channel = grpc.insecure_channel(ADDR)
    stub = pb_grpc.SynapseServiceStub(channel)

    print("\n[detect] classifying...")
    dr = stub.DetectEndpoints(
        pb.DetectRequest(working_dir=root, functions=functions,
                         project_schema="sample supply-chain project"),
        metadata=md,
    )
    if dr.error:
        raise SystemExit(f"detect error: {dr.error}")
    cands = sorted(dr.candidates, key=lambda c: c.confidence, reverse=True)
    for c in cands:
        print(f"   - {c.name:26s} conf={c.confidence:.2f}  [{c.subcategory}]")
    print(f"   -> {len(cands)} candidate(s); "
          f"{len(functions) - len(cands)} filtered out")

    query = "Create MCP tools for the following endpoints:\n\n" + "\n\n".join(
        _fmt_candidate_block(c) for c in cands
    )

    print("\n[build] generating server...")
    result = None
    for msg in stub.Build(
        iter([pb.BuildMessage(build_request=pb.BuildRequest(
            query=query, project_schema="sample supply-chain project",
            working_dir=root, output_file="mcp_server.py", validate=True, docs=True,
        ))]),
        metadata=md,
    ):
        which = msg.WhichOneof("payload")
        if which == "status_update":
            s = msg.status_update
            print(f"   [{s.stage:12s}] {s.progress*100:5.1f}%  {s.message}")
        elif which == "build_result":
            result = msg.build_result
        elif which == "error":
            raise SystemExit(f"build error: {msg.error.message}")

    if not result or not result.success:
        raise SystemExit("build failed")

    out_path = os.path.join(root, "mcp_server.py")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(result.server_code)
    print(f"\n✅ Wrote {out_path}  ({result.tool_count} tools, "
          f"{len(result.server_code.splitlines())} lines)")
    print("   It now appears on your dashboard → http://localhost:8000/app")
    channel.close()


if __name__ == "__main__":
    main()
