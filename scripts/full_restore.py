"""完整覆盖恢复：把指定包目录整个替换为 tarball 内容（解决版本混杂）"""
import os, json, shutil, subprocess, tarfile, sys

APP = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-vue3"
TMP = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/.toolchain/tmp_full"
os.makedirs(TMP, exist_ok=True)
REG = "https://registry.npmmirror.com"

def curl(url, dest):
    for _ in range(3):
        r = subprocess.run(["curl", "-fsSL", "--max-time", "150", "-o", dest, url],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 100:
            return True
    return False

def full_restore(rel, name, ver, overwrite=True):
    d = os.path.join(APP, rel)
    safe = name.replace("/", "_").replace("@", "")
    mp = os.path.join(TMP, safe + "-" + ver + ".json")
    if not os.path.exists(mp):
        if not curl("%s/%s" % (REG, name.replace("@", "%40").replace("/", "%2f")), mp):
            return -1, "元数据失败"
    try:
        jm = json.load(open(mp, encoding="utf-8"))
        url = jm["versions"][ver]["dist"]["tarball"]
    except Exception as e:
        return -1, "解析失败 %r" % e
    tg = os.path.join(TMP, "%s-%s.tgz" % (safe, ver))
    if not os.path.exists(tg):
        if not curl(url, tg):
            return -1, "下载失败"
    work = os.path.join(TMP, "ex_%s" % safe)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    try:
        with tarfile.open(tg) as tf:
            tf.extractall(work, filter="data")
    except Exception as e:
        return -1, "解包失败 %r" % e
    src_root = os.path.join(work, "package")
    if not os.path.isdir(src_root):
        return -1, "结构异常"
    cnt = 0
    for root, dirs, files in os.walk(src_root):
        relp = os.path.relpath(root, src_root)
        tgt = d if relp == "." else os.path.join(d, relp)
        os.makedirs(tgt, exist_ok=True)
        for f in files:
            s = os.path.join(root, f)
            t = os.path.join(tgt, f)
            if overwrite or not os.path.exists(t):
                try:
                    shutil.copy2(s, t); cnt += 1
                except Exception:
                    pass
    return cnt, "ok"

# 从 stdin 读 rel\tname\tver
items = []
for l in sys.stdin.read().splitlines():
    p = l.strip().split("\t")
    if len(p) >= 3:
        items.append((p[0], p[1], p[2]))

print("完整覆盖恢复 %d 个包" % len(items))
for rel, name, ver in items:
    n, msg = full_restore(rel, name, ver, overwrite=True)
    print("  %s %-56s v%-9s 覆盖 %d 文件 %s" %
          ("✅" if n >= 0 else "❌", rel[:56], ver, max(n, 0), msg))
