"""把 orca_bridge --sink print 的逐帧输出画成关节轨迹图。

仿真环境（orca_core / orca_sim / mujoco）缺失时，这是「链路是否真的在驱动
17 个关节」的可视证据：横轴为采样帧、纵轴为关节角（度）。

用法：
    # 1) 起桥接并把打印重定向到文件
    python orca_bridge.py --sink print --host 0.0.0.0  > bridge.log 2>&1
    # 2) 驱动一段手势
    python drive_gestures.py --pattern wave --seconds 8 --hz 30
    # 3) 出图（默认输出到脚本同目录的 joint-trajectories.png）
    python plot_joint_trajectories.py bridge.log

只用 Pillow（不依赖 matplotlib），中文用系统 CJK 字体。
"""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("bridge.log")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "joint-trajectories.png"

W, H = 1600, 900
PAD_L, PAD_R, PAD_T, PAD_B = 90, 300, 96, 70


def load_font(size):
    for name in ("msyh.ttc", "msyhl.ttc", "simhei.ttf", "simsun.ttc", "Deng.ttf"):
        p = Path(r"C:\Windows\Fonts") / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()


def parse(path):
    """返回 (关节名列表, 每个关节的序列)。"""
    series, order = {}, []
    pat = re.compile(r"([a-z_]+)=\s*(-?\d+(?:\.\d+)?)")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "wrist=" not in line:
            continue
        pairs = pat.findall(line)
        if not pairs:
            continue
        for k, v in pairs:
            if k not in series:
                series[k] = []
                order.append(k)
            series[k].append(float(v))
    return order, series


def main():
    if not LOG.exists():
        print(f"缺少日志：{LOG}")
        return 1
    order, series = parse(LOG)
    if not order:
        print("日志里没有可解析的帧")
        return 1
    n = min(len(series[k]) for k in order)
    series = {k: v[:n] for k, v in series.items()}
    print(f"关节 {len(order)} 个，采样 {n} 帧")

    # 只给有实际行程的关节画线，其余（外展/腕，策略为保持中立）用灰色虚线示意
    moved = [k for k in order if max(series[k]) - min(series[k]) > 1.0]
    still = [k for k in order if k not in moved]
    print(f"有行程: {len(moved)} -> {', '.join(moved)}")
    print(f"保持中立: {len(still)} -> {', '.join(still)}")

    img = Image.new("RGB", (W, H), (18, 20, 24))
    d = ImageDraw.Draw(img)
    f_title = load_font(26)
    f_lab = load_font(17)
    f_small = load_font(14)

    lo, hi = -20.0, 115.0

    def X(i):
        return PAD_L + (W - PAD_L - PAD_R) * (i / max(1, n - 1))

    def Y(v):
        return PAD_T + (H - PAD_T - PAD_B) * (1 - (v - lo) / (hi - lo))

    # 网格 + 纵轴刻度
    for v in range(-20, 120, 20):
        y = Y(v)
        d.line([(PAD_L, y), (W - PAD_R, y)], fill=(44, 48, 56), width=1)
        d.text((PAD_L - 12, y), str(v), font=f_small, fill=(150, 156, 166), anchor="rm")
    d.text((PAD_L + 2, PAD_T - 24), "关节角 (°)", font=f_small, fill=(150, 156, 166))

    palette = [
        (240, 180, 41), (90, 209, 255), (62, 207, 142), (201, 122, 75),
        (214, 96, 156), (140, 130, 240), (120, 200, 90), (230, 120, 90),
        (110, 190, 210), (200, 200, 110), (170, 110, 220),
    ]

    for idx, k in enumerate(moved):
        col = palette[idx % len(palette)]
        pts = [(X(i), Y(v)) for i, v in enumerate(series[k])]
        d.line(pts, fill=col, width=3)
        lx = W - PAD_R + 14
        ly = PAD_T + 4 + idx * 26
        d.line([(lx, ly), (lx + 26, ly)], fill=col, width=3)
        d.text((lx + 34, ly), k, font=f_small, fill=(214, 220, 230), anchor="lm")

    if still:
        lx = W - PAD_R + 14
        ly = PAD_T + 4 + len(moved) * 26 + 12
        d.text((lx, ly), "保持中立（策略）:", font=f_small, fill=(140, 146, 156))
        # 逐行折行，避免超出右边界被截断
        line, lines = "", []
        for name in still:
            cand = (line + ", " + name) if line else name
            if len(cand) > 26:
                lines.append(line)
                line = name
            else:
                line = cand
        if line:
            lines.append(line)
        for j, s in enumerate(lines):
            d.text((lx, ly + 22 + j * 19), s, font=f_small, fill=(140, 146, 156))

    d.text((PAD_L, 20), "ORCA 17 关节目标轨迹（本机实测）", font=f_title, fill=(238, 240, 244))
    d.text(
        (PAD_L, 58),
        "来源：orca_bridge.py --sink print  ×  drive_gestures.py --pattern wave --seconds 8 --hz 30（240 帧）",
        font=f_small, fill=(150, 156, 166),
    )
    d.text((PAD_L, H - 34), f"采样帧（桥接打印区间，共 {n} 帧）",
           font=f_lab, fill=(190, 196, 206))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"已写出 {OUT}  ({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
