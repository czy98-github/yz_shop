import os, subprocess, time, shutil

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
APP = WS + "/yshop-drink/yshop-drink-vue3"
NM = os.path.join(APP, "node_modules")
CACHE = WS + "/.toolchain/npm-cache"

hidden = os.path.join(NM, ".package-lock.json")
print("隐藏锁文件存在:", os.path.exists(hidden))
if os.path.exists(hidden):
    print("  大小: %d 字节" % os.path.getsize(hidden))
    try:
        os.remove(hidden)
        print("  ✅ 已删除 —— 下次 npm install 将重新校验并补齐缺失文件")
    except Exception as e:
        print("  ❌ 删除失败: %r" % e)
        # 改名方式
        bak = hidden + ".bak"
        try:
            os.rename(hidden, bak)
            print("  ✅ 已改名为 %s" % os.path.basename(bak))
        except Exception as e2:
            print("  ❌ 改名也失败: %r" % e2)

# 同时清理 npm 装到一半留下的 .xxx-xxxx 临时目录
tmpdirs = [d for d in os.listdir(NM) if d.startswith(".") and "-" in d and os.path.isdir(os.path.join(NM, d))]
print("")
print("清理 npm 半成品临时目录: %d 个" % len(tmpdirs))
for d in tmpdirs[:20]:
    p = os.path.join(NM, d)
    n = sum(len(f) for _, _, f in os.walk(p))
    try:
        shutil.rmtree(p, ignore_errors=True)
        print("   🗑️  %-28s (%d 文件)" % (d, n))
    except Exception as e:
        print("   ⚠️  %-28s 删除失败 %r" % (d, e))

# 统计 node_modules 大小
total = 0
cnt = 0
for root, dirs, files in os.walk(NM):
    cnt += len(files)
print("")
print("node_modules 当前: %d 个目录项, %d 个文件" % (len(os.listdir(NM)), cnt))
