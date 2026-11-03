"""轻量版：只恢复「缺 package.json」的嵌套包"""
import os, json, shutil, subprocess, tarfile

APP = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-vue3"
NM = os.path.join(APP, "node_modules")
TMP = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/.toolchain/tmp_broken2"
os.makedirs(TMP, exist_ok=True)
REG = "https://registry.npmmirror.com"

def curl(url, dest):
    for _ in range(3):
        r = subprocess.run(["curl", "-fsSL", "--max-time", "120", "-o", dest, url],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 100:
            return True
    return False

# 1) 找出缺 package.json 的嵌套包目录（只看 node_modules 的直接子目录，不深递归）
broken = []
stack = [NM]
while stack:
    cur = stack.pop()
    try:
        entries = list(os.scandir(cur))
    except Exception:
        continue
    for e in entries:
        if not e.is_dir(follow_symlinks=False):
            continue
        n = e.name
        if n.startswith("."):
            continue
        if n.startswith("@"):
            try:
                for s in os.scandir(e.path):
                    if s.is_dir(follow_symlinks=False) and not s.name.startswith("."):
                        if not os.path.exists(os.path.join(s.path, "package.json")):
                            broken.append((s.path, "%s/%s" % (n, s.name)))
                        stack.append(s.path)
            except Exception:
                pass
        else:
            if not os.path.exists(os.path.join(e.path, "package.json")):
                broken.append((e.path, n))
            stack.append(e.path)

print("缺 package.json 的嵌套包: %d" % len(broken))
for d, n in broken[:20]:
    print("   %s" % os.path.relpath(d, NM))

# 2) 找同级版本参考
def sibling_version(name):
    parts = name.split("/")
    for dp, dn, fn in os.walk(NM):
        cand = os.path.join(dp, name)
        if os.path.isdir(cand):
            pj = os.path.join(cand, "package.json")
            if os.path.exists(pj):
                try:
                    v = json.load(open(pj, encoding="utf-8")).get("version")
                    if v:
                        return v
                except Exception:
                    pass
        if dp.count("node_modules") > 2:
            dn[:] = []
    return None

fixed = 0
for d, name in broken:
    ver = sibling_version(name)
    if not ver:
        # 从 registry 取最新版
        mp = os.path.join(TMP, name.replace("/", "_").replace("@", "") + ".json")
        if not curl("%s/%s" % (REG, name.replace("@", "%40").replace("/", "%2f")), mp):
            print("  ❌ %s 元数据失败" % name); continue
        try:
            jm = json.load(open(mp, encoding="utf-8"))
            ver = list(jm["versions"].keys())[-1]
        except Exception:
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
            print("  ❌ %s@%s 下载失败" % (name, ver)); continue
    work = os.path.join(TMP, "ex%d" % fixed)
    os.makedirs(work, exist_ok=True)
    try:
        with tarfile.open(tg) as tf:
            tf.extractall(work, filter="data")
    except Exception as e:
        print("  ❌ %s 解包失败" % name); continue
    src_root = os.path.join(work, "package")
    if not os.path.isdir(src_root):
        continue
    cnt = 0
    for root, dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        tgt = d if rel == "." else os.path.join(d, rel)
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
    print("  ✅ %-40s v%-9s 补入 %d 文件" % (os.path.relpath(d, NM)[:40], ver, cnt))
    fixed += 1

print("")
print("=== 恢复 %d 个 ===" % fixed)
