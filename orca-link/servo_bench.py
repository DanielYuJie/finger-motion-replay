"""伺服层台架：在电脑上调试 Feetech / Dynamixel 电机逻辑，不需要任何硬件。

为什么不用 MuJoCo 调电机
------------------------
`orca_sim` 的 MuJoCo 模型是 `ntendon = 0, neq = 0` —— 每个执行器**直接驱动一个关节**，
没有腱绳、没有耦合约束。它适合看整只手的动作是否合理，但**测不出**电机层真正会踩的坑：

  · ROM / 限位是否写对          · 方向与零位偏移
  · 寄存器宽度截断（写 200% 力矩实际存进去多少）
  · 力矩使能顺序、模式设置      · 总线上的缺号 / 掉线
  · 速度寄存器 0 的语义（见下）

`orca_core` 自带 `MockFeetechClient` / `MockDynamixelClient` / `MockHandSerialLink`，
它们走的是**真实客户端的同一套 API 与同一张寄存器表（HLS）**，只把串口换成内存。
所以在这一层调通的代码，搬到真机上是同一份。

⚠️ Feetech 专属坑（来自 `feetech_registers.HLS` 的注释）
    `GOAL_SPEED = 0` 在本系列表示**停机**，而 Dynamixel 上表示"不限速"。
    所以"不限速"要写寄存器能容纳的最大值（客户端已按 `SPEED_MAX_RAW` 处理），
    但如果你自己直接写寄存器，很容易把它写成 0 然后以为电机坏了。

用法
----
    python servo_bench.py                  # 全部演示（17 个 Feetech 电机）
    python servo_bench.py --demo limits    # 只看限位/截断
    python servo_bench.py --demo motion    # 只跑位置下发与回读
    python servo_bench.py --demo bus       # 只看总线扫描与缺号
    python servo_bench.py --demo ids       # 改电机 ID
    python servo_bench.py --motor dynamixel
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

try:
    from orca_core.hardware.motor_factory import mock_motor_client_class
    from orca_core.hardware.feetech_registers import HLS
except Exception as exc:  # pragma: no cover - 环境缺失时给出可读提示
    print(f"导入 orca_core 失败：{exc}")
    print("  需要先装好 orca_core（pip install --no-deps -e <orca-ecosystem>/orca_core-upstream）")
    sys.exit(1)

MODE_POSITION = 0  # HLS.MODE = 33: 0 位置（带电流限制）


def banner(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def make_client(motor_type: str, ids: list[int], baud: int):
    cls = mock_motor_client_class(motor_type)
    print(f"  客户端类: {cls.__name__}（内存实现，无串口）")
    print(f"  支持的波特率: {cls.supported_baudrates()}")
    client = cls(list(ids), port='MOCK', baudrate=baud, lazy_connect=False)
    # 立刻连接：各演示方法都要求已连接（mock 未连接会抛 OSError），
    # 放这里就不用每个子命令各自记得连。
    client.connect()
    return client


def demo_bus(client, ids: list[int]) -> None:
    banner("1) 总线：连接、扫描、缺号检测")
    print(f"  is_connected: {client.is_connected}")   # 注意：这是 property，不加括号
    print(f"  应到电机 ID: {ids}")
    print(f"  responding_motor_ids: {client.responding_motor_ids()}")
    absent = client.absent_motor_ids()
    print(f"  absent_motor_ids    : {absent if absent else '（无缺号）'}")
    try:
        ok = client.scan_for_motors('MOCK', (1, max(ids)))
        print(f"  scan_for_motors     : {ok}")
    except NotImplementedError:
        # 已知局限：mock 客户端不实现总线扫描（真机上才有意义，因为它要逐个波特率去试）。
        print("  scan_for_motors     : 该 mock 未实现（真机才有意义，要逐波特率试探）")


def demo_gains(client, ids: list[int]) -> None:
    banner("2) 伺服档位与增益（真机默认值，用于和硬件对表）")
    gains = client.read_servo_gains(ids)
    default = client.default_profile(ids)[ids[0]]
    print(f"  default_profile: velocity={default.velocity_rad_s} rad/s  "
          f"acceleration={default.acceleration_rad_s2} rad/s^2")
    first = gains[ids[0]]
    if first is not None:
        print(f"  电机 {ids[0]} 增益: kp={first.kp} ki={first.ki} kd={first.kd} "
              f"ff_1st={first.ff_1st} ff_2nd={first.ff_2nd}")
        print("  （HLS 上电即 Kp 32 / Kd 32 / Ki 0，见 mock_feetech_client 注释）")
    else:
        print(f"  电机 {ids[0]} 读不到增益")


def demo_limits(client, motor_type: str, ids: list[int]) -> None:
    banner("3) 限位与寄存器截断 —— 这一层最值钱的地方")
    lim = mock_motor_client_class(motor_type).servo_limits()
    for key in ('gain', 'velocity_rad_s', 'acceleration_rad_s2'):
        if key in lim:
            item = lim[key]
            print(f"  {key}: [{item.get('min')}, {item.get('max')}] {item.get('unit','')}"
                  f"   zero_means={item.get('zero_means')!r}")

    if motor_type == 'feetech':
        print()
        print("  HLS 寄存器宽度（写超范围时，客户端会回报寄存器实际存下的值）：")
        print(f"    GOAL_POSITION 单位 0.087 度/unit, BIT15 为符号位  -> 正负 {32767 * 0.087:.0f} 度")
        print(f"    GOAL_CURRENT  {HLS.CURRENT_SCALE_MA} mA/unit, 上限 {HLS.GOAL_CURRENT_MAX_RAW}")
        print(f"    GOAL_SPEED    {HLS.SPEED_SCALE_RAD_S:.4f} rad/s per unit, 上限 {HLS.SPEED_MAX_RAW}")
        print("    [坑] GOAL_SPEED = 0 在本系列表示【停机】，不是不限速")
        print(f"    PROTECTION_CURRENT = {HLS.PROTECTION_CURRENT}（上电时拷进 GOAL_CURRENT）")
        print(f"    LOCK = {HLS.LOCK}: 0 表示 EEPROM 写入掉电保留，1 表示不保留")

    # 截断演示：用"位置量程"来演，这是必定能生效、也最贴近真机的限制。
    # mock 的写位置会 np.clip 到 position_range_rad，并回报"实际存下的值"，
    # 于是"我明明写了 +15° 怎么不动"这类错误在接触硬件之前就暴露出来。
    low, high = client.position_range_rad
    print()
    print(f"  位置量程 position_range_rad = ({low:.4f}, {high:.4f}) rad "
          f"= ({np.rad2deg(low):.1f}°, {np.rad2deg(high):.1f}°)")
    print("  （HLS 是一圈量程：原始值 0..360°，BIT15 作符号位 -> 映射到 0 到 -360°）")
    target = ids[0]
    print()
    print(f"  —— 截断实演：给电机 {target} 下发几个越界/在界内的角度，看回读 ——")
    for deg in (30.0, -30.0, -90.0, -400.0):
        client.write_desired_pos([target], np.array([np.deg2rad(deg)]))
        got = np.rad2deg(float(client.read_position_velocity_current().position[0]))
        mark = "  <-- 被量程夹住" if abs(got - deg) > 0.5 else ""
        print(f"    指令 {deg:+7.1f}°  ->  回读 {got:+7.1f}°{mark}")


def _fmt_read(read) -> str:
    """MotorRead 的字段名各版本略有差异，这里做容错格式化。"""
    for attr in ('pos', 'positions', 'position', 'pos_rad'):
        if hasattr(read, attr):
            arr = np.atleast_1d(np.asarray(getattr(read, attr), dtype=float))
            return f"{np.round(np.rad2deg(arr[:4]), 2)} 度（前 4 个）"
    return repr(read)[:120]


def demo_motion(client, ids: list[int]) -> None:
    banner("4) 位置下发与回读（弧度进、弧度出）")
    client.set_operating_mode(ids, MODE_POSITION)
    print(f"  set_operating_mode(所有电机, {MODE_POSITION}=位置带电流限制)")
    failed = client.set_torque_enabled(ids, True)
    print(f"  set_torque_enabled(True) -> 未成功的 ID: {failed if failed else '（无）'}")

    low, high = client.position_range_rad
    print(f"  量程 ({np.rad2deg(low):.0f}° ~ {np.rad2deg(high):.0f}°)，故下面只用负角，"
          f"这样能看出「跟踪」而不是「被夹」")
    positions = np.zeros(len(ids), dtype=np.float64)
    for step, deg in enumerate((0.0, -30.0, -90.0, -180.0, 0.0), start=1):
        positions[:] = np.deg2rad(deg)
        client.write_desired_pos(ids, positions)
        read = client.read_position_velocity_current()
        print(f"  第 {step} 步  指令 {deg:+7.1f}°   回读: {_fmt_read(read)}")

    client.set_torque_enabled(ids, False)
    print("  set_torque_enabled(False) —— 调试结束务必失能，真机上这决定手会不会突然攥紧")
    print("  注：mock 的电机「瞬间到位」（read_status_is_done_moving 恒为 True），")
    print("      所以它验证的是指令映射、量程与开关顺序，不含动力学与到位过程。")


def demo_ids(client, ids: list[int]) -> None:
    banner("5) 改电机 ID（真机 bring-up 常做的第一步）")
    old, new = ids[0], max(ids) + 1
    ok = client.change_motor_id(old, new)
    print(f"  change_motor_id({old} -> {new}) = {ok}")
    print(f"  改后 responding_motor_ids: {client.responding_motor_ids()}")


def main() -> int:
    ap = argparse.ArgumentParser(description="伺服层台架（无需硬件）")
    ap.add_argument('--motor', default='feetech', choices=['feetech', 'dynamixel'])
    ap.add_argument('--demo', default='all',
                    choices=['all', 'bus', 'gains', 'limits', 'motion', 'ids'])
    ap.add_argument('--count', type=int, default=17, help='电机数量（默认 17，对应 ORCA 17 DoF）')
    ap.add_argument('--baud', type=int, default=1000000)
    args = ap.parse_args()

    ids = list(range(1, args.count + 1))
    banner(f"伺服层台架  motor={args.motor}  {args.count} 个电机  baud={args.baud}")
    client = make_client(args.motor, ids, args.baud)

    demos = []
    if args.demo in ('all', 'bus'):
        demos.append(('总线扫描与缺号', demo_bus, (client, ids)))
    if args.demo in ('all', 'gains'):
        demos.append(('伺服增益', demo_gains, (client, ids)))
    if args.demo in ('all', 'limits'):
        demos.append(('限位与寄存器截断', demo_limits, (client, args.motor, ids)))
    if args.demo in ('all', 'motion'):
        demos.append(('位置下发与回读', demo_motion, (client, ids)))
    if args.demo == 'ids':
        demos.append(('改电机 ID', demo_ids, (client, ids)))

    # 每个演示独立容错：mock 对某些方法可能没实现（NotImplementedError），
    # 一处不支持不该中断其余部分，否则排查时只能一个个试。
    try:
        for name, fn, fn_args in demos:
            try:
                fn(*fn_args)
            except NotImplementedError as exc:
                print(f"\n  [跳过] {name}：该 mock 未实现（{exc}）")
            except Exception as exc:
                print(f"\n  [失败] {name}：{type(exc).__name__}: {exc}")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

    print()
    print("完成。以上全部在内存中完成，没有打开任何串口、没有接触硬件。")
    return 0


if __name__ == '__main__':
    sys.exit(main())
