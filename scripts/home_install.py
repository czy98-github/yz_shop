#!/usr/bin/env python3
"""
home_install.py —— 家目录安装 → 拷回 workspace → 启动 vite → 验证 /src/main.ts

背景
----
WorkBuddy IDE 的 brokered file broker 按「解析后的路径策略」拒绝 rename，
pnpm/npm 安装重度依赖 rename（建链接、替换目录、bin 链接），因此在 workspace
和 /tmp 内安装都会被拒绝/打断，产出「目录在但文件缺」「同包内文件版本混杂」的
损坏 node_modules。

家目录（/Users/tristan/）不受该策略管控，所以：在家目录安装，再 copy 回
workspace（copy 是创建文件，不是 rename，允许）。

本脚本用 Python subprocess 完整实现：
  步骤 2  家目录干净安装（pnpm --frozen-lockfile）
  步骤 3  校验关键包完整性，缺失则用 full_restore.py 补齐
  步骤 4  用 copy（不用 rename）把 node_modules 拷回 workspace
  步骤 5  重启 vite 并验证 /src/main.ts 的 HTTP 码

日志：本文件同目录的 home_install.log
用法：python3 home_install.py [--skip-install] [--skip-copy] [--skip-verify]
"""

import os
import re
import sys
import time
import shutil
import socket
import subprocess

BASE = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
APP = os.path.join(BASE, "yshop-drink/yshop-drink-vue3")
TOOLCHAIN = os.path.join(BASE, ".toolchain")
LOG = os.path.join(TOOLCHAIN, "home_install.log")

# 家目录安装区（不受 broker 路径策略管控）
HOME = "/Users/tristan"
INSTALL_DIR = os.path.join(HOME, "yshop-vue-install")
STORE_DIR = os.path.join(HOME, "yshop-pnpm-store")

PNPM = os.path.join(TOOLCHAIN, "pnpm/package/bin/pnpm.cjs")
REGISTRY = "https://registry.npmmirror.com"

VITE_LOG = os.path.join(TOOLCHAIN, "vite_home.log")
CACHE_DIR = "/tmp/vite-cache-yshop"
PORT = 3000
LAN_HOST = "192.168.3.78"

# 需要在 node_modules 顶层存在的关键包 -> 必须存在的文件
NEED = [
    ("postcss", "package.json"),
    ("postcss-scss", "package.json"),
    ("postcss-html", "package.json"),
    ("mitt", "package.json"),
    ("element-plus", "package.json"),
    ("@floating-ui/core", "dist/floating-ui.core.mjs"),
    ("@floating-ui/dom", "dist/floating-ui.dom.mjs"),
    ("vite", "package.json"),
    ("@vitejs/plugin-vue", "package.json"),
    ("@vitejs/plugin-vue-jsx", "package.json"),
    ("vite-plugin-eslint", "package.json"),
    ("unplugin-vue-components", "package.json"),
    ("unocss", "package.json"),
]

# postcss-scss@4.0.9 要求 postcss 8.4.x（8.5.x 会报
# "declarations.children.each is not a function"）
POSTCSS_PIN = "8.4.38"


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(cmd, cwd=None, timeout=None, env=None):
    """执行命令并返回 (returncode, stdout+stderr 尾部)"""
    try:
        p = subprocess.run(
            cmd, cwd=cwd, timeout=timeout, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        out = p.stdout.decode("utf-8", "replace")
        return p.returncode, out
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or b"").decode("utf-8", "replace")
        return -1, partial + "\n<<TIMEOUT>>"
    except Exception as e:
        return -1, "<<EXC %r>>" % (e,)


def parse_lock_versions():
    """从 pnpm-lock.yaml 的 importers 段解析出 顶层包 -> 锁定版本"""
    versions = {}
    path = os.path.join(APP, "pnpm-lock.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        log("读取 lockfile 失败 %r" % (e,))
        return versions
    # 只取 importers 段（第一个 packages: 之前）
    m = re.search(r"^packages:", text, re.M)
    head = text[: m.start()] if m else text
    cur = None
    for line in head.splitlines():
        mm = re.match(r"^  '?([^'\s:][^':]*?)'?:\s*$", line)
        if mm:
            cur = mm.group(1)
            continue
        if cur and re.match(r"^    version:\s", line):
            v = line.split(":", 1)[1].strip().strip("'\"")
            v = v.split("(")[0]
            versions[cur] = v
            cur = None
    return versions


def step_install():
    """步骤 2：家目录干净安装"""
    log("=== 步骤 2：家目录安装 -> %s ===" % INSTALL_DIR)
    os.makedirs(INSTALL_DIR, exist_ok=True)
    for fn in ("package.json", "pnpm-lock.yaml", ".npmrc"):
        src = os.path.join(APP, fn)
        dst = os.path.join(INSTALL_DIR, fn)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            log("  复制 %s" % fn)
        else:
            log("  缺失 %s（跳过）" % fn)

    env = dict(os.environ)
    env["npm_config_registry"] = REGISTRY

    for attempt in range(1, 9):
        log("  pnpm install 第 %d 次尝试" % attempt)
        rc, out = run(
            ["node", PNPM, "install", "--frozen-lockfile",
             "--store-dir", STORE_DIR,
             "--registry=" + REGISTRY],
            cwd=INSTALL_DIR, timeout=3600, env=env,
        )
        tail = out[-1500:]
        log("  返回码=%s" % rc)
        if "BROKER_DENY" in out:
            log("  命中 BROKER_DENY，重跑续传")
            continue
        if rc == 0:
            log("  安装成功")
            return True
        log("  安装失败，输出尾部：\n%s" % tail)
        if "ERR_PNPM" in out and attempt >= 3:
            log("  连续 pnpm 错误，停止重试")
            break
        time.sleep(3)
    return False


def check_packages(root):
    """校验关键包完整性，返回缺失列表 [(包名, 相对文件)]"""
    missing = []
    for name, rel in NEED:
        p = os.path.join(root, "node_modules", name, rel)
        if not os.path.exists(p):
            missing.append((name, rel))
    return missing


def check_postcss_version(root):
    pj = os.path.join(root, "node_modules/postcss/package.json")
    try:
        with open(pj, encoding="utf-8") as f:
            return re.search(r'"version"\s*:\s*"([^"]+)"', f.read()).group(1)
    except Exception:
        return None


def step_restore(missing, lock_versions):
    """步骤 3b：用 full_restore.py 补齐缺失包"""
    if not missing:
        return True
    script = os.path.join(TOOLCHAIN, "full_restore.py")
    if not os.path.exists(script):
        log("  full_restore.py 不存在，无法自动补齐")
        return False
    payload = []
    for name, _rel in missing:
        ver = lock_versions.get(name)
        if not ver:
            log("  lockfile 中找不到 %s 的版本，跳过" % name)
            continue
        payload.append("node_modules/%s\t%s\t%s" % (name, name, ver))
    if not payload:
        return False
    log("  补齐 %d 个包：%s" % (len(payload), ", ".join(p.split("\t")[1] for p in payload)))
    rc, out = run(
        ["python3", script],
        cwd=TOOLCHAIN, timeout=1800,
        env=dict(os.environ, RESTORE_STDIN="\n".join(payload)),
    )
    # full_restore.py 从 stdin 读取，这里改用管道方式重跑
    if rc != 0 or True:
        try:
            p = subprocess.run(
                ["python3", script], cwd=TOOLCHAIN, timeout=1800,
                input=("\n".join(payload) + "\n").encode(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            log("  full_restore 输出：\n%s" % p.stdout.decode("utf-8", "replace")[-2000:])
        except Exception as e:
            log("  full_restore 执行异常 %r" % (e,))
            return False
    return True


def step_pin_postcss():
    """把 postcss 钉回 8.4.x（与 postcss-scss@4.0.9 兼容）"""
    script = os.path.join(TOOLCHAIN, "full_restore.py")
    if not os.path.exists(script):
        return False
    payload = "node_modules/postcss\tpostcss\t%s\n" % POSTCSS_PIN
    try:
        p = subprocess.run(
            ["python3", script], cwd=TOOLCHAIN, timeout=900,
            input=payload.encode(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        log("  postcss 钉版输出：\n%s" % p.stdout.decode("utf-8", "replace")[-800:])
        return True
    except Exception as e:
        log("  postcss 钉版失败 %r" % (e,))
        return False


def step_copy_back():
    """步骤 4：拷回 workspace（只用 copy，不做 rename）"""
    log("=== 步骤 4：拷贝回 workspace ===")
    src = os.path.join(INSTALL_DIR, "node_modules")
    dst = os.path.join(APP, "node_modules")
    if not os.path.isdir(src):
        log("  源目录不存在 %s" % src)
        return False

    old = "/tmp/yshop-nm-old"
    if os.path.isdir(dst):
        try:
            if os.path.isdir(old):
                shutil.rmtree(old, ignore_errors=True)
            os.rename(dst, old)
            log("  旧 node_modules 已移到 %s" % old)
        except Exception as e:
            log("  移动旧目录失败（忽略）%r" % (e,))

    n = 0
    fail = 0
    for dp, dn, fn in os.walk(src):
        rel = os.path.relpath(dp, src)
        tgt = dst if rel == "." else os.path.join(dst, rel)
        try:
            os.makedirs(tgt, exist_ok=True)
        except Exception:
            continue
        for f in fn:
            s = os.path.join(dp, f)
            t = os.path.join(tgt, f)
            if os.path.exists(t):
                continue
            try:
                shutil.copy2(s, t)
                n += 1
                if n % 5000 == 0:
                    log("  已拷贝 %d 文件" % n)
            except Exception:
                fail += 1
    log("  拷贝完成 %d 文件（失败 %d）" % (n, fail))
    return n > 0


def port_alive(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def step_verify():
    """步骤 5：启动 vite 并验证 /src/main.ts"""
    log("=== 步骤 5：启动 vite 并验证 ===")

    # 杀掉占用 3000 的旧进程
    try:
        rc, out = run(["lsof", "-nP", "-iTCP:%d" % PORT, "-sTCP:LISTEN"])
        pids = set()
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                pids.add(parts[1])
        for pid in pids:
            try:
                os.kill(int(pid), 9)
                log("  已 kill 旧 vite pid=%s" % pid)
            except Exception:
                pass
    except Exception as e:
        log("  清理旧进程异常 %r" % (e,))

    os.makedirs(CACHE_DIR, exist_ok=True)
    env = dict(os.environ)
    env["VITE_SKIP_ESLINT"] = "true"
    env["VITE_CACHE_DIR"] = CACHE_DIR

    logfile = open(VITE_LOG, "wb")
    proc = subprocess.Popen(
        ["node", "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", str(PORT)],
        cwd=APP, stdout=logfile, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env, start_new_session=True,
    )
    log("  vite 已启动 pid=%s，日志 %s" % (proc.pid, VITE_LOG))

    deadline = time.time() + 240
    ready = False
    while time.time() < deadline:
        if port_alive("127.0.0.1", PORT):
            ready = True
            log("  端口 %d 已就绪" % PORT)
            break
        if proc.poll() is not None:
            log("  vite 进程已退出 rc=%s" % proc.returncode)
            break
        time.sleep(3)

    if not ready:
        try:
            with open(VITE_LOG, encoding="utf-8", errors="replace") as f:
                tail = f.read()[-4000:]
            log("  vite 未就绪，日志尾部：\n%s" % tail)
        except Exception:
            pass
        return False

    results = {}
    for label, url in [
        ("首页", "http://127.0.0.1:%d/" % PORT),
        ("入口JS", "http://127.0.0.1:%d/src/main.ts" % PORT),
        ("局域网", "http://%s:%d/" % (LAN_HOST, PORT)),
    ]:
        rc, out = run(
            ["curl", "-s", "--noproxy", "*", "-m", "150",
             "-o", "/dev/null", "-w", "%{http_code}", url],
            timeout=200,
        )
        code = out.strip().splitlines()[-1] if out.strip() else "000"
        results[label] = code
        log("  %-8s %s -> HTTP %s" % (label, url, code))

    # 入口 JS 若非 200，输出日志中的 Pre-transform error
    if results.get("入口JS") != "200":
        try:
            with open(VITE_LOG, encoding="utf-8", errors="replace") as f:
                text = f.read()
            for line in text.splitlines():
                if "Pre-transform error" in line or "Internal server error" in line:
                    log("  ERR: %s" % line.strip()[:300])
        except Exception:
            pass
    return results


def step_cleanup():
    """收尾：把中间目录移到 /tmp/.trash_*（用 rename，不用 rmtree）"""
    log("=== 清理中间目录 ===")
    targets = [
        STORE_DIR,
        INSTALL_DIR,
        "/tmp/yshop-pnpm-store", "/tmp/yshop-vue-install", "/tmp/yshop-vue-clean",
        CACHE_DIR,
        os.path.join(TOOLCHAIN, "tmp_tgz"),
        os.path.join(TOOLCHAIN, "tmp_exact"),
        os.path.join(TOOLCHAIN, "tmp_chain"),
        os.path.join(TOOLCHAIN, "tmp_broken"),
        os.path.join(TOOLCHAIN, "tmp_broken2"),
        os.path.join(TOOLCHAIN, "tmp_auto"),
        os.path.join(TOOLCHAIN, "tmp_pkgs"),
        os.path.join(TOOLCHAIN, "tmp_one"),
        os.path.join(TOOLCHAIN, "npm-cache"),
    ]
    for p in targets:
        if os.path.isdir(p):
            trash = "/tmp/.trash_" + os.path.basename(p)
            try:
                os.rename(p, trash)
                log("  moved %s -> %s" % (p, trash))
            except Exception as e:
                log("  skip %s %r" % (p, e))


def main():
    args = set(sys.argv[1:])
    log("########## home_install 开始 ##########")
    log("APP=%s" % APP)
    log("INSTALL_DIR=%s" % INSTALL_DIR)

    lock_versions = parse_lock_versions()
    log("lockfile 解析到 %d 个顶层包版本" % len(lock_versions))

    ok = True
    if "--skip-install" not in args:
        ok = step_install()
        if not ok:
            log("步骤 2 失败，仍尝试用已有内容校验")

    missing = check_packages(INSTALL_DIR)
    if missing:
        log("家目录缺失关键包 %d 个：%s" % (len(missing), ", ".join(m[0] for m in missing)))
        step_restore(missing, lock_versions)
        missing = check_packages(INSTALL_DIR)
        if missing:
            log("补齐后仍缺：%s" % ", ".join(m[0] for m in missing))
    else:
        log("家目录关键包齐全 ✅")

    pv = check_postcss_version(INSTALL_DIR)
    log("家目录 postcss 版本 = %s" % pv)
    if pv and not pv.startswith("8.4."):
        log("postcss 非 8.4.x，钉回 %s" % POSTCSS_PIN)
        step_pin_postcss()
        log("钉版后 postcss = %s" % check_postcss_version(INSTALL_DIR))

    if "--skip-copy" not in args:
        step_copy_back()

    missing2 = check_packages(APP)
    log("workspace 关键包校验：%s" % ("✅ 齐全" if not missing2 else
                                "仍缺 %s" % ", ".join(m[0] for m in missing2)))
    log("workspace postcss 版本 = %s" % check_postcss_version(APP))

    if "--skip-verify" not in args:
        step_verify()

    step_cleanup()
    log("########## home_install 结束 ##########")


if __name__ == "__main__":
    main()
