"""定位 ORCA 上游检出（orca_core / orcahand_description / orca_teleop）。

这些仓库不 vendor 进本项目，需要单独 clone。搜索顺序：

1. 环境变量 ``ORCA_LINK_ORCA_ROOT``（显式指定，最优先）
2. ``<本目录>/../orca-ecosystem``      —— 与项目平级放一个 orca-ecosystem 目录
3. ``<本目录>/vendor``
4. ``<本目录>/../vendor``

在每个候选根下再识别三种布局：
  ``orca_core-upstream/orca_core``  或  ``orca_core/orca_core``   控制器与模型配置
  ``orcahand_description``                                      URDF / MJCF
  ``orca_teleop/src/orca_teleop``                                遥操作栈
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _candidates() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("ORCA_LINK_ORCA_ROOT")
    if env:
        roots.append(Path(env).expanduser())
    roots += [
        HERE.parent / "orca-ecosystem",
        HERE.parent.parent / "orca-ecosystem",
        HERE / "vendor",
        HERE.parent / "vendor",
    ]
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        resolved = root.resolve() if root.exists() else root
        if resolved not in seen:
            seen.add(resolved)
            out.append(root)
    return out


def _first(paths) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def orca_root() -> Path | None:
    """返回第一个能认出控制器检出的候选根。"""
    for root in _candidates():
        if (root / "orca_core-upstream" / "orca_core").exists():
            return root
        if (root / "orca_core" / "orca_core").exists():
            return root
    return None


def _require(found: Path | None, what: str, hint: str) -> Path:
    if found is None:
        searched = "\n".join(f"    - {c}" for c in _candidates())
        raise FileNotFoundError(
            f"找不到{what}。\n  搜索过这些根目录:\n{searched}\n"
            f"  解决办法：{hint}\n"
            f"  或者设置环境变量 ORCA_LINK_ORCA_ROOT 指向含这些检出的目录。"
        )
    return found


def core_package_dir() -> Path:
    """`orca_core` 包目录（含 models/ 与 kinematics/）。"""
    for root in _candidates():
        for sub in ("orca_core-upstream", "orca_core"):
            candidate = root / sub / "orca_core"
            if candidate.exists():
                return candidate
    return _require(
        None,
        "orca_core 检出",
        "git clone https://github.com/orcahand/orca_core 到 <ORCA_LINK_ORCA_ROOT>/orca_core-upstream",
    )


def core_models_dir() -> Path:
    return core_package_dir() / "models"


def core_config(version: str = "v2", hand: str = "right") -> Path:
    """ORCA 手模型配置，例如 models/v2/orcahand-right/config.yaml。"""
    path = core_models_dir() / version / f"orcahand-{hand}" / "config.yaml"
    return _require(
        path if path.exists() else None,
        f"{version} {hand} 手配置",
        f"确认 orca_core 检出完整（应存在 {path}）",
    )


def description_dir() -> Path:
    """orcahand_description 检出根（其下有 v1/ 与 v2/）。"""
    env = os.environ.get("ORCAHAND_DESCRIPTION_DIR")
    if env and Path(env).exists():
        return Path(env)
    return _require(
        _first(root / "orcahand_description" for root in _candidates()),
        "orcahand_description 检出",
        "git clone https://github.com/orcahand/orcahand_description 到 "
        "<ORCA_LINK_ORCA_ROOT>/orcahand_description（或设 ORCAHAND_DESCRIPTION_DIR）",
    )


def urdf(version: str = "v1", hand: str = "right") -> Path:
    """URDF 路径。

    注意默认是 **v1**：v2 的 URDF/MJCF 用 CAD 命名（I-AP-R_d95d02d1），
    而上游重定向配置的 v2 帧表要的是语义名（right_index_mcp），对不上。
    v1 才是语义命名。详见 README。
    """
    path = description_dir() / version / "models" / "urdf" / f"orcahand_{hand}.urdf"
    return _require(
        path if path.exists() else None,
        f"{version} {hand} URDF",
        f"确认 orcahand_description 完整（应存在 {path}）",
    )


def teleop_proto() -> Path:
    """orca_teleop 的 hand_stream.proto 原件。"""
    for root in _candidates():
        path = root / "orca_teleop" / "src" / "orca_teleop" / "ingress" / "hand_stream.proto"
        if path.exists():
            return path
    return _require(
        None,
        "orca_teleop 的 hand_stream.proto",
        "git clone https://github.com/orcahand/orca_teleop 到 <ORCA_LINK_ORCA_ROOT>/orca_teleop",
    )


def teleop_src() -> Path:
    """orca_teleop 的 src 目录（可直接塞进 sys.path 读源码）。"""
    for root in _candidates():
        path = root / "orca_teleop" / "src" / "orca_teleop"
        if path.exists():
            return path
    return _require(
        None,
        "orca_teleop 源码",
        "git clone https://github.com/orcahand/orca_teleop 到 <ORCA_LINK_ORCA_ROOT>/orca_teleop",
    )


def describe() -> str:
    """给自检/启动日志用的一行诊断。"""
    lines = [f"ORCA_LINK_ORCA_ROOT 候选根: {', '.join(str(c) for c in _candidates())}"]
    for label, getter in (
        ("orca_core 模型目录", core_models_dir),
        ("orcahand_description", description_dir),
        ("orca_teleop 源码", teleop_src),
    ):
        try:
            lines.append(f"  {label}: {getter()}")
        except FileNotFoundError:
            lines.append(f"  {label}: 未找到")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
