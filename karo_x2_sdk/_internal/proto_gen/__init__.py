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
