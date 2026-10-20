# ORCA 右手打印清单（A1 · Feetech · v2 Base）

> 依据：官方排盘工程 `orca-link/prints/Prints-1100.3mf`（v2 Base，10 盘 / 117 件）。
> 你选定的方案：**打印右手 · 舵机 Feetech · 机型 Bambu Lab A1**。
> 本清单**不改动 3MF 文件**，全部操作在 Bambu Studio 界面里完成（路线 A）。

---

## 一、开工前

- [ ] 用 Bambu Studio 打开 `orca-link/prints/Prints-1100.3mf`（**已验证可正常打开**）
- [ ] 机型切到 **`Bambu Lab A1 0.4 nozzle`**（官方盘是按 **P2S** 排的，P2S 是 CoreXY，A1 是床动式）
- [ ] 切完机型后**让 Studio 重新做一次自动摆放/间距检查** —— 不要沿用原摆位。
      `HullFront`(110mm)、`ForeArmStructure`(91mm)、`CORE-R`(67mm)、`I-PP`(55mm) 都超过
      25mm 的 `extruder_clearance_height_to_rod` 阈值，属受约束的件
- [ ] 准备耗材：**PLA**（主体）+ **TPU**（皮肤件）。**TPU 必须走外置料盘，不能进 AMS**

---

## 二、逐盘操作

| 盘 | 件数 | 官方盘名 | 操作 | 材质 | 官方估时 |
|---|---|---|---|---|---|
| **1** | 3 | BottomTower Toptower **DYNAMIXEL** (13h) | ❌ **整盘删除**（你选 Feetech） | — | — |
| **2** | 3 | BottomTower Toptower **FEETECH** (13h) | ✅ 保留 | PLA | 13h |
| **3** | 64 | Spools + Small Parts (0.2mm)(7h) | ✅ 保留 | PLA | 7h |
| **4** | 10 | Skin (TPU) | ✅ 保留 | **TPU** | — |
| **5** | 2 | Carpals Skin (TPU) (L & R) | ⚠️ **删左手 1 件**，留 1 | **TPU** | — |
| **6** | 4 | Carpals (L & R) (0.16mm)(12h) | ⚠️ **删左手 2 件**，留 2 | PLA | 12h |
| **7** | 19 | Fingertips Touch (L & R)(0.16mm)(9.5h) | ⚠️ **删左手 3 件**，留 16 | PLA | 9.5h |
| **8** | 4 | Plates + Hulls (OH Board) (0.2mm)(4.5h) | ✅ 保留 | PLA | 4.5h |
| **9** | 1 | SidePlate **MULTICOLOR** (0.2mm)(1h) | ✅ 保留 | PLA | 1h |
| **10** | 7 | **CNC parts (FDM can substitute)**(2.5h) | 🤔 自行决定 | PLA | 2.5h |

**盘 10 的 7 件含重复**（已核对 `model_settings.config`）：`FrankaConnector` ×1、
**`SpoolHolder` ×4**、**`SpoolTensioner` ×2** —— 不是 7 个不同零件。

这 7 件本来是机加工件，盘名直接写了 "FDM can substitute"。但你文档里记过：
**`SpoolHolder` 在 v2.1 已被金属件取代**，仓库同时给了 `04_ForeArm/SpoolHolder.stl`（打印）
与 `06_CNC/SpoolHolder_CNC.step`（机加工）。
→ 走 Feetech + v2 Base 的话建议**先打**，等装配时再决定要不要换成金属件。

---

## 三、要精确删掉的件（共 9 件）

### 盘 1 —— 整盘删（3 件，Dynamixel 方案）
```
ForeArmStructure_Dynamixel_TwoFans.stl
WristAdapter_Dynamixel.stl
WristStructure_Dynamixel.stl
```

### 盘 5 —— 删 1 件（左手皮肤）
```
L-Carpals_Skin_TPU.stl        ← 删
R-Carpals_Skin_TPU.stl        ← 留
```

### 盘 6 —— 删 2 件（左手掌骨）
```
CORE-L.stl                    ← 删
L-Carpals.stl                 ← 删
CORE-R.stl                    ← 留
R-Carpals.stl                 ← 留
```

### 盘 7 —— 删 3 件（左手指尖）
```
I-AP-L.stl                    ← 删
L-T-AP.stl                    ← 删
T-TP-L.stl                    ← 删
I-AP-R.stl / R-T-AP.stl / T-TP-R.stl   ← 留（右手对应件）
```

**删完后的实际件数**：3(盘2) + 64(盘3) + 10(盘4) + 1(盘5) + 2(盘6) + 16(盘7) + 4(盘8) + 1(盘9)
= **101 件**；若盘 10 也打则 **108 件**。

---

## 四、A1 专属注意

- [ ] **喷嘴 0.4**（官方参数全按 0.4 调；用 0.2 既慢又易堵）
- [ ] 官方预设是 `0.16mm High Quality @BBL P2S`，切到 A1 后确认层高/流量跟着变
- [ ] **TPU 分任务打**（盘 4、盘 5），外置料盘，别和 PLA 混在一盘
- [ ] 盘 9 是多色（MULTICOLOR）：有 AMS 就多色，没有就单色打
- [ ] 盘 4/5 是薄片皮肤件，注意首层附着；A1 无辅助风扇，大面积薄件留意翘边

---

## 五、打完怎么核对

- [ ] 右手件齐全：`CORE-R`、`R-Carpals`、`R-Carpals_Skin_TPU`、`I-AP-R`、`R-T-AP`、`T-TP-R`
- [ ] 舵机家族一致：**盘 2 的 Feetech 三件**（`ForeArmStructure_Feetech_TwoFans`、
      `WristAdapter_Feetech`、`WristStructure_Feetech`），**不该出现任何 Dynamixel 件**
- [ ] 掌骨 + 腕 + 前臂 + Hulls + SidePlate + 64 个小件齐套
- [ ] 皮肤件（TPU）数量与盘 4/5 一致

---

## 六、为什么不用「右手专用 3MF」

之前做过一份裁好的 `Prints-1100-right-only.3mf`（111 件、左手件已清零、静态校验全过），
但 **Bambu Studio 加载时报「加载模型文件失败」** —— 文件手术还差一处没对上。
官方原件已验证可正常打开，所以本次走「界面里删件」这条稳妥路线。

> 若日后想修好那份裁切文件，已知线索：它是从官方件移除了 6 个 `<object>`、6 个 `<item>`、
> 12 条 `assemble_item`、6 个 `<model_instance>`、6 个 `cut_information` 条目，并删了 6 个
> 孤立几何文件 `3D/Objects/object_*.model`；静态引用检查全过，但 Studio 仍拒绝加载。
