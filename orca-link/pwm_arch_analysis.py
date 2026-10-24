"""PWM 平替舵机方案的可行性分析：行程、量程、量化、速度、重量、扭矩。

背景
----
用户决定走自主路线：用 ¥25 的 PWM 舵机（40x20x40mm, 55g, 4.8-7.4V,
PWM 500-2500us, 180/270°, 堵转 20KG@6V / 23KG@7.4V, 速度 0.16s/60°@6V
/ 0.14s/60°@7.4V）替代 HLS3915/HLS3930，重新设计架构。

这个脚本只回答"物理量行不行"，不管"软件栈重写"那部分。

关键假设（都标了 [假设]，来源见注释）：
- 传动比 ratio = 关节滑轮半径 / 线轴缠绕半径。线轴 OD 21mm（实测 BaseSpool），
  缠绕半径取 8.5mm [假设]；关节滑轮半径取 4.5mm [假设]（FDM 手指关节典型值，
  未实测）。ratio 扫描 0.40 / 0.53 / 0.60 三档看敏感性。
- 舵机 180° 与 270° 两个版本都算。
- PWM 用 PCA9685 12-bit [方案假设]。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(os.path.dirname(HERE), "orca-ecosystem", "orca_core-upstream")
if not os.path.isdir(CORE):
    CORE = r"D:\DSPersonal Project Area\orca-ecosystem\orca_core-upstream"
sys.path.insert(0, CORE)

import yaml

CONFIG = os.path.join(CORE, "orca_core", "models", "v2", "orcahand-right", "config.yaml")

# ---- 舵机参数（来自用户提供的参数表）----
SERVO = {
    "range_deg": 180.0,        # 或 270
    "speed_s60_deg": 0.14,     # s/60° @7.4V（电机侧）
    "stall_nm": 23.0 * 9.81 / 100.0,  # 23KG@7.4V -> N·m
    "weight_g": 55.0,
    "pwm_us": (500.0, 2500.0),
    "volt": "4.8-7.4V",
}
PCA9685_STEPS = 4096
PCA9685_PERIOD_US = 20480.0 / 1.0  # 50Hz 周期 20ms（可改频率）


def main() -> int:
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    roms = cfg["joint_roms"]
    neutral = cfg.get("neutral_position", {})
    print(f"  关节数: {len(roms)}")
    print(f"  传动比假设: 关节滑轮 4.5mm / 线轴缠绕 8.5mm ≈ 0.53（扫描 0.40/0.53/0.60）")
    print(f"  舵机: {SERVO['range_deg']}° / 堵转 {SERVO['stall_nm']:.2f} N·m / "
          f"{SERVO['speed_s60_deg']} s/60° @7.4V / {SERVO['weight_g']} g\n")

    print(f"  {'关节':<12} {'ROM范围':>10} {'行程':>6} | {'电机行程°(0.40)':>12} "
          f"{'电机行程°(0.53)':>12} {'电机行程°(0.60)':>12} | {'180°余量':>8}")
    print("  " + "-" * 86)
    worst = {}
    for j, (lo, hi) in roms.items():
        span = hi - lo
        tr = {}
        for r in (0.40, 0.53, 0.60):
            tr[r] = span * r
        m = (hi + lo) / 2
        margin = 90.0 - tr[0.53]  # 180° 版：以中位为中心的半行程余量
        worst[j] = (span, tr[0.53], margin)
        print(f"  {j:<12} [{lo:>4},{hi:>4}] {span:>5}° | {tr[0.40]:>11.1f}° "
              f"{tr[0.53]:>11.1f}° {tr[0.60]:>11.1f}° | {margin:>+7.1f}°")
    print()

    # ---- 行程结论 ----
    need = max(v[1] for v in worst.values())
    print(f"  最大电机行程需求 ≈ {need:.1f}°（ratio=0.53 时）")
    for rng in (180.0, 270.0):
        ok = all(v[1] <= rng for v in worst.values())
        print(f"    {rng:.0f}° 舵机: {'覆盖全部关节 ✓' if ok else '不够 ✗'}"
              f"（最紧张的是 {max(worst, key=lambda k: worst[k][1])}）")

    # ---- PWM 量程 ----
    pwm_span_us = SERVO["pwm_us"][1] - SERVO["pwm_us"][0]
    us_per_deg = pwm_span_us / SERVO["range_deg"]
    # 舵机定位精度 = PWM 每步对应的角度
    step_us = PCA9685_PERIOD_US / PCA9685_STEPS
    servo_step_deg = step_us / us_per_deg
    # 换算到关节侧（除以 ratio）
    joint_step_deg = servo_step_deg / 0.53
    print(f"  PWM 量程: {SERVO['pwm_us'][0]}-{SERVO['pwm_us'][1]}µs = "
          f"{us_per_deg:.2f} µs/°（电机侧）")
    print(f"  PCA9685 12bit 每步 {step_us:.2f} µs -> 电机侧 {servo_step_deg:.3f}°/步 "
          f"-> 关节侧 ≈ {joint_step_deg:.3f}°/步")
    print(f"  （对比：舵机自身死区通常在 0.5-1°，量化误差不是短板）")

    # ---- 速度与滞后 ----
    servo_speed_deg_s = 60.0 / SERVO["speed_s60_deg"]       # 电机侧 °/s
    joint_speed_deg_s = servo_speed_deg_s / 0.53             # 关节侧 °/s
    print(f"\n  舵机转速 {servo_speed_deg_s:.0f}°/s（电机侧）-> 关节侧 {joint_speed_deg_s:.0f}°/s")
    # 参考：实测 wave 手势关节峰值速度 ~77°/s（30Hz 遥操作数据）
    gesture = 77.0
    print(f"  实测手势峰值速度 {gesture:.0f}°/s -> 舵机能力是其 {joint_speed_deg_s/gesture:.1f} 倍")
    print(f"  -> 速度不构成瓶颈；舵机的启停死区带来的滞后是主要误差源（需真机实测）")

    # ---- 重量与扭矩 ----
    print(f"\n  重量: 17 × {SERVO['weight_g']} g = {17*SERVO['weight_g']} g"
          f"（对比 XC330: 17×23g = 391 g，+{17*SERVO['weight_g']-391} g）")
    # 扭矩物理：腱绳张力 = 电机扭矩 / 线轴半径；关节扭矩 = 张力 × 滑轮半径
    # 即 关节扭矩 = 电机扭矩 × (r_pulley / r_spool)。传动把扭矩**缩小**（行程放大）。
    ratio_mech = 4.5 / 8.5
    joint_torque = SERVO["stall_nm"] * ratio_mech
    print(f"  扭矩: 堵转 {SERVO['stall_nm']:.2f} N·m（电机）x (4.5/8.5) = "
          f"{joint_torque:.2f} N·m（关节，按假设的半径比）")
    # 更有说服力的对比：与设计基准 HLS3915（堵转 1.39 N·m）直接比
    print(f"  对比设计基准: HLS3915 电机堵转 1.39 N·m；这颗 2.26 N·m 是其 "
          f"{SERVO['stall_nm']/1.39:.1f} 倍")
    print(f"  -> 论文口径四指 10.5kg 是在 HLS3915 上、600mA 下做到的；"
          f"电机端强 1.6 倍的舵机，同样的腱绳几何下至少不弱于设计基准")
    print(f"  （精确的关节扭矩要等实测线轴缠绕半径与关节滑轮半径后才有定数）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
