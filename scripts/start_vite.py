#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理端 vite 启动器（规避 WorkBuddy broker 的 write EPIPE / socket 失效）

两个已踩过的坑：
1. write EPIPE —— WorkBuddy 的 broker-ipc-client 接管子进程 stdout/stderr 转发，
   管道断裂时 vite 以未捕获异常终止。解法：os.setsid 脱离会话 + stdout 直连文件 fd。
2. connect ECONNREFUSED .../broker.sock —— WorkBuddy 的 sandbox center 重启后，
   broker socket 的临时目录会变（如 cbb-IO5WH3 → 新目录），此前启动的 vite 仍持有
   旧路径，重连失败即崩溃。解法：--daemon 守护模式，检测到掉线就自动重拉。

用法：
    python3 scripts/start_vite.py            # 启动（若已在跑则跳过）
    python3 scripts/start_vite.py --status   # 只看状态
    python3 scripts/start_vite.py --daemon   # 守护模式：掉线自动重启（推荐演示用）
    python3 scripts/start_vite.py --stop     # 停掉守护进程与管理端
"""
import os
import socket
import subprocess
import sys
import time
import signal

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
APP = os.path.join(WS, "yshop-drink/yshop-drink-vue3")
LOG = "/tmp/vite_run.log"
CACHE = "/tmp/vite-cache-yshop"
PIDFILE = "/tmp/vite_daemon.pid"
PORT = 3000
SHIM = "/tmp/vite-epipe-shim.cjs"


def port_open(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def lan_ip():
    """返回本机 mDNS 主机名（*.local），IP 无关；拿不到才退回 en0 IP"""
    try:
        r = subprocess.run(["hostname"], capture_output=True, text=True, timeout=10)
        h = r.stdout.strip()
        if h and not h.endswith(".local"):
            h = h + ".local"
        if h and h != ".local":
            return h
    except Exception:
        pass
    try:
        r = subprocess.run(["ipconfig", "getifaddr", "en0"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return ""


def kill_old():
    """停掉占用 3000 的旧进程"""
    try:
        r = subprocess.run(["lsof", "-nP", "-iTCP:%d" % PORT, "-sTCP:LISTEN"],
                           capture_output=True, text=True, timeout=20)
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                try:
                    os.kill(int(parts[1]), signal.SIGKILL)
                    print("  已停止旧 vite (pid %s)" % parts[1])
                except Exception:
                    pass
    except Exception as e:
        print("  停止旧进程时出错:", e)
    time.sleep(2)


def write_shim():
    with open(SHIM, "w", encoding="utf-8") as f:
        f.write(
            "const h=(s)=>{s.on('error',e=>{if(e.code!=='EPIPE')console.error(e)})};"
            "h(process.stdout);h(process.stderr);h(process.stdin);\n"
        )


def current_broker_socket():
    """探测当前【真正有进程在监听】的 broker.sock

    背景：WorkBuddy IDE 重启后，broker 的临时目录会变
    （如 cbb-IO5WH3 → cbb-xQde8O），旧 socket 文件会变成僵尸
    （文件在，但无监听者 → ECONNREFUSED）。IDE 重启前启动的 node 进程
    仍持有旧路径，于是 vite 会以
        Error: connect ECONNREFUSED .../broker.sock
    崩溃。这里每次启动都重新探测，把有效路径注入子进程。
    """
    try:
        r = subprocess.run(["lsof", "-nP"], capture_output=True, text=True, timeout=30)
        for line in r.stdout.splitlines():
            if "broker.sock" in line and "LISTEN" not in line and "unix" in line:
                parts = line.split()
                if parts:
                    p = parts[-1]
                    if p.endswith("/broker.sock"):
                        return p
    except Exception:
        pass
    return os.environ.get("CODEBUDDY_DOCUMENT_IPC_ADDRESS", "")


def clean_env():
    """构造「干净」运行环境，彻底剥离 WorkBuddy broker，避免 vite 子进程加载
    broker-ipc-client 后在 IDE 重启 / socket 变僵尸时以 write EPIPE 崩溃
    （端口 3000 随之消失，管理端演示中断）。
      - 删除所有 CODEBUDDY_* / TOYBOX_* 变量（broker 客户端靠这些变量建立连接）
      - 删除 NODE_OPTIONS 里的 WorkBuddy 预加载
      - 清理 PATH 中的 brokered-bin / safe-bin 包装目录
    """
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("CODEBUDDY_") or k.startswith("TOYBOX_"):
            env.pop(k, None)
    env.pop("NODE_OPTIONS", None)
    env["VITE_SKIP_ESLINT"] = "true"
    env["VITE_CACHE_DIR"] = CACHE
    env["PATH"] = ":".join(
        p for p in env.get("PATH", "").split(":")
        if p and "brokered-bin" not in p and "safe-bin" not in p
    )
    return env


def real_node_bin():
    """优先用真实 node 绝对路径，绕开 brokered-bin/safe-bin 包装（包装层会强制 broker 连接）"""
    candidates = [
        os.environ.get("CODEBUDDY_NODE_BIN", ""),
        "/Users/tristan/.workbuddy/binaries/node/versions/22.22.2-6/bin/node",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return "node"


def spawn_vite():
    """以 setsid 方式启动 vite，stdout/stderr 直连文件 fd，且运行在干净环境里"""
    os.makedirs(CACHE, exist_ok=True)
    write_shim()
    env = clean_env()
    node_bin = real_node_bin()
    fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    proc = subprocess.Popen(
        [node_bin, "--require", SHIM, "node_modules/vite/bin/vite.js",
         "--host", "0.0.0.0", "--port", str(PORT)],
        cwd=APP, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
        env=env, start_new_session=True,
    )
    os.close(fd)
    return proc


def wait_ready(timeout_sec=180):
    for i in range(timeout_sec // 2):
        time.sleep(2)
        if port_open(PORT):
            return True
    return False


def pid_alive(pid):
    """真正判断进程是否存活（避免 PID 文件陈旧导致误判）"""
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def read_daemon_pid():
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        return pid if pid_alive(pid) else None
    except Exception:
        return None


def daemon():
    """守护模式：持续监控 3000 端口，掉线即重拉"""
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    log("守护进程启动 PID=%d，监控端口 %d" % (os.getpid(), PORT))
    last = None
    while True:
        up = port_open(PORT)
        if not up:
            if last != "down":
                log("3000 端口不可用 → 重新拉起 vite")
                kill_old()
                spawn_vite()
                if wait_ready():
                    log("✅ 已恢复（HTTP 200 可用）")
                else:
                    log("⚠️ 启动超时，10 秒后再试")
                    time.sleep(10)
            last = "down"
        else:
            if last != "up":
                log("✅ 3000 端口正常")
            last = "up"
        time.sleep(5)


def log(msg):
    """写守护日志（立即 flush，避免缓冲区滞留）"""
    line = "[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open("/tmp/vite_daemon.log", "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        pass
    try:
        print(line, end="")
    except Exception:
        pass


def stop():
    pid = read_daemon_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print("  已停守护进程 pid=%d" % pid)
        except Exception as e:
            print("  停守护进程失败:", e)
    else:
        print("  守护进程未在运行")
    try:
        os.remove(PIDFILE)
    except Exception:
        pass
    kill_old()


def main():
    if "--status" in sys.argv:
        print("  端口 %d : %s" % (PORT, "在跑" if port_open(PORT) else "未监听"))
        pid = read_daemon_pid()
        print("  守护进程 : %s" % ("pid=%d（在跑）" % pid if pid else "未运行"))
        sock = current_broker_socket()
        print("  broker   : %s" % (sock or "未探测到"))
        return

    if "--stop" in sys.argv:
        stop()
        return

    if "--daemon" in sys.argv:
        # 幂等：已有存活的守护进程则不重复拉起（否则多个守护会互相竞争端口）
        existing = read_daemon_pid()
        if existing:
            print("  ✅ 守护进程已在运行 pid=%d，无需重复启动" % existing)
            print("  端口状态 :", "在跑" if port_open(PORT) else "启动中…")
            return

        # 用独立进程跑守护循环：stdout/stderr 直连文件，避免 fork 继承管道后
        # 父进程退出导致 EPIPE / "lost sys.stderr"
        fd = os.open("/tmp/vite_daemon.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        p = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--daemon-inner"],
            stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
            start_new_session=True,
        )
        os.close(fd)
        time.sleep(2)
        # 二次确认：避免并发调用时启动出多个守护
        cur = read_daemon_pid()
        if cur and cur != p.pid:
            try:
                os.kill(p.pid, signal.SIGTERM)
            except Exception:
                pass
            print("  ✅ 守护进程已存在 pid=%d（本次未重复创建）" % cur)
        else:
            print("  守护进程已启动 PID = %d（日志 /tmp/vite_daemon.log）" % p.pid)
        time.sleep(4)
        print("  端口状态 :", "在跑" if port_open(PORT) else "启动中…")
        return

    if "--daemon-inner" in sys.argv:
        daemon()
        return

    if port_open(PORT):
        print("  ✅ 管理端已在运行，无需重复启动")
        return

    print("  启动管理端 vite（setsid 脱离 broker 输出管道）…")
    kill_old()
    proc = spawn_vite()
    print("  PID = %d，日志 = %s" % (proc.pid, LOG))
    if wait_ready():
        print("  ✅ 已就绪")
    else:
        print("  ❌ 启动超时")
    print("  局域网地址 : http://%s:%d" % (lan_ip() or "<本机IP>", PORT))
    print("  本机地址   : http://127.0.0.1:%d" % PORT)


if __name__ == "__main__":
    main()
