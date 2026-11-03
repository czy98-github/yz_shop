"""终极检测：按 package.json 的 main/module/exports/bin 字段解析入口，判定文件是否缺失"""
import os, json, sys

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
APP = WS + "/yshop-drink/yshop-drink-vue3"
NM = os.path.join(APP, "node_modules")

def all_pkg_dirs():
    """含嵌套 node_modules 里的所有包目录"""
    out = []
    stack = [NM]
    while stack:
        cur = stack.pop()
        if not os.path.isdir(cur):
            continue
        for name in sorted(os.listdir(cur)):
            if name.startswith("."):
                continue
            p = os.path.join(cur, name)
            if not os.path.isdir(p):
                continue
            if name.startswith("@"):
                for sub in sorted(os.listdir(p)):
                    sp = os.path.join(p, sub)
                    if os.path.isdir(sp):
                        out.append((name + "/" + sub, sp))
                        stack.append(os.path.join(sp, "node_modules"))
            else:
                out.append((name, p))
                stack.append(os.path.join(p, "node_modules"))
    return out

def resolve_exports(pkgdir, meta):
    """按 exports 解析 "." 入口，返回候选相对路径列表"""
    exp = meta.get("exports")
    cands = []
    if isinstance(exp, str):
        cands.append(exp)
    elif isinstance(exp, dict):
        root = exp.get(".")
        if isinstance(root, str):
            cands.append(root)
        elif isinstance(root, dict):
            for cond in ("require", "node", "default", "import"):
                v = root.get(cond)
                if isinstance(v, str):
                    cands.append(v); break
                if isinstance(v, dict):
                    for c2 in ("require", "node", "default", "import"):
                        v2 = v.get(c2)
                        if isinstance(v2, str):
                            cands.append(v2); break
                    break
    return cands

bad = []
pkgs = all_pkg_dirs()
for label, d in pkgs:
    pj = os.path.join(d, "package.json")
    if not os.path.exists(pj):
        continue
    try:
        meta = json.load(open(pj, encoding="utf-8"))
    except Exception:
        continue

    cands = []
    for f in ("main", "module"):
        if meta.get(f):
            cands.append(meta[f])
    cands += resolve_exports(d, meta)
    if not cands:
        continue

    ok_any = False
    for c in cands:
        cp = c.lstrip("./")
        if os.path.isfile(os.path.join(d, cp)):
            ok_any = True; break
        if os.path.isfile(os.path.join(d, cp + ".js")):
            ok_any = True; break
        if os.path.isdir(os.path.join(d, cp)):
            for idx in ("index.js", "index.cjs", "index.mjs", "index.json"):
                if os.path.isfile(os.path.join(d, cp, idx)):
                    ok_any = True; break
        if ok_any:
            break
    if not ok_any:
        bad.append((label, d, meta.get("name") or label, meta.get("version", "")))

print("包总数: %d   入口缺失: %d" % (len(pkgs), len(bad)))
for label, d, name, ver in bad:
    print("  %-40s v%s" % (label, ver))

lines = ["%s\t%s\t%s\tx" % (name, name, ver) for label, d, name, ver in bad]
open(WS + "/.toolchain/bad_pkgs2.tsv", "w").write("\n".join(lines))
print("")
print("清单: bad_pkgs2.tsv（%d 行）" % len(lines))
