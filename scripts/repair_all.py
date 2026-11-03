"""按包批量补齐所有缺失文件（curl 直下 tarball，逐文件比对拷贝）"""
import os, json, glob, shutil, subprocess, sys, tarfile

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
APP = WS + "/yshop-drink/yshop-drink-vue3"
NM = os.path.join(APP, "node_modules")
TMP = WS + "/.toolchain/tmp_tgz"
os.makedirs(TMP, exist_ok=True)

# 读入 pkgname\tversion
items = []
for l in open(WS + "/.toolchain/bad_pkgs.tsv", encoding="utf-8"):
    l = l.strip()
    if not l:
        continue
    p = l.split("\t")
    if len(p) >= 3 and p[2]:
        items.append((p[0], p[2]))

# 过滤掉 .xxx-xxxx 临时目录（npm 装到一半的残留）
items = [(n, v) for n, v in items if not n.startswith(".")]
print("待修复包: %d" % len(items))

def curl(url, dest):
    for _ in range(3):
        r = subprocess.run(["curl", "-fsSL", "--max-time", "150", "-o", dest, url],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 100:
            return True
    return False

ok, fail = 0, []
for name, ver in items:
    # 找到实际安装目录（含 scoped 与嵌套）
    base = name.split("/")
    if name.startswith("@"):
        cand = [os.path.join(NM, base[0], base[1])]
    else:
        cand = [os.path.join(NM, name)]
    # 嵌套副本
    for root, dirs, _ in os.walk(NM):
        if "node_modules" in root and root.count("node_modules") > 1:
            for c in list(cand):
                alt = os.path.join(root, name)
                if os.path.isdir(alt) and alt not in cand:
                    cand.append(alt)
        if len(cand) > 12:
            break

    # 元数据
    safe = name.replace("/", "_").replace("@", "")
    mp = os.path.join(TMP, safe + ".json")
    if not os.path.exists(mp):
        if not curl("https://registry.npmmirror.com/%s" % name.replace("@", "%40").replace("/", "%2f"), mp):
            print("  ❌ %s 元数据失败" % name); fail.append(name); continue
    try:
        meta = json.load(open(mp, encoding="utf-8"))
        url = meta["versions"][ver]["dist"]["tarball"]
    except Exception as e:
        print("  ❌ %s@%s 解析失败 %r" % (name, ver, e)); fail.append(name); continue

    tg = os.path.join(TMP, "%s-%s.tgz" % (safe, ver))
    if not os.path.exists(tg):
        if not curl(url, tg):
            print("  ❌ %s@%s 下载失败" % (name, ver)); fail.append(name); continue

    work = os.path.join(TMP, "ex_" + safe)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    try:
        with tarfile.open(tg) as tf:
            tf.extractall(work, filter="data")
    except Exception as e:
        print("  ❌ %s 解包失败 %r" % (name, e)); fail.append(name); continue
    src_root = os.path.join(work, "package")
    if not os.path.isdir(src_root):
        fail.append(name); continue

    total = 0
    for c in cand:
        if not os.path.isdir(c):
            continue
        for root, dirs, files in os.walk(src_root):
            rel = os.path.relpath(root, src_root)
            tgt = c if rel == "." else os.path.join(c, rel)
            try:
                os.makedirs(tgt, exist_ok=True)
            except Exception:
                continue
            for f in files:
                t = os.path.join(tgt, f)
                if not os.path.exists(t):
                    try:
                        shutil.copy2(os.path.join(root, f), t); total += 1
                    except Exception:
                        pass
    print("  ✅ %-40s 补入 %d 文件" % (name, total))
    ok += 1

print("")
print("=== 处理 %d 个包，失败 %d ===" % (ok, len(fail)))
for f in fail:
    print("  ❌ %s" % f)
