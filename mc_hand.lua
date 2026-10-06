--[[
  mc_hand.lua — CC:Tweaked 机械手控制脚本
  ------------------------------------------------
  轮询本机中继服务读取五指关节角，用红石脉冲驱动
  Create 序列换挡，让机械手跟随真实手部动作。

  前置：
    1) 电脑已安装 CC:Tweaked，且 computercraft-server.toml 里 http.enabled = true
    2) PC 上已运行  python bridge_server.py   (127.0.0.1:8765)
    3) 浏览器打开 capture.html，勾选「推送关节角到 CC:Tweaked」

  接线（每个手指一条红石线，接到对应序列换挡）：
    left   -> 拇指     top    -> 食指
    bottom -> 中指     right  -> 无名指
    front  -> 小指

  序列换挡需要配置成：
    信号 ON  -> 旋转 +STEP_DEG
    信号 OFF -> 旋转 -STEP_DEG
  这样一串脉冲就能推/拉手指。
]]

-- ============ 配置 ============
local BRIDGE   = "http://127.0.0.1:8765/angles"
local STEP_DEG = 15        -- 与序列换挡里配置的角度一致
local MAX_DEG  = 90        -- 单指最大弯曲角
local POLL     = 0.08      -- 轮询间隔（秒）
local DEADBAND = 8         -- 角度差小于此值不动，防抖
local PULSE_ON = 0.06      -- 脉冲高电平时长
local PULSE_OFF= 0.06      -- 脉冲低电平时长
local MAX_PULSE= 3         -- 单次最多补几个脉冲，防止暴走

-- 手指 -> 电脑侧面
local FINGERS = {
  { name = "thumb",  side = "left"   },
  { name = "index",  side = "top"    },
  { name = "middle", side = "bottom" },
  { name = "ring",   side = "right"  },
  { name = "pinky",  side = "front"  },
}

-- ============ 工具 ============
local function log(...)
  print(...)
end

local function clamp(v, lo, hi)
  if v < lo then return lo end
  if v > hi then return hi end
  return v
end

-- 读取一次角度
local function fetchAngles()
  local ok, res = pcall(http.get, BRIDGE, { ["Cache-Control"] = "no-store" })
  if not ok or not res then
    return nil, "http 请求失败"
  end
  local body = res.readAll()
  res.close()
  if not body or #body == 0 then
    return nil, "空响应"
  end
  local data = textutils.unserializeJSON(body)
  if type(data) ~= "table" then
    return nil, "JSON 解析失败"
  end
  return data
end

-- 发 n 个脉冲（n 可为负，负号仅作提示，方向由换挡配置决定）
local function pulse(side, n)
  local step = 1
  for _ = 1, math.abs(n) do
    redstone.setOutput(side, true)
    sleep(PULSE_ON)
    redstone.setOutput(side, false)
    sleep(PULSE_OFF)
  end
end

-- ============ 主程序 ============
local cur = {}    -- 每指当前角度
local tgt = {}    -- 每指目标角度
for _, f in ipairs(FINGERS) do
  cur[f.name] = 0
  tgt[f.name] = 0
end

-- 初始化：先把所有输出拉低
for _, f in ipairs(FINGERS) do
  redstone.setOutput(f.side, false)
end

term.clear()
term.setCursorPos(1, 1)
log("机械手桥接控制")
log("桥接地址: " .. BRIDGE)
log("步进角: " .. STEP_DEG .. " 度")
log("-----------------------------")

local tick = 0
local lostCount = 0

while true do
  local data, err = fetchAngles()
  tick = tick + 1

  if not data then
    lostCount = lostCount + 1
    if lostCount % 25 == 1 then
      print("! " .. tostring(err))
    end
  else
    lostCount = 0
    local hand = data.hand
    local fingers = data.fingers or {}

    -- 手不在画面：慢慢回零（松开）
    for _, f in ipairs(FINGERS) do
      local d = fingers[f.name]
      if hand and d then
        local flex = tonumber(d.flex) or 0
        -- flex 是 0..100 的弯曲程度，映射到 0..MAX_DEG
        tgt[f.name] = clamp(flex / 100 * MAX_DEG, 0, MAX_DEG)
      else
        tgt[f.name] = 0
      end
    end

    -- 依次补脉冲
    for _, f in ipairs(FINGERS) do
      local diff = tgt[f.name] - cur[f.name]
      if math.abs(diff) >= DEADBAND then
        local steps = math.floor(math.abs(diff) / STEP_DEG + 0.5)
        if steps > MAX_PULSE then steps = MAX_PULSE end
        if steps > 0 then
          pulse(f.side, steps)
          -- 方向：diff>0 需要正向脉冲。这里假定换挡按 ON=+ 配置；
          -- 若实际方向相反，把下方 cur 的加减号对调即可。
          if diff > 0 then
            cur[f.name] = cur[f.name] + steps * STEP_DEG
          else
            cur[f.name] = cur[f.name] - steps * STEP_DEG
          end
          cur[f.name] = clamp(cur[f.name], 0, MAX_DEG)
        end
      end
    end

    -- 状态行
    if tick % 5 == 0 then
      term.setCursorPos(1, 5)
      term.clearLine()
      local parts = {}
      for _, f in ipairs(FINGERS) do
        parts[#parts + 1] = string.format("%s:%d>%d",
          f.name:sub(1, 2), math.floor(cur[f.name]), math.floor(tgt[f.name]))
      end
      print(table.concat(parts, "  "))
    end
  end

  sleep(POLL)
end
