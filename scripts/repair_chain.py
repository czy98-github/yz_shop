"""定向补齐 vite.config.ts 插件链所需包的缺失文件"""
import os, json, shutil, subprocess, tarfile, glob

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
APP = WS + "/yshop-drink/yshop-drink-vue3"
NM = os.path.join(APP, "node_modules")
TMP = WS + "/.toolchain/tmp_chain"
os.makedirs(TMP, exist_ok=True)
REG = "https://registry.npmmirror.com"

# vite.config.ts + build/vite/index.ts 里 import 的全部插件及其依赖
TARGETS = [
    "@vitejs/plugin-vue", "@vitejs/plugin-vue-jsx", "vite-plugin-progress",
    "vite-plugin-eslint", "vite-plugin-purge-icons", "vite-plugin-ejs",
    "unplugin-element-plus", "unplugin-auto-import", "unplugin-vue-components",
    "vite-plugin-compression", "vite-plugin-top-level-await",
    "@intlify/unplugin-vue-i18n", "vite-plugin-svg-icons", "unocss",
    "picomatch", "eslint", "postcss", "autoprefixer", "unplugin-icons",
    "@intlify/core-base", "@intlify/shared", "@vue/compiler-sfc",
    "@vue/compiler-dom", "@vue/compiler-core", "@vue/runtime-core",
    "@vue/compiler-ssr", "@vue/shared", "magic-string", "@babel/core",
    "@babel/parser", "@babel/types", "@babel/traverse", "@babel/generator",
    "@babel/template", "@babel/code-frame", "@babel/helper-module-transforms",
    "@babel/helper-module-imports", "@babel/helper-validator-identifier",
    "@babel/helper-plugin-utils", "@babel/helper-compilation-targets",
    "@babel/helper-validator-option", "@babel/plugin-transform-modules-commonjs",
    "@babel/plugin-transform-parameters", "@babel/plugin-transform-block-scoping",
    "@babel/plugin-transform-dotall-regex", "@babel/plugin-transform-regenerator",
    "@babel/plugin-transform-regenerator-methods", "@babel/runtime",
    "@jridgewell/trace-mapping", "@jridgewell/sourcemap-codec", "@jridgewell/gen-mapping",
    "@jridgewell/resolve-uri", "@jridgewell/set-array", "jsesc", "entities",
    "source-map-js", "source-map", "magic-string", "estree-walker",
    "@vue/compiler-core", "vue", "vue-tsc", "typescript", "vite",
    "esbuild", "postcss-load-config", "postcss-value-parser", "nanoid",
    "picomatch", "tinyglobby", "fast-glob", "chokidar", "ws", "rollup",
]

def curl(url, dest):
    for _ in range(3):
        r = subprocess.run(["curl", "-fsSL", "--max-time", "150", "-o", dest, url],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 100:
            return True
    return False

def find_all(name):
    """找出该包名的所有安装位置（含嵌套）"""
    res = []
    base = name.split("/")
    stack = [NM]
    while stack:
        cur = stack.pop()
        if not os.path.isdir(cur):
            continue
        for n in sorted(os.listdir(cur)):
            if n.startswith("."):
                continue
            p = os.path.join(cur, n)
            if not os.path.isdir(p):
                continue
            if n.startswith("@") and len(base) == 2:
                sp = os.path.join(p, base[1])
                if os.path.isdir(sp):
                    res.append(sp)
                    stack.append(os.path.join(sp, "node_modules"))
            elif n == base[0] and len(base) == 1:
                res.append(p)
                stack.append(os.path.join(p, "node_modules"))
    return res

total_pkg, total_file = 0, 0
for name in TARGETS:
    dirs = find_all(name)
    if not dirs:
        continue
    for d in dirs:
        pj = os.path.join(d, "package.json")
        if not os.path.exists(pj):
            continue
        try:
            meta = json.load(open(pj, encoding="utf-8"))
        except Exception:
            continue
        ver = meta.get("version", "")
        if not ver:
            continue
        safe = name.replace("/", "_").replace("@", "")
        mp = os.path.join(TMP, safe + ".json")
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
        work = os.path.join(TMP, "ex_" + safe + "_" + ver)
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work, exist_ok=True)
        try:
            with tarfile.open(tg) as tf:
                tf.extractall(work, filter="data")
        except Exception:
            continue
        src_root = os.path.join(work, "package")
        if not os.path.isdir(src_root):
            continue
        cnt = 0
        for root, dirs_, files in os.walk(src_root):
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
        if cnt:
            print("  ✅ %-34s v%-10s 补入 %d 文件" % (name, ver, cnt))
            total_pkg += 1
            total_file += cnt

print("")
print("=== 共补齐 %d 个包的 %d 个文件 ===" % (total_pkg, total_file))
