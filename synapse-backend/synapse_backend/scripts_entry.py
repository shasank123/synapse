"""Container/CLI entrypoint for one-shot maintenance tasks.

Usage:
    python -m synapse_backend.scripts_entry init      # tables + seed key + bucket + collection
    python -m synapse_backend.scripts_entry new-key   # mint an extra dev API key
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("synapse.init")


def cmd_init() -> None:
    from synapse_backend.db.init_db import create_tables, seed_dev_key

    create_tables()
    seed_dev_key()

    # Best-effort provisioning of storage + vector infra (fail soft).
    try:
        from synapse_backend.storage.s3 import ensure_bucket

        ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bucket provisioning skipped: %s", exc)

    try:
        from synapse_backend.vector.qdrant_store import ensure_collection

        ensure_collection()
    except Exception as exc:  # noqa: BLE001
        logger.warning("collection provisioning skipped: %s", exc)

    logger.info("init complete")


def cmd_new_key() -> None:
    from synapse_backend.db.init_db import new_key

    new_key()


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    if cmd == "init":
        cmd_init()
    elif cmd == "new-key":
        cmd_new_key()
    else:
        print(f"Unknown command: {cmd}")
        print("Commands: init | new-key")
        sys.exit(1)


if __name__ == "__main__":
    main()
