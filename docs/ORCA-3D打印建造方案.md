# ORCA Hand 3D 打印建造方案

目标：造一只**能被 [`orca-link/`](../orca-link/) 遥操作管线驱动的真手**——也就是我们已经在
MuJoCo 里跑通的那只手的物理版本。

论文口径（[arXiv:2504.04259](https://arxiv.org/abs/2504.04259)，IROS 2025）与官方现行规格：

| 指标 | 论文（v2.0，2025-04） | 官网现行（v2.1，2026） |
|---|---|---|
| 自由度 | **17**（腱驱动，含触觉集成） | 17 |
| 装配时间 | **< 8 小时**（假设零件齐备） | — |
| 材料成本 | **< 2000 CHF** | — |
| 耐久 | **> 10000 次循环 ≈ 20 小时**无故障 | **额定 200,000 次循环** |
| 腱绳接触面 | 无 PTFE（v2.0） | **只接触金属与光滑 PTFE，不碰 PLA** |
| 线轴座/张紧器 | 打印件 | **金属件** |
| 在售价格 | — | base **from $3,500** / touch **from $6,100** |

---

## 0. 先做一个决策：自己造，还是买成品

官方在售两个型号（[orcahand.com](https://www.orcahand.com/) 定价，2026 年查询）：

| 型号 | 配置 | 价格 |
|---|---|---|
| **1100 · orcahand v2.1 base** | 17 DoF，**无**触觉、**无**关节位置传感 | **from $3,500** |
| **2100 · orcahand v2.0 touch** | 17 DoF + **351 个触觉点**（TS） | **from $6,100** |

对照自造：论文口径材料成本 **< 2000 CHF**（≈ $2,300）。

**所以自造省的是大约三分之一到一半的钱，代价是**：数天打印机时 + 采购长尾 + 装配与标定
（官方口径 <8 h，但那是在零件齐备且有装配视频的前提下）+ 公差风险。

- **想要"尽快有一只手做研究"** → 买 1100。$3,500 换掉的是你几周的采购与试错。
- **想要"这只手是我造的"、或预算受限** → 按本方案自造，但务必走 §3 的 Gate 流程。
- **折中**（我推荐）：先按 §3 只打印 + 干装，把公差和零件可获取性摸清，再决定要不要继续。
  打印成本只有几十块耗材，却是唯一能提前暴露风险的动作。

> 仓库里的文件对应的是 **v2.1 / 1100**（3MF 名为 `Prints-1100`，
> `ASSEMBLY_ADDENDUM` 里也按 "V1100" 描述线轴），与在售型号同代。

---

## 1. 先看三个决定可行性的事实

这三点会直接改变你的执行路线，先说清楚再谈步骤。

### ① 仓库里**没有机械 BOM**

`orcahand_hardware` 只有：
- `orca_v2/electronics/ORCA_Motor_Connectors_BOM.xls`（**仅电子件**：电机接线板）
- Gerber 文件 + `How-to-order-PCB.txt`（指向 EasyEDA 下单流程）

**紧固件、销、轴承、PTFE 管、腱绳、弹簧、硅胶——一个清单都没有。**

但官方把 BOM 放在**网站上**，不在仓库里：

- **<https://www.orcahand.com/bill-of-materials>** ← 官方 BOM 页
- **官方 Discord**：<https://discord.gg/xvGyxaccRa> —— 官网原话：
  *"BOM, assembly and the rest live in Discord, with us and other builders. **Not email.**"*

> 这是本方案**最大的执行风险**：不是"能不能打印"，而是"买不齐零件"。
> 先把 `/bill-of-materials` 页和 Discord 里的清单拿到手，再开始采购。

### ② 有 CNC 机加工件

`orca_v2/base/06_CNC/`：`SpoolHolder_CNC.step` 与 `FrankaConnector.step`，各带技术图纸 PDF。

这不是可选项——官网明确写 v2.1 的改进之一就是
**"metal spool holders: Spool holders and tensioners are metal in v2.1, printed in v2.0"**。
也就是说 v2.0 可以打印这些件，**v2.1 用的是金属件**。需要找机加工（铝），
或自行评估用高填充打印件替代（线轴座承力，替代有风险）。

同一条官网说明还提到：**v2.1 里腱绳只接触金属与光滑 PTFE，永不接触 PLA**（v2.0 没有 PTFE）。
PTFE 管在这版里是**功能性必需件**，不是可省的细节。


### ③ 成本几乎全在 17 个舵机

| 家族 | 腕（×1） | 指（×16） |
|---|---|---|
| Dynamixel | XC430-T240BB-T | XC330-T288-T |
| Feetech | HLS3930 | HLS3915 |

两家族价差很大，**选型直接决定预算量级**。3MF 里盘 1（DYNAMIXEL）与盘 2（FEETECH）
只是塔身不同，其余盘通用——所以**选型可以晚于打印决定**。

---

## 2. 变体选型

型号编号与在售目录对应：**1100 = v2.1 base**（本方案首选），**2100 = v2.0 touch**。

| 选项 | 内容 | 对应在售 | 建议 |
|---|---|---|---|
| **v2 Base**（`Prints-1100.3mf`） | 98 个 STL（60 手部 + 38 模具）、已排好盘的 Bambu 3MF | **1100**，17 DoF 无传感 | ✅ **首选**：文档、3MF、装配视频齐全，也是我们软件栈验证过的配置 |
| v2 Touch（`Prints-2100.3mf`） | 指尖加触觉，需额外 Paxini 传感器 + 板子 | **2100**，351 taxels | 后续升级 |
| v2 lite | 只有 23 STL / 18 STEP，**无 3MF、无文档** | 无 | 备选；零件少但等于自己当第一个吃螃蟹的人 |
| joint-sensing | `PrintsJointSensing.3mf` | 无（加装） | 需要关节编码器闭环时再上 |

**推荐起点：v2 Base + motor-only**。原因：我们验证过的软件路径正是 motor-only
（`load_hand(config_path="models/v2/orcahand-right/config.yaml")` → `OrcaHand`），
触觉与关节编码器都是**可后加的升级**，不必一开始就压上。

---

## 3. 阶段 0：先验证，再花钱（最重要的一步）

不要一次买齐 17 个舵机。按这个顺序：

1. **只打印，不买电机**：先打 1 根手指 + 腕骨 + 线轴
2. **干装（dry-fit）**：销、轴承、PTFE 管能不能按图纸压入？
3. 公差过关 → 再打全套 → 再买舵机

理由：FDM 公差是这类腱驱动手最常见的翻车点。销孔小 0.1mm 就要重打 60 个零件，
而这在买完舵机之后才发现会很痛。

---

## 4. 打印

```bash
git clone https://github.com/orcahand/orcahand_hardware.git   # 约 850 MB
```

用 **Bambu Lab Studio** 打开 `orca_v2/base/Prints-1100.3mf`——官方已排好盘并带打印参数。
非 Bambu 机型：从 `01_Fingers` / `02_Carpals` / `03_Wrist` / `04_ForeArm` / `05_Spools` /
`09_Skin` 里取 STL 自己排盘（STEP 源文件同名附带）。

| 部位 | STL 数 | 体积 |
|---|---|---|
| 01_Fingers | 16 | 13.2 MB |
| 02_Carpals | 9 | 35.9 MB |
| 03_Wrist | 7 | 28.9 MB |
| 04_ForeArm | 15 | 3.4 MB |
| 05_Spools | 4 | 1.0 MB |
| 09_Skin | 9 | 6.0 MB |
| 07_Molds（模具，可选） | 38 | 40.9 MB |

材料：结构件 PLA（强度够、尺寸稳）；皮肤两选一——
**TPU 直打（快，3MF 已含 `(TPU)` 盘）** 或 **硅胶浇注（官方推荐：抓握更好、更耐久）**。
硅胶路线要打印模具（`SiliconeMolds-1100.3mf`，其中一块用 ~85A 软 TPU）+ 硅胶 + 脱泡。

---

## 5. 采购清单

**可以现在确定的部分：**

- **舵机 ×17**：16 指 + 1 腕，按 §1③ 选家族
- **驱动/接口**：
  - v2 手自带的 **ORCA controller board** → Windows 上免驱，显示为两个 `USB Serial Device (COMx)`
  - 若用 U2D2（Dynamixel 路线）：还需 Power Hub Board + **12V 电源**
  - Feetech 路线：CH340 或 CP210x 适配器
- **电机接线板 PCB**：用 `electronics/ORCA_Motor_Connectors_Gerber` 走 EasyEDA/JLCPCB 打样
- **PTFE 管**：每指 AP 2 根（宽孔对，长约 8–10 mm，两端各留 ~1 mm）；
  腕骨 **32 根**；塔身 **32 根**
- **销**：拇指 AP 用 **2×30** ×2；腕关节用 **3×50**（3×45 勉强可用）×2
- **轴承**：拇指 AP 用 **4×8×3**；腕轴两端各一个 **8×13×4**
- **M4 螺钉**：塔身用，外面套 PTFE 管

**仍需自行补全的部分**（仓库未列，去装配视频/Discord/官方套件确认）：
腱绳（材质与直径）、弹簧、其余紧固件规格与数量、硅胶型号与硬度。

> 我不在这里编造价格。唯一可靠的总量数字是论文的 <2000 CHF；**舵机选型是最大变量**，
> 其余按 §5 清单逐项询价即可。

---

## 6. 装配顺序

⚠️ 官方装配视频有若干处**已过期**，`orca_v2/base/ASSEMBLY_ADDENDUM.md` 是修正版。
下面把修正合并进来了（时间戳指视频）：

1. **每指 AP 打 PTFE**（视频 7:50）：宽孔对的两个孔各插一根，两端各留 ~1 mm
2. **拇指 AP**（21:04）：新件是**一条长缝**、不是 6 个孔 → 先按视频顺序把腱穿进长缝
   （顺序错了会交叉），再插 2 根 2×30 销，最后上 4×8×3 轴承
3. **腕骨**（25:05）：**32 个通道**各插一根 PTFE；穿腱；把 5 指装到腕骨上
4. **腕关节与齿轮**（31:59）← **视频里缺这一步**：插 2 根 3×50 销；装 3D 打印的腕骨齿轮；
   腕轴两端各装一个 8×13×4 轴承
5. **塔身**（40:50 / 39:50）：**32 个通道**插 PTFE；M4 螺钉套 PTFE 时，
   一手压紧、用螺丝刀把它"拧进"管子，比硬压容易
6. **线轴**（53:30）：**V1100 的线轴是 4 个螺钉孔**，V1000 是 5 个——别混
7. 最难的一步是往细长弯曲通道里塞 PTFE：把一根打了结的腱先穿过 PTFE，
   再用它把管子**拉**进通道，而不是推

---

## 7. 张力与标定（官方流程，必须循环做）

1. `python scripts/tension.py <config.yaml>`
   默认先自动绕紧腱绳 → 锁住舵机 → 固定底部线轴。`--no-move-motors` 可只保持当前位置
2. 用随件打印的**棘轮**，顺时针拧**每个舵机的上线轴**
   拧的时候应该听到/感到**"咔哒"**声——这表示棘轮啮合、正在上张力
3. ⚠️ **极容易过紧**。只拧到腱绳"有张力感"就停，**不是越紧越好**；过紧会直接损害性能
4. `python scripts/calibrate.py <config.yaml>` 跑全套关节标定
5. **重复 2↔4 一到两次**，直到标定结束后**不再出现新的松弛**
   （初次装配因为手工绕线，松弛会很多，标定一开始"看起来没效果"是正常的）
6. `python scripts/measure_travel.py <config.yaml>` 生成这只手**自己的**
   `joint_motor_travel` 基线 —— 每只手的腱路由都不同，**不要抄别人的数字**

---

## 8. 软件接入（我们已有的部分直接可用）

### Windows 首次连接清单

1. `uv run pytest` 通过
2. 插上手：`python -m serial.tools.list_ports -v` 能看到 COM 号，设备管理器无黄色感叹号
   - v2 自带控制板：Windows 免驱，会出**两个** COM 口（电机总线 + 传感链路）
   - **U2D2 用户注意**：设备管理器 → 端口 → 属性 → 端口设置 → 高级 →
     **Latency Timer 改成 1 ms**（这个设置 Windows 上不会自动改，不改的话控制频率上不去）
3. `python scripts/detect.py` 应能自动认出端口和舵机家族（问你要选端口时是数字列表，正常）
4. `python scripts/configure_motor_chain.py <config.yaml>` 配置电机链
5. **端口是独占的**：另一个程序占着 COM 口会直接 `PermissionError`，关掉串口监视器等再试

### 接到我们的遥操作管线

```powershell
# 先用仿真确认输入正常（不碰硬件）
<conda env>\python.exe orca-link\teleop_live.py --drive sim --sim-render human
<conda env>\python.exe orca-link\orca_bridge.py --sink grpc
<conda env>\python.exe orca-link\drive_gestures.py --pattern wave --seconds 0

# 确认无误后换真机
<conda env>\python.exe orca-link\teleop_live.py --drive real
```

`--drive real` 会走真实的 `load_hand()` → `connect()` → `init_joints()`，
再由官方 `pipeline.run()` 把重定向后的关节角下发。**先空载、低电流、小幅度试**。

---

## 9. 时间与预算

| 项目 | 估计 | 依据/不确定性 |
|---|---|---|
| 下载仓库 | 850 MB | 实测 |
| 打印 | 60 个手部零件 + 38 模具 | 单件 1–3 h 视机型 → 数天打印机时（**估算**） |
| **CNC 铝件** | SpoolHolder + FrankaConnector | 需询价；v2.1 的金属线轴座是**必需件** |
| 装配 | **< 8 h** | 论文口径，假设零件齐备 |
| 张力+标定 | 数小时（要循环 2–3 轮） | 官方流程 |
| 材料成本 | **< 2000 CHF** | 论文口径；**舵机选型是最大变量** |
| 对照：买成品 | **$3,500**（base）/ **$6,100**（touch） | 官网定价，2026 年查询 |

> 我**不编造**逐项价格。唯一可靠的两个总量数字是论文的 <2000 CHF 与官网的 $3,500/$6,100；
> 舵机家族选型是最大变量，其余按 §5 清单逐项询价。

---

## 10. 风险与检查点（每个 Gate 不过就别往下走）

| Gate | 检查什么 | 不过怎么办 |
|---|---|---|
| **G1 打印公差** | 销与轴承能按图纸压入（先干装 1 根手指） | 调补偿/换打印机，别买舵机 |
| **G2 零件齐备** | §5 清单全部到位（尤其腱绳与紧固件） | 转向官方套件 |
| **G3 电机链** | 17 个 ID 唯一、波特率一致、`detect.py` 全认出 | 用 `configure_motor_chain.py` 重配 |
| **G4 空载单指** | 单指能跟随小幅度指令 | 查腱路由与张力，别整手穿腱 |
| **G5 标定收敛** | 张力↔标定循环后不再出现新松弛 | 继续循环；仍不收敛查是否过紧/腱绳打滑 |
| **G6 首次整手运动** | 低电流 + 小步长 + 手边有断电手段 | 立即停 |

论文的"<8 小时装配"是在**零件齐备、有装配视频**的前提下。真正的长尾在 §5 的采购和 G1/G2。

---

## 11. 参考

**官方（BOM 与采购问题优先看这里）**

- 官方 BOM 页：<https://www.orcahand.com/bill-of-materials>
- 官方 Discord（BOM/装配问题的官方渠道，官网明确说**不要用邮件**）：<https://discord.gg/xvGyxaccRa>
- 官方 Getting started：<https://www.orcahand.com/getting-started>
- 型号与配置下单：<https://www.orcahand.com/models/full> · <https://www.orcahand.com/shop/configure>

**代码与模型**

- 硬件仓库（3MF/STL/STEP，CC BY 4.0）：<https://github.com/orcahand/orcahand_hardware>
- 控制栈：<https://github.com/orcahand/orca_core> · 遥操作：<https://github.com/orcahand/orca_teleop>
- 论文（IROS 2025）：<https://arxiv.org/abs/2504.04259>
- 装配视频（配合 `ASSEMBLY_ADDENDUM.md` 看）：<https://www.youtube.com/watch?v=TgIz7HiyaoU>
- Windows 连接细节：`orca_core/docs/pages/getting-started-docs/windows.md`
- 张力与标定：`orca_core/docs/pages/getting-started-docs/initial-tensioning-and-calibration.md`

> 授权注意：硬件文件按仓库 README 声明为 **CC BY 4.0**（可商用，需署名；官网页脚单独
> 提到 v1 设计文件为 CC BY 4.0）；`orca_core` / `orcahand_description` 是 MIT；
> **`orca_teleop` 没有 LICENSE 文件**，商用前请自行确认。

