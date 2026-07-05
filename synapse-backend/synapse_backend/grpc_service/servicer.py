"""SynapseServiceServicer implementation.

Implements the four RPCs the CLI calls:

* DetectEndpoints (unary)  — classify functions into MCP tool candidates.
* Build (bidi stream)      — run the agent pipeline, stream status, return code.
* TrackEvent (unary)       — quota_check / quota_info + telemetry.
* Analyze (bidi stream)    — legacy; analyze is local in the CLI, so this just
                             returns a friendly not-needed result.

Auth: Build/Detect read the raw key from ``x-api-key`` metadata; TrackEvent uses
the ``api_key_hash`` field (sha256 of the key). Both resolve to an ApiKey row.

Build orchestration: the pipeline runs in a worker thread and pushes
status/result items onto a queue; the RPC generator drains the queue and yields
protobuf messages. Context is supplied up-front by the CLI (project_schema +
context_bundle), so Build is effectively server-streaming for the POC.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any, Iterator

import grpc

from synapse_backend.auth.api_keys import get_by_hash_sync, validate_raw_key_sync
from synapse_backend.db import quota as quota_svc
from synapse_backend.db.database import SessionLocal
from synapse_backend.db.models import ApiKey
from synapse_backend.proto import synapse_pb2 as pb
from synapse_backend.proto import synapse_pb2_grpc as pb_grpc

logger = logging.getLogger(__name__)

_SENTINEL = object()


def _metadata_value(context: grpc.ServicerContext, key: str) -> str:
    for k, v in context.invocation_metadata() or ():
        if k.lower() == key:
            return v
    return ""


class SynapseServicer(pb_grpc.SynapseServiceServicer):
    # ── DetectEndpoints ──────────────────────────────────────────────────────
    def DetectEndpoints(
        self, request: pb.DetectRequest, context: grpc.ServicerContext
    ) -> pb.DetectResponse:
        from synapse_backend.agents.detector import detect

        raw_key = _metadata_value(context, "x-api-key")
        session = SessionLocal()
        try:
            api_key = validate_raw_key_sync(session, raw_key)
            if api_key is None:
                return pb.DetectResponse(error="Invalid or expired API key")

            functions = [
                {
                    "name": f.name,
                    "file_path": f.file_path,
                    "signature": f.signature,
                    "docstring": f.docstring,
                    "return_type": f.return_type,
                    "is_async": f.is_async,
                    "line_number": f.line_number,
                    "param_names": list(f.param_names),
                    "param_types": list(f.param_types),
                    "endpoint_type": f.endpoint_type,
                }
                for f in request.functions
            ]

            candidates = detect(functions, request.project_schema)

            quota_svc.touch_last_used(session, api_key)
            quota_svc.log_event(
                session,
                api_key=api_key,
                event_type="detect",
                candidate_count=len(candidates),
            )

            return pb.DetectResponse(
                candidates=[
                    pb.DetectedEndpoint(
                        name=c.get("name", ""),
                        file_path=c.get("file_path", ""),
                        confidence=float(c.get("confidence", 0.5)),
                        human_title=c.get("human_title", ""),
                        human_description=c.get("human_description", ""),
                        conversion_type=c.get("conversion_type", "ready"),
                        client_dependency_json=c.get("client_dependency_json", ""),
                        subcategory=c.get("subcategory", ""),
                        signature=c.get("signature", ""),
                        docstring=c.get("docstring", ""),
                        line_number=int(c.get("line_number", 0) or 0),
                    )
                    for c in candidates
                ],
                error="",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("DetectEndpoints failed")
            return pb.DetectResponse(error=str(exc))
        finally:
            session.close()

    # ── Build ────────────────────────────────────────────────────────────────
    def Build(
        self,
        request_iterator: Iterator[pb.BuildMessage],
        context: grpc.ServicerContext,
    ) -> Iterator[pb.BuildMessage]:
        from synapse_backend.agents.pipeline import run_build

        raw_key = _metadata_value(context, "x-api-key")

        # First message must be the build_request.
        first = next(request_iterator, None)
        if first is None or first.WhichOneof("payload") != "build_request":
            yield _error_msg("BAD_REQUEST", "Expected build_request as first message")
            return
        req = first.build_request

        session = SessionLocal()
        try:
            api_key = validate_raw_key_sync(session, raw_key)
            if api_key is None:
                yield _error_msg("UNAUTHENTICATED", "Invalid or expired API key")
                return

            if api_key.quota_exceeded:
                yield _build_result_msg(
                    {"success": False, "error": api_key.quota_message()}
                )
                return

            context_bundle: dict[str, Any] = {}
            if req.context_bundle:
                try:
                    context_bundle = json.loads(req.context_bundle)
                except json.JSONDecodeError:
                    context_bundle = {}

            out_q: queue.Queue = queue.Queue()

            def emit(stage, message, progress, agent_name="", task_name=""):
                out_q.put(
                    (
                        "status",
                        pb.BuildMessage(
                            status_update=pb.StatusUpdate(
                                stage=stage,
                                message=message,
                                progress=float(progress),
                                agent_name=agent_name,
                                task_name=task_name,
                            )
                        ),
                    )
                )

            def worker():
                try:
                    result = run_build(
                        query=req.query,
                        project_schema=req.project_schema,
                        working_dir=req.working_dir,
                        output_file=req.output_file or "mcp_server.py",
                        context_bundle=context_bundle,
                        generate_only=req.generate_only,
                        todo_list_content=req.todo_list_content,
                        emit=emit,
                        call_tool=None,  # context supplied up-front; bridge unused in POC
                    )
                    out_q.put(("result", result))
                except Exception as exc:  # noqa: BLE001
                    logger.exception("build worker crashed")
                    out_q.put(("error", str(exc)))
                finally:
                    out_q.put(_SENTINEL)

            threading.Thread(target=worker, daemon=True).start()

            while True:
                item = out_q.get()
                if item is _SENTINEL:
                    break
                kind, payload = item
                if kind == "status":
                    yield payload
                elif kind == "error":
                    yield _error_msg("BUILD_ERROR", payload)
                elif kind == "result":
                    self._finalize_build(session, api_key, req, payload)
                    yield _build_result_msg(payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Build failed")
            yield _error_msg("INTERNAL", str(exc))
        finally:
            session.close()

    def _finalize_build(
        self, session, api_key: ApiKey, req: pb.BuildRequest, result: dict
    ) -> None:
        """On success, archive code to S3 + record the server against quota."""
        if not result.get("success"):
            return
        try:
            from synapse_backend.storage.s3 import put_server_code

            server = quota_svc.record_server_generated(
                session,
                api_key,
                name=req.output_file or "mcp_server.py",
                query=req.query,
                tool_count=int(result.get("tool_count", 0)),
                resource_count=int(result.get("resource_count", 0)),
                line_count=len((result.get("server_code") or "").splitlines()),
                working_dir_hash="",
            )
            uri = put_server_code(api_key.id, server.id, result.get("server_code", ""))
            if uri:
                server.storage_uri = uri
                session.commit()
            quota_svc.log_event(
                session,
                api_key=api_key,
                event_type="build",
                tool_count=int(result.get("tool_count", 0)),
            )
        except Exception:  # noqa: BLE001 - accounting must never fail the build
            logger.exception("finalize_build accounting failed")

    # ── TrackEvent ───────────────────────────────────────────────────────────
    def TrackEvent(
        self, request: pb.TrackEventRequest, context: grpc.ServicerContext
    ) -> pb.TrackEventResponse:
        session = SessionLocal()
        try:
            snap = quota_svc.snapshot_by_hash(session, request.api_key_hash)
            # Opportunistic telemetry for non-quota events.
            if request.event_type not in ("quota_check", "quota_info"):
                api_key = get_by_hash_sync(session, request.api_key_hash)
                if api_key is not None and request.lines_count:
                    quota_svc.record_lines_indexed(
                        session, api_key, int(request.lines_count)
                    )
                    snap = quota_svc.snapshot_from_key(api_key)
            return pb.TrackEventResponse(
                success=True,
                quota_exceeded=snap["quota_exceeded"],
                quota_message=snap["quota_message"],
                mcp_servers_count=snap["mcp_servers_count"],
                max_mcp_servers=snap["max_mcp_servers"],
                lines_indexed=snap["lines_indexed"],
                max_lines_indexed=snap["max_lines_indexed"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("TrackEvent failed")
            return pb.TrackEventResponse(success=False, quota_message=str(exc))
        finally:
            session.close()

    # ── Analyze (legacy) ─────────────────────────────────────────────────────
    def Analyze(
        self,
        request_iterator: Iterator[pb.AnalyzeMessage],
        context: grpc.ServicerContext,
    ) -> Iterator[pb.AnalyzeMessage]:
        # analyze runs locally in the CLI now; acknowledge and return an empty result.
        next(request_iterator, None)
        yield pb.AnalyzeMessage(
            status_update=pb.StatusUpdate(
                stage="complete",
                message="Analyze runs locally in the CLI; nothing to do server-side.",
                progress=1.0,
            )
        )
        yield pb.AnalyzeMessage(analyze_result=pb.AnalyzeResult(success=True))


# ── message builders ─────────────────────────────────────────────────────────
def _error_msg(code: str, message: str) -> pb.BuildMessage:
    return pb.BuildMessage(
        error=pb.ErrorMessage(code=code, message=message, recoverable=False)
    )


def _build_result_msg(result: dict) -> pb.BuildMessage:
    return pb.BuildMessage(
        build_result=pb.BuildResult(
            success=bool(result.get("success", False)),
            server_code=result.get("server_code", "") or "",
            tool_count=int(result.get("tool_count", 0)),
            resource_count=int(result.get("resource_count", 0)),
            documentation=result.get("documentation", "") or "",
            todo_list=result.get("todo_list", "") or "",
            error=result.get("error", "") or "",
        )
    )
