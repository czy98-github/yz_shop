"""自动迭代修复：启动 vite → 解析缺失模块 → 定位所属包 → 补齐 → 重试"""
import os, re, json, glob, shutil, subprocess, sys, tarfile, urllib.request, time

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
APP = WS + "/yshop-drink/yshop-drink-vue3"
NM = os.path.join(APP, "node_modules")
TMP = WS + "/.toolchain/tmp_auto"
VITE_LOG = WS + "/.toolchain/vite_auto.log"
os.makedirs(TMP, exist_ok=True)

REG = "https://registry.npmmirror.com"

def curl(url, dest):
    for _ in range(3):
        r = subprocess.run(["curl", "-fsSL", "--max-time", "150", "-o", dest, url],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 100:
            return True
    return False

def find_owner(missing_path):
    """缺失文件绝对路径 → 所属包目录、包名、版本"""
    mp = os.path.abspath(missing_path)
    cur = os.path.dirname(mp)
    while cur and cur.startswith(os.path.abspath(NM)):
        if os.path.basename(cur) == "node_modules":
            cur = os.path.dirname(cur)
            # cur 现在是 scope 或包所在目录的上级
            parts = cur.split(os.sep)
            base = os.path.basename(cur)
            if base.startswith("@"):
                parent = os.path.dirname(cur)
                cand = os.path.join(parent, base, os.path.basename(mp.split("node_modules")[1].lstrip(os.sep).split(os.sep)[0]))
            else:
                cand = os.path.join(cur, base)
            if os.path.isdir(cand):
                pj = os.path.join(cand, "package.json")
                if os.path.exists(pj):
                    try:
                        m = json.load(open(pj, encoding="utf-8"))
                        return cand, m.get("name") or base, m.get("version", "")
                    except Exception:
                        return cand, base, ""
            cur = os.path.dirname(cur)
        else:
            cur = os.path.dirname(cur)
    return None, None, None

def repair_pkg(pkgdir, name, ver):
    """下载 tarball，把包内所有缺失文件补进去"""
    safe = name.replace("/", "_").replace("@", "")
    mp = os.path.join(TMP, safe + ".json")
    if not os.path.exists(mp):
        if not curl("%s/%s" % (REG, name.replace("@", "%40").replace("/", "%2f")), mp):
            return 0, "元数据获取失败"
    try:
        meta = json.load(open(mp, encoding="utf-8"))
        url = meta["versions"][ver]["dist"]["tarball"]
    except Exception as e:
        return 0, "解析失败 %r" % e
    tg = os.path.join(TMP, "%s-%s.tgz" % (safe, ver))
    if not os.path.exists(tg):
        if not curl(url, tg):
            return 0, "tarball 下载失败"
    work = os.path.join(TMP, "ex_" + safe)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    try:
        with tarfile.open(tg) as tf:
            tf.extractall(work, filter="data")
    except Exception as e:
        return 0, "解包失败 %r" % e
    src_root = os.path.join(work, "package")
    if not os.path.isdir(src_root):
        return 0, "包结构异常"
    cnt = 0
    for root, dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        tgt = pkgdir if rel == "." else os.path.join(pkgdir, rel)
        try:
            os.makedirs(tgt, exist_ok=True)
        except Exception:
            continue
        for f in files:
            t = os.path.join(tgt, f)
            if not os.path.exists(t):
                try:
                    shutil.copy2(os.path.join(root, f), t); cnt += 1
                except Exception:
                    pass
    return cnt, "ok"

RE_MISS = re.compile(r"Cannot find module '([^']+)'")
fixed_pkgs = {}

for rnd in range(1, 16):
    # 启动 vite
    VLOG = VITE_LOG.replace('.log', '_r%d.log' % rnd)
    p = subprocess.Popen(["node", "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", "3000"],
                         cwd=APP, stdout=open(VLOG, "wb"), stderr=subprocess.STDOUT,
                         start_new_session=True)
    ok = False
    for _ in range(40):
        time.sleep(1.5)
        txt = ""
        if os.path.exists(VLOG):
            txt = open(VLOG, encoding="utf-8", errors="ignore").read()
        if "ready in" in txt or "Local:" in txt:
            ok = True
            break
        m = RE_MISS.search(txt)
        if m:
            break
    txt = open(VLOG, encoding="utf-8", errors="ignore").read() if os.path.exists(VLOG) else ""

    if ok:
        print("=" * 70)
        print("✅ 第 %d 轮：vite 启动成功" % rnd)
        print("=" * 70)
        for line in txt.splitlines()[:12]:
            print("   " + line[:150])
        # 端口验证
        r = subprocess.run(["curl", "-s", "--noproxy", "*", "-m", "15", "-o", "/dev/null",
                            "-w", "%{http_code}", "http://127.0.0.1:3000/"],
                           capture_output=True, text=True)
        print("")
        print("   http://127.0.0.1:3000  -> HTTP %s" % r.stdout.strip())
        r = subprocess.run(["curl", "-s", "--noproxy", "*", "-m", "15", "-o", "/dev/null",
                            "-w", "%{http_code}", "http://10.211.14.175:3000/"],
                           capture_output=True, text=True)
        print("   http://10.211.14.175:3000 -> HTTP %s" % r.stdout.strip())
        print("")
        print("修复过的包: %s" % (", ".join(sorted(set(fixed_pkgs.keys()))) or "(无)"))
        sys.exit(0)

    m = RE_MISS.search(txt)
    if not m:
        print("=" * 70)
        print("❌ 第 %d 轮：非模块缺失错误" % rnd)
        print("=" * 70)
        print(txt[:1800])
        try:
            os.kill(p.pid, 9)
        except Exception:
            pass
        sys.exit(1)

    missing = m.group(1)
    print("第 %d 轮：缺失模块 %s" % (rnd, missing))
    try:
        os.kill(p.pid, 9)
    except Exception:
        pass
    time.sleep(1)

    # 相对路径：从 Require stack 定位来源文件
    if not missing.startswith("/"):
        req_stack = re.search(r"Require stack:(.*?)(?:\n\s+at |\Z)", txt, re.S)
        src_file = None
        if req_stack:
            lines = [l.strip() for l in req_stack.group(1).splitlines() if l.strip()]
            for l in lines:
                if l.endswith("/" + missing.lstrip("./").replace(".js", "")) or l.endswith(missing.lstrip("./")):
                    src_file = l; break
            if src_file is None and lines:
                src_file = lines[0]
        if src_file:
            base = os.path.dirname(src_file)
            cand = os.path.normpath(os.path.join(base, missing))
            print("   相对路径解析: %s + %s -> %s" % (os.path.basename(base), missing, cand))
            # 从该文件向上找所属包
            cur = os.path.dirname(cand)
            pkgdir = name = ver = None
            while cur and cur.startswith(os.path.abspath(NM)):
                pj = os.path.join(cur, "package.json")
                if os.path.exists(pj):
                    try:
                        mj = json.load(open(pj, encoding="utf-8"))
                        pkgdir, name, ver = cur, mj.get("name"), mj.get("version", "")
                    except Exception:
                        pkgdir = cur
                    break
                cur = os.path.dirname(cur)
    if not pkgdir:
        pkgdir, name, ver = find_owner(missing)
    if not pkgdir:
        # 退化为：向上找最近的含 package.json 的目录
        cur = os.path.dirname(os.path.abspath(missing))
        while cur.startswith(os.path.abspath(NM)):
            if os.path.exists(os.path.join(cur, "package.json")):
                try:
                    mj = json.load(open(os.path.join(cur, "package.json"), encoding="utf-8"))
                    pkgdir, name, ver = cur, mj.get("name"), mj.get("version", "")
                except Exception:
                    pkgdir = cur
                break
            cur = os.path.dirname(cur)
    if not pkgdir or not name or not ver:
        print("   ⚠️ 无法定位所属包，尝试直接补文件")
        # 直接从 registry 下该路径对应的 tarball（按文件名猜包名不可靠）→ 放弃
        sys.exit(1)

    key = "%s@%s" % (name, ver)
    if key in fixed_pkgs:
        print("   ⚠️ %s 已修过仍失败，停止" % key)
        sys.exit(1)

    cnt, msg = repair_pkg(pkgdir, name, ver)
    fixed_pkgs[key] = cnt
    print("   ✅ 修复 %s（补入 %d 文件） %s" % (key, cnt, msg))

print("❌ 超过最大轮次")
sys.exit(1)
