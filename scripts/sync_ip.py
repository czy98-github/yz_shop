#!/usr/bin/env python3
"""演示 IP 同步：把本机最新局域网 IP 写入小程序端与管理端配置"""
import os, re, shutil, subprocess, time, sys

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
CFG = WS + "/yshop-drink/yshop-drink-uniapp-vue3/config/index.js"
ENVF = WS + "/yshop-drink/yshop-drink-vue3/.env.dev"

print("=" * 66)
print(" 特色菜订餐小程序 · 演示 IP 同步")
print("=" * 66)

# 1) 取本机 mDNS 主机名（*.local）——IP 无关，换网络 / 换 IP 都不用改
#    优先用 `hostname`（macOS 默认返回 xxx.local）；拿不到再退回 en0 的 IP 兜底。
HOST = ""
try:
    r = subprocess.run(["hostname"], capture_output=True, text=True, timeout=10)
    HOST = r.stdout.strip()
except Exception:
    pass
if HOST and not HOST.endswith(".local"):
    HOST = HOST + ".local"
if not HOST or HOST == ".local":
    try:
        r = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=10)
        HOST = r.stdout.strip()
    except Exception:
        pass
if not HOST:
    print("❌ 未取到本机主机名 / 局域网 IP"); sys.exit(1)

print("本机演示地址（mDNS，IP 无关）: %s" % HOST)
print("")

# 2) 备份
for f in (CFG, ENVF):
    if os.path.exists(f):
        shutil.copy2(f, "%s.bak.%s" % (f, time.strftime("%H%M%S")))

# 3) 小程序端：把 LAN_API_URL 的主机部分替换为 .local 主机名（IP 无关）
if os.path.exists(CFG):
    s = open(CFG, encoding="utf-8").read()
    s2 = re.sub(r"http://[^'\"\s]+:48081/app-api",
                "http://%s:48081/app-api" % HOST, s)
    if s2 != s:
        open(CFG, "w", encoding="utf-8").write(s2)
        print("✅ 小程序端 config/index.js 已更新为 %s" % HOST)
    else:
        print("✅ 小程序端 config/index.js 已是最新（%s）" % HOST)
    for line in s2.splitlines():
        if "LAN_API_URL =" in line:
            print("     %s" % line.strip())

# 4) 管理端：如 .env.dev 仍为「直连后端」写法则同步主机名（默认走 vite 代理，通常为空值，此处兼容保留）
if os.path.exists(ENVF):
    s = open(ENVF, encoding="utf-8").read()
    s2 = re.sub(r"VITE_BASE_URL='http://[^']+:48081'",
                "VITE_BASE_URL='http://%s:48081'" % HOST, s)
    s2 = re.sub(r"VITE_UPLOAD_URL='http://[^']+:48081/admin-api/infra/file/upload'",
                "VITE_UPLOAD_URL='http://%s:48081/admin-api/infra/file/upload'" % HOST, s2)
    if s2 != s:
        open(ENVF, "w", encoding="utf-8").write(s2)
        print("✅ 管理端 .env.dev 已更新为 %s" % HOST)
    for line in s2.splitlines():
        if line.startswith("VITE_BASE_URL=") or line.startswith("VITE_UPLOAD_URL="):
            print("     %s" % line.strip())

print("")
print("=" * 66)
print(" 后端地址（无需改动，后端监听 0.0.0.0，.local 即本机当前 IP）")
print("   http://%s:48081" % HOST)
print("   健康检查: curl -s http://%s:48081/actuator/health" % HOST)
print("")
print(" 管理端访问地址（vite 已 --host 0.0.0.0，局域网经代理转发，IP 无关）")
print("   http://%s:3000    （需先启动 vite）" % HOST)
print("   http://127.0.0.1:3000  （本机直连）")
print("")
print(" ⚠️ 改完配置后必须重启：")
print("   1) 管理端：Ctrl+C 停掉 vite，再重新启动（env 变更不热更新）")
print("   2) 小程序端：HBuilderX 里重新运行到微信开发者工具 / 真机预览")
print("=" * 66)
