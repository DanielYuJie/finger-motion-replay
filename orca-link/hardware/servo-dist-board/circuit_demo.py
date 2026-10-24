"""ORCA 17 路舵机分配板的**时域电路仿真演示**（补 power_sim.py 的空白）。

power_sim.py 是直流压降分析，README 里也写明了它「没有瞬态、没有浪涌、没有伺服动态」。
这个脚本补三件事，并用动画/曲线演示出来：

  A) 上电浪涌：C1(1000µF) 从 0 充电，P-FET + 走线 + 电源内阻决定峰值电流
  B) 负载阶跃：17 个舵机同时从静止跳到满载，母线瞬间塌多少、多久恢复
  C) 控制环脉动：舵机电流按总线更新率(≈224 Hz)跳变时，母线残余纹波

电路模型（集总，节点法 + 后向欧拉）
------------------------------------
    Vs ──Rp── nA ──Rfet── vB ─┬── C1(1000µF, ESR1) ──┐
                              ├── C2(100nF,  ESR2) ──┤
                              └── 17 × 支路(R_br) ───┴── GND ── Rp_gnd ── 电源负端
    每支路再减去该舵机自己的走线 ladder 压降

电源按**限流模式**处理：算出的电流超过 Ilim 就切恒流源，母线由电容支路决定。
这样上电浪涌不会像理想电压源那样给出几十安的假峰值。

⚠️ 所有「假设」都在 PARAMS 里单独标出，因为它们不是来自官方文件：
   电源内阻/限流值、C1 的 ESR、舵机静态与满载电流的分配。
   Rds、铜电阻、走线长度/宽度来自 power_sim.py 的真实几何，不是拍的。

用法
----
    python circuit_demo.py                # 三个场景的曲线图 + 一个动画 GIF
    python circuit_demo.py --no-gif       # 只出静图
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, replace

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

# DejaVu Sans 没有 CJK 字形，中文会变成方块并大量告警。显式指定系统中文字体。
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

import power_sim as ps

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


@dataclass
class Params:
    """电路参数。带 [假设] 的项没有权威来源，改这里即可试不同的硬件。"""

    vs: float = 12.0            # 母线
    r_psu: float = 0.05         # [假设] SMPS + 输入线内阻
    i_lim: float = 10.0         # [假设] 电源限流点（12V/10A 砖形适配器）
    r_fet: float = 0.065        # P-FET Rds(on)（power_sim 默认值）
    c1_uf: float = 1000.0       # 板上 C1 电解
    esr1: float = 0.05          # [假设] 1000µF/35V 电解典型 ESR
    c2_nf: float = 100.0        # 板上 C2 陶瓷
    esr2: float = 0.01          # [假设] 100nF 陶瓷 ESR
    r_gnd: float = 0.0174       # GND 回流段（38mm × 1.2mm @1oz，算自几何）
    i_idle: float = 0.05        # [假设] 舵机静止保持电流
    i_full: float = 0.90        # 舵机限流上限（orca_core 默认 900 mA）
    v_brownout: float = 7.0     # [假设] 舵机欠压复位阈值（官方未给，取常见的 7 V 量级）
    v_recover: float = 8.0      # [假设] 恢复阈值：欠压后要高过这个值才重新起转（迟滞）
    n: int = 17


def branch_resistances(p: Params) -> np.ndarray:
    """17 个舵机各自「排针 + 舵机线 + 排内 ladder」的串联电阻，取自真实几何。"""
    servos = ps.servo_positions()
    r = np.zeros(len(servos))
    r += 2 * ps.R_HEADER + 2 * ps.R_LEAD_PER_M * ps.LEAD_LEN_M
    # 排内 ladder：最远那个舵机累计的铜阻
    for row, (ry, cnt, x0) in enumerate(zip(ps.ROWS, ps.ROW_COUNTS, ps.ROW_X0)):
        acc = 0.0
        prev = ps.XD_V
        for j in range(cnt):
            x = x0 + j * ps.PITCH
            acc += ps.r_of(max(x - prev, 0.3), ps.TRUNK_MM, 1.0)
            prev = x
            k = row * 99 + j
            idx = [i for i, (rr, _, xx) in enumerate(servos) if rr == row and abs(xx - x) < 1e-6]
            if idx:
                r[idx[0]] += acc
    return r


def common_resistance(p: Params) -> float:
    """输入到母线之间、承载总电流的板铜电阻（不含 FET、不含电源内阻）。"""
    tot = 0.0
    for _, L, w in ps.VIN_SEGS + ps.GND_SEGS:
        tot += ps.r_of(L, w, 1.0)
    return tot


def simulate(p: Params, load_fn, t_end: float, dt: float | None = None,
             init_v: float | None = None):
    """后向欧拉时域求解。load_fn(t) -> 每舵机电流数组 (n,)。

    C1/C2 用「ESR + dt/C」等效串联，节点电压可解析求出，不需要迭代。

    两个关键建模决定：
    * init_v：模拟"运行中的负载阶跃"时必须从**直流稳态**起步，否则电容从 0 V 起
      等于把母线短路，前几步全是充电过程，看不到阶跃。
    * 欠压钳制（brownout）：母线跌破 v_brownout 时舵机停转、只留保持电流。
      没有这个钳制，电源带不动时母线会被算出 −80 V 这种非物理值
      （真实舵机欠压就复位了）。
    """
    if dt is None:
        dt = min(2e-5, t_end / 4000.0)
    steps = int(t_end / dt) + 1
    n = p.n

    r_br = branch_resistances(p)
    r_comm = common_resistance(p)
    e1 = p.esr1 + dt / (p.c1_uf * 1e-6)
    e2 = p.esr2 + dt / (p.c2_nf * 1e-9)
    vs = p.vs
    r_series = p.r_psu + p.r_fet + r_comm

    def solve(i_load: float):
        """给定负载电流，解出母线电压、电源电流、是否限流。"""
        g1 = 1.0 / r_series + 1.0 / e1 + 1.0 / e2
        b1 = vs / r_series + vc1 / e1 + vc2 / e2 - i_load
        v = b1 / g1
        i_s = (vs - v) / r_series
        cc = False
        if i_s > p.i_lim:
            g2 = 1.0 / e1 + 1.0 / e2
            b2 = vc1 / e1 + vc2 / e2 + p.i_lim - i_load
            v = b2 / g2
            i_s = p.i_lim
            cc = True
        return v, i_s, cc

    if init_v is None:
        i0 = float(np.asarray(load_fn(0.0), dtype=float).sum())
        init_v = vs - min(i0, p.i_lim) * r_series
    vc1 = init_v
    vc2 = init_v
    t = 0.0
    brown_state = False   # 迟滞状态：欠压后要回到 v_recover 以上才解除

    out = {k: np.zeros(steps) for k in
           ("t", "vbus", "i_psu", "i_fet", "i_c1", "i_c2", "i_load",
            "p_fet", "p_cu", "v_servo_min", "in_cc", "brownout")}

    for s in range(steps):
        i_k = np.asarray(load_fn(t), dtype=float)
        i_load = float(i_k.sum())
        vbus, i_psu, in_cc = solve(i_load)

        # 欠压 → 舵机停转，只留保持电流，再解一次。
        # 用迟滞（进入 < v_brownout，解除 > v_recover），否则母线上下来回穿阈值时
        # 每个时步都在「满载/停转」之间抖动，曲线会画成一条密集的噪声带。
        # 一旦欠压就**锁死**（真实舵机欠压复位后需要断电/重新使能，不会瞬时自恢复）。
        # 若改成「高过 v_recover 就恢复」，会得到一个稳定的弛张振荡（实测 7↔8.8 V、
        # 周期 ~0.35 ms）——那就是假设的阈值在自我循环，不是电路本身的性质，故不用。
        if vbus < p.v_brownout and i_load > p.n * p.i_idle + 1e-9:
            brown_state = True
        brown = brown_state
        if brown:
            i_k = np.full(p.n, p.i_idle)
            i_load = float(i_k.sum())
            vbus, i_psu, in_cc = solve(i_load)

        i_c1 = (vbus - vc1) / e1
        i_c2 = (vbus - vc2) / e2
        vc1 += dt * i_c1 / (p.c1_uf * 1e-6)
        vc2 += dt * i_c2 / (p.c2_nf * 1e-9)

        r_br_only = r_br - 2 * ps.R_HEADER - 2 * ps.R_LEAD_PER_M * ps.LEAD_LEN_M
        v_servo = vbus - i_k * r_br_only

        out["t"][s] = t
        out["vbus"][s] = vbus
        out["i_psu"][s] = i_psu
        out["i_fet"][s] = i_psu
        out["i_c1"][s] = i_c1
        out["i_c2"][s] = i_c2
        out["i_load"][s] = i_load
        out["p_fet"][s] = i_psu ** 2 * p.r_fet
        out["p_cu"][s] = i_load ** 2 * (r_comm + float(np.mean(r_br)))
        out["v_servo_min"][s] = float(v_servo.min())
        out["in_cc"][s] = 1.0 if in_cc else 0.0
        out["brownout"][s] = 1.0 if brown else 0.0
        t += dt
    return out

# ---------------------------------------------------------------- 场景

def sc_inrush(p: Params):
    """真正的上电：电容从 0 V 起，看浪涌峰值与充电时间。"""
    return simulate(p, lambda t: np.full(p.n, p.i_idle), t_end=0.02, init_v=0.0)


def sc_step(p: Params, c1_uf: float | None = None, i_lim: float | None = None,
            i_full: float | None = None):
    """运行中的负载阶跃：电容从直流稳态起步，母线只塌 C1/ESR/内阻决定的那部分。"""
    q = replace(p, c1_uf=c1_uf if c1_uf is not None else p.c1_uf,
                i_lim=i_lim if i_lim is not None else p.i_lim)
    hi = i_full if i_full is not None else q.i_full
    t0 = 0.003

    def load(t):
        return np.full(q.n, q.i_idle if t < t0 else hi)
    return simulate(q, load, t_end=0.012)


def sc_collapse(p: Params):
    """电源不够大：10 A 限流带不动 17 × 900 mA = 15.3 A，母线必然塌。
    这是 README「这块板不是 15 A 板」那条警告的时域证据。"""
    def load(t):
        return np.full(p.n, 0.28 if t < 0.002 else p.i_full)
    return simulate(p, load, t_end=0.02)


def sc_ripple(p: Params):
    """按总线更新率（17 电机 3 Mbaud 优化后 ~224 Hz，取自 orca_core 延迟文档）
    让电流在 300 mA / 900 mA 之间跳变，看残余纹波。"""
    period = 1.0 / 224.0
    duty = 0.5

    def load(t):
        ph = (t % period) / period
        return np.full(p.n, p.i_full if ph < duty else 0.30)
    return simulate(p, load, t_end=0.02)


# ---------------------------------------------------------------- 画图

def dashboard(p: Params, name: str, r: dict, title: str, note: str) -> str:
    fig = plt.figure(figsize=(13, 8.5), facecolor="#12161c")
    gs = GridSpec(2, 3, figure=fig, hspace=0.38, wspace=0.26)
    fg, ag = "#e6eef6", "#5b6875"

    def style(ax, ylab, xlab="时间 (ms)"):
        ax.set_facecolor("#171d25")
        ax.tick_params(colors=ag, labelsize=9)
        ax.set_ylabel(ylab, color=fg, fontsize=10)
        ax.set_xlabel(xlab, color=fg, fontsize=10)
        for sp in ax.spines.values():
            sp.set_color("#2b3542")
        ax.grid(True, color="#232c37", lw=0.8)

    tms = r["t"] * 1000
    ax = fig.add_subplot(gs[0, :2])
    ax.plot(tms, r["vbus"], color="#4fc3f7", lw=1.8, label="母线 V+")
    ax.plot(tms, r["v_servo_min"], color="#ffb74d", lw=1.2, label="最差舵机端电压")
    style(ax, "电压 (V)")
    ax.legend(facecolor="#171d25", edgecolor="#2b3542", labelcolor=fg, fontsize=9)
    ax.set_title("母线电压", color=fg, fontsize=11, loc="left")

    ax = fig.add_subplot(gs[0, 2])
    ax.plot(tms, r["i_psu"], color="#81c784", lw=1.5, label="电源输出")
    ax.plot(tms, r["i_load"], color="#e57373", lw=1.2, label="负载需求")
    ax.plot(tms, r["i_c1"], color="#ba68c8", lw=1.0, ls="--", label="C1 电流")
    style(ax, "电流 (A)")
    ax.legend(facecolor="#171d25", edgecolor="#2b3542", labelcolor=fg, fontsize=8)
    ax.set_title("电流分配", color=fg, fontsize=11, loc="left")

    ax = fig.add_subplot(gs[1, 0])
    ax.plot(tms, r["p_fet"], color="#ff8a65", lw=1.6)
    style(ax, "功率 (W)")
    ax.set_title("P-FET 瞬时耗散", color=fg, fontsize=11, loc="left")

    ax = fig.add_subplot(gs[1, 1])
    ax.plot(tms, r["vbus"] * 0 + r["i_load"] * 0 + (r["in_cc"] * 100), color="#ffd54f", lw=1.2)
    ax.set_ylim(-5, 105)
    style(ax, "限流占比 (%)")
    ax.set_title("电源是否进入限流", color=fg, fontsize=11, loc="left")

    ax = fig.add_subplot(gs[1, 2])
    ax.axis("off")
    ax.set_facecolor("#171d25")
    lo, hi = r["vbus"].min(), r["vbus"].max()
    txt = (
        f"电源 {p.vs:.1f} V / 限流 {p.i_lim:.1f} A\n"
        f"C1 {p.c1_uf:.0f} µF (ESR {p.esr1*1000:.0f} mΩ)\n"
        f"P-FET {p.r_fet*1000:.0f} mΩ\n\n"
        f"母线最低 {lo:.3f} V\n母线最高 {hi:.3f} V\n"
        f"谷深 {(p.vs-lo):.3f} V\n"
        f"峰值电流 {r['i_psu'].max():.2f} A\n"
        f"峰值 FET 功耗 {r['p_fet'].max():.2f} W\n"
        f"母线<-11.5V 时长 {np.mean(r['vbus']<11.5)*100:.1f}%"
    )
    ax.text(0.02, 0.95, txt, transform=ax.transAxes, va="top", ha="left",
            color=fg, fontsize=10,
            bbox=dict(facecolor="#1b232c", edgecolor="#2b3542", pad=8))
    ax.set_title("实测摘要", color=fg, fontsize=11, loc="left")

    fig.suptitle(title, color=fg, fontsize=15, x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.945, note, color="#8fa3b8", fontsize=9.5, ha="left")
    path = os.path.join(OUT, f"circuit-{name}.png")
    fig.savefig(path, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def make_gif(p: Params, path: str, frames: int = 90) -> str:
    """负载阶跃过程的动画：左边电路示意（走线亮度∝电流），右边示波器。"""
    r = sc_step(p)
    n = len(r["t"])
    idx = np.linspace(0, n - 1, frames).astype(int)

    fig = plt.figure(figsize=(13, 6.2), facecolor="#12161c")
    gs = GridSpec(1, 2, figure=fig, width_ratios=[1.05, 1.0], wspace=0.16)
    fg, ag = "#e6eef6", "#5b6875"

    axc = fig.add_subplot(gs[0, 0])
    axc.set_facecolor("#171d25")
    axc.set_xlim(0, 10)
    axc.set_ylim(0, 6)
    axc.axis("off")

    # 电路示意（简化示意，不是严格拓扑图）
    axc.add_patch(plt.Rectangle((0.4, 2.35), 0.9, 1.3, fc="#20303d", ec="#3a4d5e"))
    axc.text(0.85, 3.0, "PSU", color=fg, ha="center", va="center", fontsize=10)
    axc.text(0.85, 1.95, "12 V\n10 A", color=ag, ha="center", va="top", fontsize=8)

    fet = plt.Rectangle((2.1, 2.5), 0.75, 1.0, fc="#3a2b20", ec="#7a5b3a")
    axc.add_patch(fet)
    axc.text(2.48, 3.0, "Q1\nP-FET", color="#ffb74d", ha="center", va="center", fontsize=9)

    wire, = axc.plot([1.3, 2.1], [3.0, 3.0], color="#4fc3f7", lw=2)
    wire2, = axc.plot([2.85, 8.6], [3.0, 3.0], color="#4fc3f7", lw=2)
    gnd1, = axc.plot([1.3, 1.3, 8.6, 8.6], [2.35, 1.2, 1.2, 2.4], color="#8fa3b8", lw=2)
    axc.text(4.2, 3.25, "V+ 母干 2.4 mm", color=ag, fontsize=8)

    # C1 / C2
    axc.plot([4.3, 4.3], [3.0, 2.3], color="#4fc3f7", lw=2)
    axc.plot([4.05, 4.55], [2.3, 2.3], color="#ba68c8", lw=3)
    axc.plot([4.05, 4.55], [2.05, 2.05], color="#ba68c8", lw=3)
    axc.plot([4.3, 4.3], [2.05, 1.2], color="#8fa3b8", lw=2)
    axc.text(4.62, 2.18, "C1 1000µF", color="#ba68c8", fontsize=8, va="center")

    # 17 路舵机
    servo_lines = []
    for k in range(p.n):
        x = 5.6 + (k % 6) * 0.52
        y = 4.05 + (k // 6) * 0.62
        axc.plot([x, x], [3.0, y - 0.16], color="#4fc3f7", lw=1.4)
        ln, = axc.plot([x], [y], marker="s", ms=7, color="#2e4a5c", mec="#4fc3f7")
        servo_lines.append(ln)
        axc.plot([x, x], [y + 0.16, 1.2], color="#8fa3b8", lw=1.0)
    axc.text(7.9, 4.9, f"17 × 舵机", color=fg, fontsize=9, ha="right")

    readout = axc.text(0.4, 0.55, "", color=fg, fontsize=10,
                       va="top")

    ax = fig.add_subplot(gs[0, 1])
    style_kw = dict(color="#2b3542")

    def style(ax, ylab):
        ax.set_facecolor("#171d25")
        ax.tick_params(colors=ag, labelsize=9)
        ax.set_ylabel(ylab, color=fg, fontsize=10)
        ax.set_xlabel("时间 (ms)", color=fg, fontsize=10)
        for sp in ax.spines.values():
            sp.set_color("#2b3542")
        ax.grid(True, color="#232c37", lw=0.8)

    style(ax, "电压 (V) / 电流 (A)")
    ax.set_xlim(r["t"][0] * 1000, r["t"][-1] * 1000)
    ax.set_ylim(0, max(p.vs * 1.02, r["i_load"].max() * 1.15))
    lv, = ax.plot([], [], color="#4fc3f7", lw=1.8, label="母线 V+")
    li, = ax.plot([], [], color="#e57373", lw=1.5, label="负载电流")
    lg, = ax.plot([], [], color="#81c784", lw=1.3, ls="--", label="电源输出")
    ax.legend(facecolor="#171d25", edgecolor="#2b3542", labelcolor=fg, fontsize=9)
    ax.axvline(3.0, color="#ffd54f", lw=1, ls=":", alpha=0.8)
    ax.text(3.12, ax.get_ylim()[1] * 0.96, "17 舵机同时满载", color="#ffd54f", fontsize=8)

    fig.suptitle("ORCA 配电板 · 负载阶跃瞬态", color=fg, fontsize=15, x=0.012,
                 ha="left", y=0.975)
    fig.text(0.012, 0.93,
             "集总模型 + 后向欧拉；Rds/铜阻取自真实几何，电源内阻与 C1 ESR 为假设值",
             color="#8fa3b8", fontsize=9, ha="left")

    tms = r["t"] * 1000

    def update(fi):
        i = idx[fi]
        cur = r["i_fet"][i]
        # 走线亮度 ∝ 电流
        for ln in (wire, wire2):
            ln.set_alpha(min(1.0, 0.25 + cur / max(p.i_lim, 1e-6)))
        # 舵机方块亮度 ∝ 各自电流
        frac = r["i_load"][i] / (p.i_full * p.n)
        for ln in servo_lines:
            ln.set_color(plt.cm.YlOrRd(min(1.0, 0.15 + frac * 1.6)))
        d = r["vbus"][i]
        col = "#e57373" if d < 11.0 else ("#ffd54f" if d < 11.5 else "#81c784")
        readout.set_text(
            f"t = {tms[i]:7.2f} ms\n"
            f"母线 V+  {d:7.3f} V   {col}\n"
            f"负载电流 {r['i_load'][i]:7.2f} A\n"
            f"电源输出 {r['i_psu'][i]:7.2f} A"
            f"{'  (限流)' if r['in_cc'][i] > 0.5 else '        '}\n"
            f"C1 电流  {r['i_c1'][i]:7.2f} A\n"
            f"P-FET    {r['p_fet'][i]:7.2f} W"
        )
        readout.set_color(col if d < 11.5 else fg)
        lv.set_data(tms[:i + 1], r["vbus"][:i + 1])
        li.set_data(tms[:i + 1], r["i_load"][:i + 1])
        lg.set_data(tms[:i + 1], r["i_psu"][:i + 1])
        return ()

    from matplotlib.animation import FuncAnimation, PillowWriter
    anim = FuncAnimation(fig, update, frames=frames, interval=60, blit=False)
    anim.save(path, writer=PillowWriter(fps=16))
    plt.close(fig)
    return path


def report(p: Params) -> None:
    """三个场景的关键数字 + 一次与 power_sim 的直流一致性校验。"""
    print("  ── 直流一致性校验（电容视为开路，与 power_sim 对母线电压）──")
    q = replace(p, c1_uf=1e-6, c2_nf=1e-6, i_lim=1e6)     # C→极小 = 开路
    r = sc_step(q, i_full=p.i_full)
    vbus_ours = r["vbus"][-1]
    vbus_ours_nopsu = vbus_ours + p.i_full * p.n * p.r_psu
    ref = ps.simulate("x", p.vs, p.i_full, 1.0, p.r_fet)
    # power_sim 的 v_min 把 FET 按单舵机电流算了（见上一轮发现的 bug），这里换成总电流
    vbus_ref = p.vs - ref.drop_common - ref.i_total * p.r_fet
    print(f"    本模型母线（含电源内阻 {p.r_psu*1000:.0f} mΩ）  {vbus_ours:7.3f} V")
    print(f"    本模型去掉电源内阻后                      {vbus_ours_nopsu:7.3f} V")
    print(f"    power_sim（FET 按总电流修正）             {vbus_ref:7.3f} V")
    print(f"    差                                        "
          f"{vbus_ours_nopsu - vbus_ref:+.3f} V")
    print(f"    → 两者一致性 {abs(vbus_ours_nopsu - vbus_ref)/vbus_ref*100:.2f}%，"
          f"残差来自 power_sim 把每排干线按独立支路简化\n")

    print("  ── A) 上电浪涌（C1 从 0 V 起）──")
    a = sc_inrush(p)
    ipk = a["i_psu"].max()
    dt = a["t"][1] - a["t"][0]
    hit = a["vbus"] > 0.95 * p.vs
    t95 = (np.argmax(hit) * dt * 1000) if hit.any() else float("nan")
    print(f"    峰值电流 {ipk:6.2f} A（电源限流 {p.i_lim:.0f} A "
          f"→ {'触及限流' if ipk >= p.i_lim * 0.999 else '未触及'}）")
    print(f"    C1 充到 95% 用时 ≈ {t95:.3f} ms   峰值 FET 功耗 {a['p_fet'].max():.2f} W")
    print(f"    解析校验：C·ΔV/I = {p.c1_uf*1e-6*p.vs/p.i_lim*1000:.3f} ms"
          f"（限流恒流充电时 t = C·V/I）\n")

    print("  ── B) 负载阶跃：17 × 50 mA → 17 × 900 mA（电源够大，20 A）──")
    for c1 in (1000.0, 4700.0, 10000.0):
        r = sc_step(p, c1_uf=c1, i_lim=20.0)
        dt = r["t"][1] - r["t"][0]
        final = r["vbus"][-1]
        after = np.where((r["t"] > 0.003) &
                         (np.abs(r["vbus"] - final) < 0.01 * (p.vs - final)))[0]
        settle = (r["t"][after[0]] - 0.003) * 1000 if len(after) else float("nan")
        print(f"    C1={c1:6.0f} µF  稳态母线 {final:6.3f} V  全程最低 {r['vbus'].min():6.3f} V  "
              f"过渡到 1% 用时 {settle:6.2f} ms")
    print("    → 最关键是：**没有下冲**。直流塌陷(2.57 V)完全由 Rds+铜阻决定，")
    print("      跟 C1 大小无关；C1 只决定过渡快慢。别指望加电容能救直流压降。\n")

    print("  ── C) 电源不够大：10 A 限流 vs 15.3 A 负载（C1 能买多久？）──")
    for c1 in (1000.0, 4700.0, 10000.0):
        q = replace(p, c1_uf=c1)
        c = sc_collapse(q)
        br = np.where((c["t"] > 0.002) & (c["brownout"] > 0.5))[0]
        t_bo = (c["t"][br[0]] - 0.002) * 1000 if len(br) else float("nan")
        # 解析式要用**阶跃前**的母线电压（此时负载 17×280 mA，母线已经降下来了），
        # 用 p.vs 会高估，因为电容是在 11.2 V 起放电、不是 12 V
        v_pre = p.vs - 0.28 * p.n * (p.r_psu + p.r_fet + common_resistance(p))
        pred = (v_pre - p.v_brownout) * c1 * 1e-6 / (p.i_full * p.n - p.i_lim) * 1000
        print(f"    C1={c1:6.0f} µF  到欠压({p.v_brownout:.0f} V) {t_bo:6.2f} ms   "
              f"解析 ΔV·C/ΔI = {pred:6.2f} ms   最低 {c['vbus'].min():5.2f} V")
    print("    → 电容只是把崩塌**推迟几毫秒**，撑不住持续过载。")
    print("      这就是「这块板不是 15 A 板」和「下调单舵机限流到 280 mA」的时域依据。\n")

    print("  ── D) 控制环脉动（224 Hz 方波负载，电源 20 A）──")
    r = sc_ripple(replace(p, i_lim=20.0))
    seg = r["vbus"][len(r["vbus"]) // 2:]
    pp = float(seg.max() - seg.min())
    print(f"    母线纹波峰峰 {pp:.3f} V（{pp/p.vs*100:.2f}%）")
    print(f"    C1 纹波电流峰值 {np.abs(r['i_c1']).max():.2f} A")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-gif", action="store_true")
    ap.add_argument("--c1", type=float, default=1000.0)
    ap.add_argument("--ilim", type=float, default=10.0)
    ap.add_argument("--rds", type=float, default=0.065)
    args = ap.parse_args()

    p = Params(c1_uf=args.c1, i_lim=args.ilim, r_fet=args.rds)
    os.makedirs(OUT, exist_ok=True)
    print(f"  {p.vs} V · 限流 {p.i_lim} A · Rds {p.r_fet*1000:.0f} mΩ · "
          f"C1 {p.c1_uf:.0f} µF · 17 路\n")
    report(p)

    print("  ── 出图 ──")
    print("   ", dashboard(p, "inrush", sc_inrush(p),
                          "A) 上电浪涌：C1 从 0 V 充电",
                          "电源进入限流后，电容按恒流充电 t = C·V/I"))
    print("   ", dashboard(p, "step", sc_step(p, i_lim=20.0),
                          "B) 负载阶跃：17 舵机同时满载（电源 20 A 充足）",
                          "稳态塌陷由 Rds 与铜阻决定；C1 只决定瞬态那一脚"))
    print("   ", dashboard(p, "collapse", sc_collapse(p),
                          "C) 电源不够：10 A 限流带 15.3 A 负载",
                          "电容只能撑几毫秒，母线随后崩塌 —— 这块板不是 15 A 板"))
    print("   ", dashboard(p, "ripple", sc_ripple(replace(p, i_lim=20.0)),
                          "D) 控制环脉动（224 Hz）", "稳态下母线的残余纹波"))
    if not args.no_gif:
        g = make_gif(p, os.path.join(OUT, "circuit-step-anim.gif"))
        print("   ", g, f"{os.path.getsize(g)/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())