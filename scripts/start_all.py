#!/usr/bin/env python3
"""一键启动演示所需全部服务（MySQL → Redis → 后端 → 管理端）"""
import os, socket, subprocess, sys, time

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
TC = WS + "/.toolchain"
MYSQL_HOME = TC + "/mysql/mysql-8.4.11-macos15-x86_64"
REDIS_SRC = TC + "/redis/redis-redis-1a2574c/src"
JDK = TC + "/jdk21/jdk-21.0.13+9/Contents/Home"
VUE = WS + "/yshop-drink/yshop-drink-vue3"
JAR = WS + "/yshop-drink/yshop-drink-boot3/yshop-server/target/yshop-server.jar"

def port_open(p, host="127.0.0.1"):
    s = socket.socket(); s.settimeout(1.5)
    try:
        s.connect((host, p)); return True
    except Exception:
        return False
    finally:
        s.close()

def lan_ip():
    try:
        r = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return ""

def step(t):
    print("\n" + "=" * 66)
    print(" " + t)
    print("=" * 66)

IP = lan_ip()
print("局域网 IP: %s" % (IP or "未取到"))

# ---------- 1. MySQL ----------
step("[1/4] 启动 MySQL 8.4")
if port_open(3306):
    print("✅ 已在运行")
else:
    os.makedirs(TC + "/mysqldata", exist_ok=True)
    p = subprocess.Popen([
        MYSQL_HOME + "/bin/mysqld",
        "--socket=/tmp/mysql-deli.sock",
        "--datadir=" + TC + "/mysqldata",
        "--port=3306",
        "--basedir=" + MYSQL_HOME,
        "--pid-file=/tmp/mysql-deli.pid",
        "--log-error=" + TC + "/mysqldata/error.log",
        "--bind-address=0.0.0.0",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        time.sleep(1.5)
        if port_open(3306):
            break
    print("%s MySQL PID=%d" % ("✅ 已启动" if port_open(3306) else "❌ 启动失败", p.pid))

r = subprocess.run([MYSQL_HOME + "/bin/mysql", "--socket=/tmp/mysql-deli.sock", "-u", "root",
                    "-proot", "-D", "yixiang-drink-open", "--default-character-set=utf8mb4",
                    "-N", "-e", "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='yixiang-drink-open';"],
                   capture_output=True, text=True, timeout=30)
tbl = [l for l in r.stdout.splitlines() if l.strip().isdigit()]
print("   表数: %s（期望 94）" % (tbl[0] if tbl else "查询失败"))

# ---------- 2. Redis ----------
step("[2/4] 启动 Redis 8.10")
if port_open(6379):
    print("✅ 已在运行")
else:
    os.makedirs(TC + "/redisdata", exist_ok=True)
    p = subprocess.Popen([REDIS_SRC + "/redis-server", "--port", "6379", "--daemonize", "no",
                           "--dir", TC + "/redisdata", "--appendonly", "yes"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(20):
        time.sleep(1)
        if port_open(6379):
            break
    print("%s Redis PID=%d" % ("✅ 已启动" if port_open(6379) else "❌ 启动失败", p.pid))

# ---------- 3. 后端 ----------
step("[3/4] 启动后端 Spring Boot 48081")
if port_open(48081):
    print("✅ 已在运行")
else:
    if not os.path.exists(JAR):
        print("❌ jar 不存在: %s" % JAR)
        print("   请先执行：cd %s/yshop-drink/yshop-drink-boot3 && mvn -B clean install package -Dmaven.test.skip=true" % WS)
        sys.exit(1)
    env = dict(os.environ, JAVA_HOME=JDK)
    logf = open(TC + "/backend_run.log", "wb")
    p = subprocess.Popen([JDK + "/bin/java", "-Xms512m", "-Xmx2g", "-jar", JAR,
                          "--spring.profiles.active=local", "--server.port=48081"],
                         stdout=logf, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    print("   启动中 PID=%d，日志: %s/backend_run.log" % (p.pid, TC))
    up = False
    for _ in range(90):
        time.sleep(2)
        if port_open(48081):
            up = True
            break
        try:
            t = open(TC + "/backend_run.log", encoding="utf-8", errors="ignore").read()
            if "APPLICATION FAILED TO START" in t:
                break
        except Exception:
            pass
    print("%s 后端" % ("✅ 已启动" if up else "❌ 启动失败"))

if port_open(48081):
    r = subprocess.run(["curl", "-s", "--noproxy", "*", "-m", "15",
                        "http://127.0.0.1:48081/actuator/health"], capture_output=True, text=True, timeout=30)
    print("   健康检查: %s" % r.stdout.strip()[:80])
    if IP:
        r = subprocess.run(["curl", "-s", "--noproxy", "*", "-m", "15",
                            "http://%s:48081/actuator/health" % IP], capture_output=True, text=True, timeout=30)
        print("   局域网(%s): %s" % (IP, r.stdout.strip()[:80]))

# ---------- 4. 管理端 ----------
step("[4/4] 启动管理端 Vite 3000")
if port_open(3000):
    print("✅ 已在运行")
else:
    if not os.path.isdir(VUE + "/node_modules"):
        print("❌ node_modules 缺失，请先执行：")
        print("   cd %s/yshop-drink/yshop-drink-vue3" % WS)
        print("   node %s/pnpm/package/bin/pnpm.cjs install --frozen-lockfile --store-dir %s/pnpm-store --registry=https://registry.npmmirror.com" % (TC, TC))
        sys.exit(1)
    env = dict(os.environ, VITE_SKIP_ESLINT="true")
    logf = open(TC + "/vite_run.log", "wb")
    # stdin 必须接 DEVNULL：vite 会监听 stdin 做「按 h 显示帮助」的交互，
    # 若 stdin 断开会抛 read EIO 直接崩溃（本机实测踩过）
    p = subprocess.Popen(["node", "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", "3000"],
                         cwd=VUE, stdout=logf, stderr=subprocess.STDOUT, env=env,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    print("   启动中 PID=%d，日志: %s/vite_run.log" % (p.pid, TC))
    print("   ⏳ 注意：首次启动加载 14 个 vite 插件，本机实测需 2~3 分钟")
    up = False
    for _ in range(150):
        time.sleep(2)
        if port_open(3000):
            up = True
            break
        try:
            t = open(TC + "/vite_run.log", encoding="utf-8", errors="ignore").read()
            if "error when starting dev server" in t:
                break
        except Exception:
            pass
    print("%s 管理端" % ("✅ 已启动" if up else "❌ 启动失败"))

# ---------- 汇总 ----------
step("启动汇总")
for name, p_ in [("MySQL", 3306), ("Redis", 6379), ("后端", 48081), ("管理端", 3000)]:
    print("  %s %-8s :%d" % ("✅" if port_open(p_) else "❌", name, p_))
if IP:
    print("")
    print("  局域网访问地址：")
    print("    后端   http://%s:48081" % IP)
    print("    管理端 http://%s:3000" % IP)
    print("    小程序 API http://%s:48081/app-api" % IP)
print("")
print("  下一步：python3 %s/demo_check.py  # 演示前自检" % TC)
