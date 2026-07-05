"""gRPC server entrypoint: ``python -m synapse_backend.grpc_service.server``."""

from __future__ import annotations

import logging
from concurrent import futures

import grpc

from synapse_backend.config import settings
from synapse_backend.grpc_service.servicer import SynapseServicer
from synapse_backend.proto import synapse_pb2_grpc as pb_grpc

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("synapse.grpc")


def serve() -> None:
    options = [
        ("grpc.max_send_message_length", settings.grpc_max_message_bytes),
        ("grpc.max_receive_message_length", settings.grpc_max_message_bytes),
        # Match the client's keepalive expectations.
        ("grpc.keepalive_time_ms", 60000),
        ("grpc.keepalive_timeout_ms", 40000),
        ("grpc.keepalive_permit_without_calls", 0),
    ]
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=16),
        options=options,
    )
    pb_grpc.add_SynapseServiceServicer_to_server(SynapseServicer(), server)

    address = f"{settings.grpc_host}:{settings.grpc_port}"
    server.add_insecure_port(address)
    server.start()
    logger.info("Synapse gRPC server listening on %s (provider=%s)",
                address, settings.llm_provider)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
