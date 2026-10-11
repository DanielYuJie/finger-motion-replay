"""把 finger-motion-replay 的视觉屈曲角映射为 ORCA Hand 的关节目标。

输入是浏览器端 MediaPipe 管线产出的 payload（见 finger-motion-replay/app.js 的
pushBridge），单位是度、0 表示伸直、数值变大表示屈曲。输出是 ORCA
config.yaml 里 joint_ids 所定义的 17 个关节角，同样是度。

两个来源的约定本来就接近（都以屈曲为正、都用度），所以映射是仿射的：
    目标 = neutral + gain * (视觉角 / 满屈曲角) * (rom_max - neutral)
再夹到 [rom_min, rom_max]。ORCA 侧不提供视觉输入的关节（外展、腕）按策略保持。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# 视觉 payload 的键 -> ORCA 关节名。
# 拇指的 payload 键是 mcp/pip/dip，但语义是 CMC/MCP/IP（app.js 里 FINGER_DEFS
# 的 joints 才是解剖学名字），这里按语义修正。
# 四指在 ORCA v2 上只有 mcp/pip，DIP 没有对应关节，因此被丢弃。
# ---------------------------------------------------------------------------
VISION_TO_ORCA: dict[tuple[str, str], str] = {
    ("thumb", "mcp"): "thumb_cmc",
    ("thumb", "pip"): "thumb_mcp",
    ("thumb", "dip"): "thumb_dip",
    ("index", "mcp"): "index_mcp",
    ("index", "pip"): "index_pip",
    ("middle", "mcp"): "middle_mcp",
    ("middle", "pip"): "middle_pip",
    ("ring", "mcp"): "ring_mcp",
    ("ring", "pip"): "ring_pip",
    ("pinky", "mcp"): "pinky_mcp",
    ("pinky", "pip"): "pinky_pip",
}

FINGERS = ("thumb", "index", "middle", "ring", "pinky")
NON_THUMB = ("index", "middle", "ring", "pinky")

# 没有视觉输入的关节：外展每指一个，另有腕。
ABDUCTION_JOINTS = {
    "index": "index_abd",
    "middle": "middle_abd",
    "ring": "ring_abd",
    "pinky": "pinky_abd",
    "thumb": "thumb_abd",
}

# ORCA v2 右手的内置副本，仅在读不到 config.yaml 时兜底。
# 数值来源：orca_core/models/v2/orcahand-right/config.yaml
FALLBACK_JOINT_IDS: tuple[str, ...] = (
    "wrist",
    "thumb_cmc", "thumb_abd", "thumb_mcp", "thumb_dip",
    "index_abd", "index_mcp", "index_pip",
    "middle_abd", "middle_mcp", "middle_pip",
    "ring_abd", "ring_mcp", "ring_pip",
    "pinky_abd", "pinky_mcp", "pinky_pip",
)

FALLBACK_ROMS: dict[str, tuple[float, float]] = {
    "wrist": (-65.0, 35.0),
    "thumb_cmc": (-45.0, 33.0),
    "thumb_abd": (-18.0, 55.0),
    "thumb_mcp": (-25.0, 100.0),
    "thumb_dip": (-15.0, 107.0),
    "index_abd": (-25.0, 30.0),
    "index_mcp": (-25.0, 100.0),
    "index_pip": (-15.0, 107.0),
    "middle_abd": (-27.0, 27.0),
    "middle_mcp": (-25.0, 100.0),
    "middle_pip": (-15.0, 107.0),
    "ring_abd": (-27.0, 27.0),
    "ring_mcp": (-25.0, 100.0),
    "ring_pip": (-15.0, 107.0),
    "pinky_abd": (-30.0, 30.0),
    "pinky_mcp": (-25.0, 100.0),
    "pinky_pip": (-15.0, 107.0),
}

FALLBACK_NEUTRAL: dict[str, float] = {
    "wrist": -20.0,
    "thumb_cmc": 0.0, "thumb_abd": 50.0, "thumb_mcp": 33.0, "thumb_dip": 18.0,
    "index_abd": -14.0, "index_mcp": 2.0, "index_pip": 6.0,
    "middle_abd": -4.0, "middle_mcp": 2.0, "middle_pip": 4.0,
    "ring_abd": 10.0, "ring_mcp": -2.0, "ring_pip": 8.0,
    "pinky_abd": 22.0, "pinky_mcp": -4.0, "pinky_pip": -2.0,
}


@dataclass
class Tuning:
    """可调参数，改 YAML 即可，不必动代码。"""

    # 视觉角达到多少度算「满屈曲」，即映射到 rom_max。
    full_flexion_deg: float = 100.0
    # 整体增益，用于整体压小/放大动作幅度。
    gain: float = 1.0
    # 无视觉输入的关节怎么处理：neutral 保持中立位 / zero 归零。
    abduction_policy: str = "neutral"
    wrist_policy: str = "neutral"
    # 仅当 payload 只带 flex（0-100 索引）时使用，按 ROM 跨度分配屈曲量。
    flex_fallback_enabled: bool = True
    # 从世界坐标 landmark 估外展（实验性）。默认关闭。
    abduction_from_landmarks: bool = False
    # 逐关节覆盖。
    per_joint_full_flexion: dict[str, float] = field(default_factory=dict)
    per_joint_gain: dict[str, float] = field(default_factory=dict)
    # 安全上限：单帧允许的最大关节变化量（度），None 表示不限。
    # 默认开启：遥操作时一帧跳 100° 会直接拽到腱绳，宁可跟不上也不要甩手。
    max_step_deg: float | None = 25.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Tuning":
        data = dict(data or {})
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"未知的配置项: {sorted(unknown)}")
        return cls(**data)


def _load_hand_config(path: str | Path) -> tuple[tuple[str, ...], dict[str, tuple[float, float]], dict[str, float]]:
    """从 ORCA 的 config.yaml 读取关节顺序、ROM 与中立位。"""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    joint_ids = tuple(raw["joint_ids"])
    roms = {j: (float(lo), float(hi)) for j, (lo, hi) in raw["joint_roms"].items()}
    neutral = {j: float(v) for j, v in raw["neutral_position"].items()}
    missing = [j for j in joint_ids if j not in roms and j != "wrist"]
    if missing:
        raise ValueError(f"config.yaml 缺少这些关节的 ROM: {missing}")
    # 腕没有 ROM 时可自行放宽，不阻塞其余关节。
    for j in joint_ids:
        roms.setdefault(j, FALLBACK_ROMS.get(j, (-180.0, 180.0)))
        neutral.setdefault(j, 0.0)
    return joint_ids, roms, neutral


class OrcaJointMap:
    """视觉屈曲角 -> ORCA 关节目标。"""

    def __init__(
        self,
        hand_config_path: str | Path | None = None,
        tuning: Tuning | Mapping[str, Any] | None = None,
    ) -> None:
        if hand_config_path is not None and Path(hand_config_path).exists():
            self.joint_ids, self.roms, self.neutral = _load_hand_config(hand_config_path)
            self.source = str(hand_config_path)
        else:
            self.joint_ids = FALLBACK_JOINT_IDS
            self.roms = dict(FALLBACK_ROMS)
            self.neutral = dict(FALLBACK_NEUTRAL)
            self.source = "内置 ORCA v2 右手副本"

        self.tuning = tuning if isinstance(tuning, Tuning) else Tuning.from_mapping(tuning)

        unknown = [j for j in self.roms if j not in self.joint_ids]
        if unknown:
            raise ValueError(f"ROM 里出现了 joint_ids 之外的关节: {unknown}")

    # -- 基础工具 ---------------------------------------------------------

    def clamp(self, joints: Mapping[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for joint in self.joint_ids:
            value = float(joints.get(joint, self.neutral[joint]))
            lo, hi = self.roms[joint]
            out[joint] = min(max(value, lo), hi)
        return out

    def neutral_pose(self) -> dict[str, float]:
        return self.clamp({j: self.neutral[j] for j in self.joint_ids})

    def to_ordered_array(self, joints: Mapping[str, float]) -> list[float]:
        """按 config.yaml 的 joint_ids 顺序展开，供 set_joint_positions 的 ndarray 用。"""
        return [float(joints[j]) for j in self.joint_ids]

    def _full_flexion(self, joint: str) -> float:
        return float(self.tuning.per_joint_full_flexion.get(joint, self.tuning.full_flexion_deg))

    def _gain(self, joint: str) -> float:
        return float(self.tuning.per_joint_gain.get(joint, self.tuning.gain))

    def _flex_to_joint(self, joint: str, flexion_deg: float) -> float:
        full = self._full_flexion(joint)
        if full <= 0:
            raise ValueError(f"{joint} 的 full_flexion_deg 必须为正，收到 {full}")
        span = self.roms[joint][1] - self.neutral[joint]
        return self.neutral[joint] + self._gain(joint) * (flexion_deg / full) * span

    # -- 主映射 -----------------------------------------------------------

    def from_vision_payload(self, payload: Mapping[str, Any] | None) -> dict[str, float]:
        """把一帧视觉得到 payload 变成完整的 17 关节目标。"""
        pose = self.neutral_pose()
        if not payload or not payload.get("hand"):
            return pose

        fingers = payload.get("fingers") or {}
        landmarks = payload.get("world_landmarks") or payload.get("worldLandmarks")

        for finger in FINGERS:
            data = fingers.get(finger) or {}
            mapped_any = False
            for vision_key, joint in VISION_TO_ORCA.items():
                if vision_key[0] != finger:
                    continue
                if vision_key[1] in data and data[vision_key[1]] is not None:
                    pose[joint] = self._flex_to_joint(joint, float(data[vision_key[1]]))
                    mapped_any = True
            if not mapped_any and self.tuning.flex_fallback_enabled:
                self._apply_flex_fallback(pose, finger, data)

        if self.tuning.abduction_from_landmarks and landmarks:
            pose.update(self.abduction_from_landmarks(landmarks))

        return self.clamp(pose)

    def _apply_flex_fallback(self, pose: dict[str, float], finger: str, data: Mapping[str, Any]) -> None:
        """只有 flex（0-100 索引）时，按各关节 ROM 跨度分配屈曲量。"""
        if "flex" not in data:
            return
        fraction = max(0.0, min(100.0, float(data["flex"]))) / 100.0
        for (f, _), joint in VISION_TO_ORCA.items():
            if f != finger:
                continue
            span = self.roms[joint][1] - self.neutral[joint]
            pose[joint] = self.neutral[joint] + self._gain(joint) * fraction * span

    # -- 外展估计（实验性） ------------------------------------------------

    def abduction_from_landmarks(self, landmarks: Any) -> dict[str, float]:
        """用世界坐标 landmark 的掌面扇形角估外展。

        landmark 需为 21×3、米制、腕部相对（MediaPipe world landmarks）。
        以食/小指 MCP 与腕定义掌面，取各指在掌面上的投影相对中指的张角。
        这是近似：ORCA 官方做法是用 orca_teleop 的重定向器联合求解。
        """
        import numpy as np

        pts = np.asarray(landmarks, dtype=float)
        if pts.shape != (21, 3):
            raise ValueError(f"landmarks 形状应为 (21,3)，收到 {pts.shape}")

        wrist, index_mcp, pinky_mcp = pts[0], pts[5], pts[17]
        normal = np.cross(index_mcp - wrist, pinky_mcp - wrist)
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            return {}
        normal = normal / norm

        def palm_direction(mcp: int, pip: int) -> "np.ndarray | None":
            d = pts[pip] - pts[mcp]
            d = d - np.dot(d, normal) * normal
            n = np.linalg.norm(d)
            return d / n if n > 1e-9 else None

        reference = palm_direction(9, 10)  # 中指 MCP->PIP
        if reference is None:
            return {}

        out: dict[str, float] = {}
        for finger, (mcp, pip) in (("index", (5, 6)), ("ring", (13, 14)), ("pinky", (17, 18))):
            direction = palm_direction(mcp, pip)
            if direction is None:
                continue
            angle = np.degrees(np.arctan2(
                np.dot(np.cross(reference, direction), normal),
                np.dot(reference, direction),
            ))
            joint = ABDUCTION_JOINTS[finger]
            lo, hi = self.roms[joint]
            mid = self.neutral[joint]
            # ±25° 的扇形角对应到 ROM 的两端。
            scaled = mid + angle / 25.0 * max(abs(hi - mid), abs(mid - lo))
            out[joint] = min(max(scaled, lo), hi)
        return out

    # -- 限速 -------------------------------------------------------------

    def limit_step(self, target: Mapping[str, float], previous: Mapping[str, float] | None) -> dict[str, float]:
        """把单帧变化压到 max_step_deg 以内，避免遥操作时甩手。"""
        limit = self.tuning.max_step_deg
        if limit is None or previous is None:
            return dict(target)
        out: dict[str, float] = {}
        for joint in self.joint_ids:
            want = float(target[joint])
            was = float(previous.get(joint, want))
            out[joint] = was + min(max(want - was, -limit), limit)
        return out


def load_tuning(path: str | Path | None) -> Tuning:
    if path is None:
        return Tuning()
    if not Path(path).exists():
        raise FileNotFoundError(f"映射配置不存在: {path}")
    import yaml

    return Tuning.from_mapping(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
