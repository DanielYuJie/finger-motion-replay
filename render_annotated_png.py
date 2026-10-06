"""带标注的等距效果图 → PNG（用 Pillow 绘制，便于校验）"""
import math
from PIL import Image, ImageDraw, ImageFont

S = 46
COS30 = math.cos(math.radians(30))
SIN30 = math.sin(math.radians(30))

def project(x, y, z):
    return (x - z) * COS30 * S, (x + z) * SIN30 * S - y * S

PAL = {
    "grass":    ((122,178,74),(86,138,48),(62,108,34)),
    "dirt":     ((150,116,78),(118,90,58),(92,68,42)),
    "palm":     ((166,166,160),(134,134,138),(104,104,112)),
    "brass":    ((232,190,106),(198,152,66),(158,118,44)),
    "casing":   ((196,150,88),(160,118,62),(124,90,44)),
    "motor":    ((104,116,132),(78,90,104),(58,68,80)),
    "segment":  ((214,194,152),(180,160,122),(142,124,92)),
    "hub":      ((232,216,182),(202,186,152),(162,148,118)),
    "shaft":    ((150,150,158),(116,116,126),(90,90,98)),
    "redstone": ((196,62,46),(156,46,34),(120,36,26)),
    "lever":    ((212,212,212),(170,170,170),(134,134,134)),
}

cubes = []
def add(x, y, z, k, tag=None):
    cubes.append({"x":x,"y":y,"z":z,"k":k,"tag":tag})

for gx in range(-6, 12):
    for gz in range(-8, 18):
        add(gx,-1,gz,"grass"); add(gx,-2,gz,"dirt")

for bx in range(-1, 2):
    for bz in range(-3, 14):
        add(bx,0,bz,"palm","palm" if (bx==0 and bz==5) else None)

FINGERS=[0,3,6,9]
for i,fz in enumerate(FINGERS):
    add(0,0,fz-1,"motor","motor" if i==0 else None)
    add(0,0,fz,"casing","bearing" if i==0 else None)
    add(0,0,fz+1,"hub","hub" if i==0 else None)
    for k in range(1,4):
        add(k,0,fz+1,"brass" if k==3 else "segment",
            "finger" if (i==0 and k==2) else None)

add(-2,0,-2,"motor","thumbmotor")
add(-1,0,-2,"casing","thumbbearing")
add(-1,0,-1,"hub","thumbhub")
for k in range(1,4):
    add(-1,0,-1+k,"segment","thumb" if k==2 else None)

for sz in range(-3,14):
    add(2,0,sz,"shaft","shaft" if sz==6 else None)
for fz in FINGERS:
    add(1,0,fz-1,"brass","gear" if fz==6 else None)
    add(2,0,fz-1,"brass")

for i,fz in enumerate(FINGERS):
    add(3,0,fz-1,"casing")
    add(3,1,fz-1,"lever","lever" if i==0 else None)
add(3,0,12,"redstone","redstone")

cubes.sort(key=lambda c:(c["x"]+c["z"], c["y"]))

allpts=[]
for c in cubes:
    for dx in (0,1):
        for dy in (0,1):
            for dz in (0,1):
                allpts.append(project(c["x"]+dx,c["y"]+dy,c["z"]+dz))
minx=min(p[0] for p in allpts); maxx=max(p[0] for p in allpts)
miny=min(p[1] for p in allpts); maxy=max(p[1] for p in allpts)
PADL,PADR,PADT,PADB = 300, 560, 190, 60
W=int(maxx-minx+PADL+PADR); H=int(maxy-miny+PADT+PADB)
OX=-minx+PADL; OY=-miny+PADT

def sp(x,y,z):
    px,py=project(x,y,z); return px+OX, py+OY

def fpts(x,y,z,w):
    if w=="top": p=[(x,y+1,z),(x+1,y+1,z),(x+1,y+1,z+1),(x,y+1,z+1)]
    elif w=="x": p=[(x+1,y,z),(x+1,y,z+1),(x+1,y+1,z+1),(x+1,y+1,z)]
    else:        p=[(x,y,z+1),(x+1,y,z+1),(x+1,y+1,z+1),(x,y+1,z+1)]
    return [sp(*q) for q in p]

img=Image.new("RGB",(W,H),(13,23,32))
dr=ImageDraw.Draw(img,"RGBA")
for i in range(H):
    t=i/H
    dr.line([(0,i),(W,i)], fill=(int(13+30*(1-t)**2), int(23+44*(1-t)**2), int(32+58*(1-t)**2)))

for c in cubes:
    top,fx,fz_=PAL[c["k"]]
    dr.polygon(fpts(c["x"],c["y"],c["z"],"x"), fill=fx)
    dr.polygon(fpts(c["x"],c["y"],c["z"],"z"), fill=fz_)
    dr.polygon(fpts(c["x"],c["y"],c["z"],"top"), fill=top)
    dr.line(fpts(c["x"],c["y"],c["z"],"top")+[fpts(c["x"],c["y"],c["z"],"top")[0]],
            fill=(0,0,0,40), width=1)

def font(sz, bold=False):
    for name in (["msyhbd.ttc","msyh.ttc"] if bold else ["msyh.ttc","msyhl.ttc"]):
        for base in (r"C:\Windows\Fonts",):
            try: return ImageFont.truetype(f"{base}\\{name}", sz)
            except Exception: pass
    return ImageFont.load_default()

F_BIG=font(40,True); F_SUB=font(23); F_LAB=font(21); F_TAG=font(19,True)

dr.text((60,40), "Minecraft · Create 机械手结构效果图", font=F_BIG, fill=(242,234,216))
dr.text((62,92), "超平坦世界 · 四指 + 拇指 · 轴承轴向 Z · 指节垂直伸出", font=F_SUB, fill=(143,168,184))

anchors={}
for c in cubes:
    if c["tag"]:
        pts=fpts(c["x"],c["y"],c["z"],"top")
        anchors[c["tag"]]=(sum(p[0] for p in pts)/4, sum(p[1] for p in pts)/4)

LAB={
 "palm":("掌板（固定基座）","left"),
 "bearing":("机械轴承 · 轴=Z","left"),
 "hub":("轮毂（落在轴上）","left"),
 "finger":("指节 · 垂直伸出才转","right"),
 "motor":("动力（电机/舵机位）","left"),
 "thumb":("拇指（轴转90°对掌）","left"),
 "shaft":("主轴（贯穿传动）","right"),
 "gear":("齿轮盘（分动）","right"),
 "lever":("拉杆 = 单指开关","right"),
 "redstone":("红石信号","right"),
}

used_left=[]; used_right=[]
def place(cx, cy, side, h=34):
    """避让：同侧标签垂直错开"""
    lst = used_left if side=="left" else used_right
    y = cy - 46
    while any(abs(y-v) < h for v in lst):
        y -= h
    lst.append(y)
    return y

for tag,(text,side) in LAB.items():
    if tag not in anchors: continue
    cx,cy=anchors[tag]
    ey = place(cx,cy,side)
    if side=="left":
        ex = cx - 170; tx = ex - 14; anchor="right"
    else:
        ex = cx + 130; tx = ex + 14; anchor="left"
    dr.line([(cx,cy),(ex,ey)], fill=(224,180,92,210), width=2)
    dr.ellipse([cx-6,cy-6,cx+6,cy+6], fill=(224,180,92))
    dr.ellipse([ex-4,ey-4,ex+4,ey+4], fill=(224,180,92))
    bb=dr.textbbox((0,0),text,font=F_LAB)
    tw=bb[2]-bb[0]; th=bb[3]-bb[1]
    if anchor=="right":
        bx0 = tx-tw-18
    else:
        bx0 = tx-8
    dr.rounded_rectangle([bx0, ey-th/2-11, bx0+tw+26, ey+th/2+11], radius=9,
                         fill=(13,23,32,225), outline=(224,180,92,140), width=1)
    dr.text((bx0+13, ey-th/2-3), text, font=F_LAB, fill=(240,226,196))

img=img.filter(__import__("PIL.ImageFilter",fromlist=["x"]).GaussianBlur(0))
img.save("mc-hand-render.png")
print("尺寸:", img.size, " 方块:", len(cubes), " 标注:", len(anchors))
print("已写入 mc-hand-render.png")
