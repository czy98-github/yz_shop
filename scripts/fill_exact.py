"""按包目录精确版本补齐缺失文件（处理嵌套 node_modules）"""
import os, json, shutil, subprocess, tarfile, sys

APP = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-vue3"
TMP = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/.toolchain/tmp_exact"
os.makedirs(TMP, exist_ok=True)
REG = "https://registry.npmmirror.com"

def curl(url, dest):
    for _ in range(3):
        r = subprocess.run(["curl", "-fsSL", "--max-time", "150", "-o", dest, url],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 100:
            return True
    return False

def fill(pkgdir, name, ver):
    """把 tarball 内所有缺失文件补进 pkgdir"""
    safe = name.replace("/", "_").replace("@", "")
    mp = os.path.join(TMP, safe + "-" + ver + ".json")
    if not os.path.exists(mp):
        if not curl("%s/%s" % (REG, name.replace("@", "%40").replace("/", "%2f")), mp):
            return 0, "元数据失败"
    try:
        jm = json.load(open(mp, encoding="utf-8"))
        url = jm["versions"][ver]["dist"]["tarball"]
    except Exception as e:
        return 0, "解析失败 %r" % e
    tg = os.path.join(TMP, "%s-%s.tgz" % (safe, ver))
    if not os.path.exists(tg):
        if not curl(url, tg):
            return 0, "下载失败"
    work = os.path.join(TMP, "ex_" + safe + "_" + ver + "_%d" % os.getpid())
    os.makedirs(work, exist_ok=True)
    try:
        with tarfile.open(tg) as tf:
            tf.extractall(work, filter="data")
    except Exception as e:
        return 0, "解包失败 %r" % e
    src_root = os.path.join(work, "package")
    if not os.path.isdir(src_root):
        return 0, "结构异常"
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

# 输入：包目录绝对路径（每行一个）
targets = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
print("待补齐目录: %d" % len(targets))
for d in targets:
    pj = os.path.join(d, "package.json")
    if not os.path.exists(pj):
        print("  ⚠️ 无 package.json: %s" % d); continue
    try:
        m = json.load(open(pj, encoding="utf-8"))
    except Exception as e:
        print("  ⚠️ 解析失败: %s" % d); continue
    name = m.get("name")
    ver = m.get("version")
    if not name or not ver:
        print("  ⚠️ 缺 name/version: %s" % d); continue
    cnt, msg = fill(d, name, ver)
    print("  %s %-30s v%-9s 补入 %d 文件  %s" %
          ("✅" if cnt else "·", name, ver, cnt, msg))
