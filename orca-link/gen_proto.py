"""从 orca_teleop 的 hand_stream.proto 生成 gRPC 桩。

proto 是 orca_teleop 的事实协议，这里直接用它的原件生成，保证线上格式一致。
生成到同目录的 proto_gen/ 下，grpc 版本要与 orca_teleop 的对齐（protobuf<5）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orca_paths import teleop_proto  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 hand_stream gRPC 桩")
    parser.add_argument("--proto", default=None, help="默认取 orca_teleop 里的原生 proto 原件")
    parser.add_argument("--out", default=str(Path(__file__).with_name("proto_gen")))
    args = parser.parse_args(argv)

    proto = Path(args.proto) if args.proto else teleop_proto()
    if not proto.exists():
        print(f"proto 不存在: {proto}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from grpc_tools import protoc

    code = protoc.main([
        "grpc_tools.protoc",
        f"-I{proto.parent}",
        f"--python_out={out}",
        f"--grpc_python_out={out}",
        str(proto),
    ])
    if code != 0:
        print(f"protoc 失败，退出码 {code}", file=sys.stderr)
        return code

    generated = sorted(p.name for p in out.glob("*_pb2*.py"))
    print("生成:", ", ".join(generated) if generated else "(无)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
