"""S3 / MinIO client for storing generated MCP server source.

Per the doc's data layer, generated servers are stored in object storage. We
store each build's ``mcp_server.py`` under ``<api_key_id>/<server_id>.py`` and
keep the ``s3://`` URI on the MCPServer row.

All operations fail soft: if storage is unavailable the build still succeeds
(the code is also returned inline to the CLI), we just skip archiving.
"""

from __future__ import annotations

import logging

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from synapse_backend.config import settings

logger = logging.getLogger(__name__)


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket() -> bool:
    """Create the bucket if missing. Returns True on success."""
    try:
        client = _client()
        existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
        if settings.s3_bucket not in existing:
            client.create_bucket(Bucket=settings.s3_bucket)
            logger.info("Created S3 bucket %s", settings.s3_bucket)
        return True
    except (BotoCoreError, ClientError) as exc:
        logger.warning("ensure_bucket failed: %s", exc)
        return False


def put_server_code(api_key_id: str, server_id: str, code: str) -> str:
    """Upload generated code. Returns the s3:// URI, or "" on failure."""
    key = f"{api_key_id}/{server_id}.py"
    try:
        _client().put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=code.encode("utf-8"),
            ContentType="text/x-python",
        )
        return f"s3://{settings.s3_bucket}/{key}"
    except (BotoCoreError, ClientError) as exc:
        logger.warning("put_server_code failed: %s", exc)
        return ""


def get_server_code(server_uri: str) -> str | None:
    """Fetch code back by s3:// URI."""
    if not server_uri.startswith("s3://"):
        return None
    _, _, rest = server_uri.partition("s3://")
    bucket, _, key = rest.partition("/")
    try:
        obj = _client().get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode("utf-8")
    except (BotoCoreError, ClientError) as exc:
        logger.warning("get_server_code failed: %s", exc)
        return None
