#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_DIR="$(dirname "${SCRIPT_DIR}")"
REPO_ROOT="$(dirname "${PYTHON_DIR}")"
OUT_DIR="${PYTHON_DIR}/karo_x2_sdk/_internal/proto_gen"

if [ -f "${REPO_ROOT}/proto/sdk/common.proto" ]; then
  PROTO_SRC="${REPO_ROOT}/proto"
elif [ -f "${PYTHON_DIR}/proto/sdk/common.proto" ]; then
  PROTO_SRC="${PYTHON_DIR}/proto"
else
  echo "ERROR: cannot locate proto/ — looked at ${REPO_ROOT}/proto and ${PYTHON_DIR}/proto" >&2
  exit 1
fi
echo "[gen_proto] PROTO_SRC=${PROTO_SRC}"

if ! command -v protoc >/dev/null 2>&1; then
  echo "ERROR: protoc not found. Install protobuf-compiler (apt) or protobuf (brew)." >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"

FILES=(
  "sdk/common.proto"
  "sdk/session.proto"
  "sdk/v1/telemetry.proto"
  "karo/v1/common.proto"
  "karo/v1/rpc.proto"
  "karo/v1/control.proto"
  "karo/v1/safety.proto"
  "karo/v1/stream.proto"
  "karo/v1/telemetry_stream.proto"
  "karo/v1/transport.proto"
  "karo/v1/tasks.proto"
)

cd "${PROTO_SRC}"
protoc --experimental_allow_proto3_optional --python_out="${OUT_DIR}" "${FILES[@]}"

cat > "${OUT_DIR}/__init__.py" << 'PYINIT'
"""protoc 生成的 _pb2.py 文件包.

protoc --python_out 生成的代码用**绝对** import (例 ``from sdk import common_pb2``),
需要 proto_gen 目录在 sys.path 上才能解析. 此 __init__ 把自己的目录插入 sys.path,
让 ``karo_x2_sdk._internal.proto_gen`` 被 import 时绝对 import 工作.

调用方应通过 ``from karo_x2_sdk._internal.proto_gen.sdk import common_pb2`` 命名空间访问;
sys.path hack 仅为 generated 代码内部 import 服务.
"""
import os as _os
import sys as _sys

_here = _os.path.dirname(__file__)
if _here not in _sys.path:
    _sys.path.insert(0, _here)

del _os, _sys, _here
PYINIT

touch "${OUT_DIR}/sdk/__init__.py"
touch "${OUT_DIR}/sdk/v1/__init__.py"
touch "${OUT_DIR}/karo/__init__.py"
touch "${OUT_DIR}/karo/v1/__init__.py"

echo "generated _pb2.py files in ${OUT_DIR}:"
find "${OUT_DIR}" -name '*_pb2.py' | sort

echo ""
echo "remember to: git add ${OUT_DIR}"

