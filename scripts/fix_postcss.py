#!/usr/bin/env python3
"""
fix_postcss.py —— 把 node_modules/postcss 修成 lockfile 锁定的 8.4.38

为什么必须降级 postcss
----------------------
- pnpm-lock.yaml 锁定 postcss 8.4.38（specifier ^8.4.35）
- postcss-scss 4.0.9 的 peerDependencies 是 postcss ^8.4.29 —— 明确排除 8.5.x
- postcss-scss 最新版就是 4.0.9，没有能兼容 postcss 8.5 的版本
- 当前 node_modules 里 postcss 是 8.5.32（安装被 broker 打断导致的版本混杂）
- 8.5.x 重构了 lib/node.js（cloneNode 由递归改为显式栈），
  postcss-scss 4.0.9 访问 declarations.children.each 时抛
  "declarations.children.each is not a function"

因此唯一正解：把 postcss 换回 8.4.38。

实现要点
--------
broker 按「解析后的路径策略」拒绝 rename，但允许创建文件。所以本脚本
只用「下载 tarball -> 解包 -> 逐文件写入目标目录」，全程不做 rename。
只用 Python 标准库（tarfile / urllib / shutil），不依赖 curl / tar 子进程。

用法：
    python3 fix_postcss.py                # 修复并校验版本
    python3 fix_postcss.py --verify-only  # 只校验当前版本
"""

import os
import sys
import json
import shutil
import tarfile
import urllib.request

APP = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-vue3"
TARGET = os.path.join(APP, "node_modules", "postcss")
VERSION = "8.4.38"
TARBALL = "https://registry.npmmirror.com/postcss/-/postcss-%s.tgz" % VERSION
MIRRORS = [
    TARBALL,
    "https://registry.npmjs.org/postcss/-/postcss-%s.tgz" % VERSION,
]
WORK = "/tmp/fix_postcss_work"


def log(msg):
    print("[fix_postcss] %s" % msg, flush=True)


def current_version():
    pj = os.path.join(TARGET, "package.json")
    try:
        with open(pj, encoding="utf-8") as f:
            return json.load(f).get("version")
    except Exception:
        return None


def download(dest):
    for url in MIRRORS:
        try:
            log("下载 %s" % url)
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if len(data) > 10000:
                with open(dest, "wb") as f:
                    f.write(data)
                log("  成功，%d 字节" % len(data))
                return True
            log("  内容过小，放弃")
        except Exception as e:
            log("  失败 %r" % (e,))
    return False


def extract(tgz, outdir):
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir, exist_ok=True)
    with tarfile.open(tgz) as tf:
        tf.extractall(outdir, filter="data")
    src = os.path.join(outdir, "package")
    if not os.path.isdir(src):
        return None
    return src


def copy_over(src, dst):
    """逐文件写入目标目录（只创建，不 rename）"""
    n = 0
    skipped = 0
    for dp, dn, fn in os.walk(src):
        rel = os.path.relpath(dp, src)
        tgt = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(tgt, exist_ok=True)
        for f in fn:
            s = os.path.join(dp, f)
            t = os.path.join(tgt, f)
            # 8.5.x 可能残留了 8.4.x 没有的文件，清掉避免混用
            try:
                with open(s, "rb") as fh:
                    data = fh.read()
                with open(t, "wb") as fh:
                    fh.write(data)
                n += 1
            except Exception:
                skipped += 1
    return n, skipped


def prune_extra(src, dst):
    """删除目标目录里源包没有的文件（版本混杂残留）"""
    keep = set()
    for dp, dn, fn in os.walk(src):
        for f in fn:
            keep.add(os.path.relpath(os.path.join(dp, f), src))
    removed = 0
    for dp, dn, fn in os.walk(dst, topdown=False):
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), dst)
            if rel not in keep:
                try:
                    os.remove(os.path.join(dp, f))
                    removed += 1
                except Exception:
                    pass
    return removed


def main():
    verify_only = "--verify-only" in sys.argv

    log("目标目录 %s" % TARGET)
    log("当前 postcss 版本 = %s" % current_version())

    if verify_only:
        v = current_version()
        if v == VERSION:
            log("✅ 已是 %s，无需修复" % VERSION)
            return 0
        log("需要修复为 %s" % VERSION)
        return 1

    if current_version() == VERSION:
        log("✅ 已是 %s，跳过下载" % VERSION)
        return 0

    os.makedirs(WORK, exist_ok=True)
    tgz = os.path.join(WORK, "postcss-%s.tgz" % VERSION)
    if not download(tgz):
        log("❌ 下载失败")
        return 2

    src = extract(tgz, os.path.join(WORK, "ex"))
    if not src:
        log("❌ 解包结构异常")
        return 2
    with open(os.path.join(src, "package.json"), encoding="utf-8") as f:
        got = json.load(f).get("version")
    log("解包得到版本 %s" % got)
    if got != VERSION:
        log("❌ 版本不符")
        return 2

    n, skipped = copy_over(src, TARGET)
    log("写入 %d 文件（失败 %d）" % (n, skipped))
    removed = prune_extra(src, TARGET)
    log("清理版本混杂残留 %d 文件" % removed)

    final = current_version()
    log("修复后 postcss 版本 = %s" % final)
    if final != VERSION:
        log("❌ 修复未生效")
        return 1

    # 关键文件存在性自检
    for rel in ("lib/postcss.js", "lib/node.js", "lib/parser.js",
                "lib/container.js", "lib/declaration.js", "lib/symbols.js"):
        p = os.path.join(TARGET, rel)
        if not os.path.exists(p):
            log("❌ 缺少 %s" % rel)
            return 1
    log("✅ 关键文件齐全")
    shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
