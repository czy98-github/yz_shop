"""自动循环：启动 vite → 解析各类报错 → 定位并修复包 → 重试"""
import os, re, json, shutil, subprocess, tarfile, time, glob, sys

APP = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-vue3"
TMP = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/.toolchain/tmp_loop"
os.makedirs(TMP, exist_ok=True)
REG = "https://registry.npmmirror.com"
VLOG = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/.toolchain/vite_loop.log"

def curl(url, dest):
    for _ in range(3):
        r = subprocess.run(["curl", "-fsSL", "--max-time", "150", "-o", dest, url],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 100:
            return True
    return False

def find_pkg_dirs(name):
    """找出包名对应的所有目录（含嵌套）"""
    res = []
    stack = [os.path.join(APP, "node_modules")]
    while stack:
        cur = stack.pop()
        try:
            entries = list(os.scandir(cur))
        except Exception:
            continue
        for e in entries:
            if not e.is_dir(follow_symlinks=False) or e.name.startswith("."):
                continue
            if e.name.startswith("@"):
                try:
                    for s in os.scandir(e.path):
                        if s.is_dir(follow_symlinks=False) and not s.name.startswith("."):
                            if s.name == name.split("/")[-1] and os.path.basename(
                                    os.path.dirname(os.path.dirname(s.path))) == name.split("/")[0]:
                                res.append(s.path)
                            stack.append(os.path.join(s.path, "node_modules"))
                except Exception:
                    pass
            else:
                if e.name == name:
                    res.append(e.path)
                stack.append(os.path.join(e.path, "node_modules"))
    return res

def full_restore(name):
    """把该包名的所有安装位置完整覆盖恢复"""
    dirs = find_pkg_dirs(name)
    if not dirs:
        return 0, "未找到安装目录"
    total = 0
    for d in dirs:
        pj = os.path.join(d, "package.json")
        if not os.path.exists(pj):
            continue
        try:
            m = json.load(open(pj, encoding="utf-8"))
        except Exception:
            continue
        ver = m.get("version")
        if not ver:
            continue
        safe = name.replace("/", "_").replace("@", "")
        mp = os.path.join(TMP, safe + "-" + ver + ".json")
        if not os.path.exists(mp):
            if not curl("%s/%s" % (REG, name.replace("@", "%40").replace("/", "%2f")), mp):
                continue
        try:
            jm = json.load(open(mp, encoding="utf-8"))
            url = jm["versions"][ver]["dist"]["tarball"]
        except Exception:
            continue
        tg = os.path.join(TMP, "%s-%s.tgz" % (safe, ver))
        if not os.path.exists(tg):
            if not curl(url, tg):
                continue
        work = os.path.join(TMP, "ex_%s_%d" % (safe, os.getpid()))
        os.makedirs(work, exist_ok=True)
        try:
            with tarfile.open(tg) as tf:
                tf.extractall(work, filter="data")
        except Exception:
            continue
        src_root = os.path.join(work, "package")
        if not os.path.isdir(src_root):
            continue
        for root, dirs, files in os.walk(src_root):
            rel = os.path.relpath(root, src_root)
            tgt = d if rel == "." else os.path.join(d, rel)
            try:
                os.makedirs(tgt, exist_ok=True)
            except Exception:
                continue
            for f in files:
                s = os.path.join(root, f)
                t = os.path.join(tgt, f)
                try:
                    shutil.copy2(s, t); total += 1
                except Exception:
                    pass
    return total, "ok"

PATTERNS = [
    (re.compile(r'Failed to resolve entry for package "([^"]+)"'), "resolve-entry"),
    (re.compile(r"Cannot find module '([^']+)'"), "cannot-find"),
    (re.compile(r"Failed to import ESLint"), "eslint"),
    (re.compile(r'does not provide an export named \'([^\']+)\''), "no-export"),
]

fixed = set()
for rnd in range(1, 26):
    log = VLOG.replace(".log", "_r%d.log" % rnd)
    p = subprocess.Popen(
        ["node", "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", "3000"],
        cwd=APP, stdout=open(log, "wb"), stderr=subprocess.STDOUT,
        env=dict(os.environ, VITE_SKIP_ESLINT="true"), start_new_session=True)
    txt = ""
    ready = False
    for _ in range(90):
        time.sleep(2)
        if os.path.exists(log):
            txt = open(log, encoding="utf-8", errors="ignore").read()
        if "ready in" in txt or "Local:" in txt:
            ready = True
            break
        if "error when starting dev server" in txt:
            break
    if ready:
        print("=" * 72)
        print("✅ 第 %d 轮：vite 启动成功" % rnd)
        print("=" * 72)
        for line in txt.splitlines()[:12]:
            print("   " + line[:140])
        for u in ("http://127.0.0.1:3000/", "http://10.211.14.175:3000/"):
            r = subprocess.run(["curl", "-s", "--noproxy", "*", "-m", "25", "-o", "/dev/null",
                                "-w", "%{http_code}", u], capture_output=True, text=True)
            print("   %-28s HTTP %s" % (u, r.stdout.strip()))
        print("")
        print("修复过的包: %s" % (", ".join(sorted(fixed)) or "(无)"))
        sys.exit(0)

    try:
        os.kill(p.pid, 9)
    except Exception:
        pass
    time.sleep(1)

    target = None
    kind = None
    for rx, k in PATTERNS:
        m = rx.search(txt)
        if m:
            target = m.group(1) if m.groups() else k
            kind = k
            break
    if not target:
        print("❌ 第 %d 轮：无法识别的错误" % rnd)
        print(txt[:1500])
        sys.exit(1)
    if kind == "eslint":
        print("第 %d 轮：eslint 导入失败（已用 VITE_SKIP_ESLINT 跳过，若仍失败需修 eslint 包）" % rnd)
        print(txt[:900])
        sys.exit(1)
    if kind == "no-export":
        print("第 %d 轮：导出缺失 %s —— 需按版本混杂处理" % (rnd, target))
        sys.exit(1)

    print("第 %d 轮：%s → 修复包 %s" % (rnd, kind, target))
    n, msg = full_restore(target)
    fixed.add(target)
    print("   覆盖 %d 文件 %s" % (n, msg))

print("❌ 超过最大轮次")
sys.exit(1)
