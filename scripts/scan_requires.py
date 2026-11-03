"""精确检测：扫描所有包内 require() 的相对路径引用，找出引用了但缺失的文件"""
import os, re, json, sys

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
APP = WS + "/yshop-drink/yshop-drink-vue3"
NM = os.path.join(APP, "node_modules")

REQ = re.compile(r"""require\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)""")
EXT = ["", ".js", ".cjs", ".mjs", ".json", "/index.js", "/index.cjs", "/index.json"]

def resolve(base):
    for e in EXT:
        p = base + e
        if os.path.isfile(p):
            return p
    return None

def pkg_of(path):
    """从绝对路径回溯所属包目录与包名"""
    rel = os.path.relpath(path, NM)
    parts = rel.split(os.sep)
    if parts[0].startswith("@") and len(parts) > 1:
        return os.path.join(NM, parts[0], parts[1]), parts[0] + "/" + parts[1]
    return os.path.join(NM, parts[0]), parts[0]

missing = {}   # (pkgdir, pkgname) -> set(missing_rel_paths)
scan_pkgs = 0
for root, dirs, files in os.walk(NM):
    dirs[:] = [d for d in dirs if d != ".bin"]
    # 限制在包目录内（遇到 node_modules 子目录说明进入了嵌套包，也算独立包）
    for f in files:
        if not f.endswith(".js") and not f.endswith(".cjs"):
            continue
        fp = os.path.join(root, f)
        try:
            if os.path.getsize(fp) > 3_000_000:
                continue
            src = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        if "require(" not in src:
            continue
        for m in REQ.finditer(src):
            rel = m.group(1)
            base = os.path.normpath(os.path.join(root, rel))
            if resolve(base):
                continue
            pd, pn = pkg_of(fp)
            missing.setdefault((pd, pn), set()).add(os.path.relpath(base, pd))
        scan_pkgs += 1

print("扫描 JS 文件: %d" % scan_pkgs)
print("发现文件缺失的包: %d" % len(missing))
print("")
lines = []
for (pd, pn), files_set in sorted(missing.items(), key=lambda x: x[0][1]):
    pj = os.path.join(pd, "package.json")
    ver = ""
    if os.path.exists(pj):
        try:
            ver = json.load(open(pj, encoding="utf-8")).get("version", "")
        except Exception:
            pass
    print("  %-34s v%-10s 缺 %d 个: %s" % (pn, ver, len(files_set),
          ", ".join(sorted(files_set)[:4])))
    lines.append("%s\t%s\t%s\t%s" % (pn, pn, ver, "x"))
open(WS + "/.toolchain/bad_pkgs.tsv", "w").write("\n".join(lines))
print("")
print("清单已写入 bad_pkgs.tsv（%d 行）" % len(lines))
