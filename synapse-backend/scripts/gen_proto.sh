#!/usr/bin/env bash
# Regenerate the gRPC stubs from proto/synapse.proto.
#
# NOTE: for the POC we instead reuse the client's already-generated stubs
# (copied into synapse_backend/proto/) to guarantee an identical wire format.
# Run this only if you intentionally change the contract on both sides.
set -euo pipefail

cd "$(dirname "$0")/.."

python -m grpc_tools.protoc \
  -I proto \
  --python_out=synapse_backend/proto \
  --grpc_python_out=synapse_backend/proto \
  proto/synapse.proto

# Fix the import in the generated *_grpc.py to be a relative package import.
if [[ "$(uname)" == "Darwin" ]]; then
  sed -i '' 's/^import synapse_pb2/from . import synapse_pb2/' synapse_backend/proto/synapse_pb2_grpc.py
else
  sed -i 's/^import synapse_pb2/from . import synapse_pb2/' synapse_backend/proto/synapse_pb2_grpc.py
fi

echo "Regenerated synapse_pb2.py / synapse_pb2_grpc.py"
