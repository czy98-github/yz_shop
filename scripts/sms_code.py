#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小程序端短信验证码速查 / 一键登录辅助

背景：后端 application-local.yaml 里 sms.mock-enable=true，
      短信走 Mock 模式——不会真发短信，验证码固定为 9999。
      验证码会写入数据库表 system_sms_code，可在本脚本中直接读出。

用法：
  python3 scripts/sms_code.py                 # 查最近的验证码记录
  python3 scripts/sms_code.py 15136175246     # 查指定手机号的最新验证码
  python3 scripts/sms_code.py 15136175246 --login   # 顺便实测登录，验证链路
"""
import os
import subprocess
import sys
import json
import urllib.request

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
MYSQL = os.path.join(WS, ".toolchain/mysql/mysql-8.4.11-macos15-x86_64/bin/mysql")
SOCK = "/tmp/mysql-deli.sock"
DB = "yixiang-drink-open"


def mysql_query(sql):
    """执行 SQL 并返回行列表（tab 分隔）"""
    cmd = [MYSQL, "--socket=" + SOCK, "-u", "root", "-proot", "-D", DB, "-N", "-e", sql]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        out = [l for l in r.stdout.splitlines() if l.strip()]
        return out
    except Exception as e:
        print("  ❌ 查询失败:", e)
        return []


def lan_ip():
    try:
        r = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return ""


def get_base_url():
    """从小程序 config/index.js 读取当前生效的 API 地址"""
    p = os.path.join(WS, "yshop-drink/yshop-drink-uniapp-vue3/config/index.js")
    try:
        for line in open(p, encoding="utf-8", errors="ignore"):
            if line.strip().startswith("const LAN_API_URL"):
                return line.split("=", 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return ""


def post_json(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "tenant-id": "1"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_login = "--login" in sys.argv
    mobile = args[0] if args else None

    base = get_base_url()
    ip = lan_ip()

    print()
    print("=" * 64)
    print("  小程序端登录辅助 · 2026-11-02")
    print("=" * 64)
    print()
    print("  登录方式说明：")
    print("    ✅ 手机号 + 短信验证码  —— 可用（本脚本辅助）")
    print("    ❌ 微信手机号快捷登录   —— 不可用（需真实 AppID/secret，且需匹配）")
    print("    ❌ 手机号 + 密码        —— 小程序端【没有】此方式（那是管理端的）")
    print()
    print("  📌 验证码固定为 9999（后端 sms.mock-enable=true，短信不会真发）")
    print()
    print("  当前 API 地址 :", base or "（未读到）")
    print("  本机局域网 IP :", ip or "（未读到）")
    if base and ip and ip not in base:
        print("  ⚠️  警告：API 地址中的 IP 与本机当前 IP 不一致！")
        print("      请先执行： python3 scripts/sync_ip.py  然后重新编译小程序")
    print()

    # ---- 查验证码 ----
    print("-" * 64)
    print("  最近验证码记录（来自 system_sms_code）")
    print("-" * 64)
    where = "WHERE mobile='%s'" % mobile if mobile else ""
    rows = mysql_query(
        "SELECT id,mobile,code,used,create_time FROM system_sms_code %s "
        "ORDER BY id DESC LIMIT 8;" % where
    )
    if not rows:
        print("  （无记录）")
        if mobile:
            print("  → 请先在小程序里点「获取验证码」，再回来查")
    else:
        print("  %-6s %-14s %-6s %-5s %-20s" % ("ID", "手机号", "验证码", "已用", "创建时间"))
        for r in rows:
            f = r.split("\t")
            if len(f) >= 5:
                used = "是" if f[3] == "1" else "否"
                mark = "" if f[3] == "1" else "  ← 可用"
                print("  %-6s %-14s %-6s %-5s %-20s%s" % (f[0], f[1], f[2], used, f[4], mark))
    print()

    # ---- 发码 + 登录实测 ----
    if mobile and do_login:
        print("-" * 64)
        print("  实测链路：发码 → 取码 → 登录")
        print("-" * 64)
        api = base or ("http://%s:48081/app-api" % ip)
        try:
            r = post_json(api + "/member/auth/send-sms-code", {"mobile": mobile, "scene": 1})
            print("  ① 发送验证码 :", "成功" if r.get("code") == 0 else "失败 %s" % r)
            rows2 = mysql_query(
                "SELECT code FROM system_sms_code WHERE mobile='%s' ORDER BY id DESC LIMIT 1;" % mobile
            )
            code = rows2[0].strip() if rows2 else "9999"
            print("  ② 数据库取码 :", code)
            r2 = post_json(api + "/member/auth/sms-login", {"mobile": mobile, "code": code})
            if r2.get("code") == 0:
                d = r2.get("data") or {}
                ui = d.get("userInfo") or {}
                print("  ③ 登录结果   : ✅ 成功")
                print("       userId    =", d.get("userId"))
                print("       nickname  =", ui.get("nickname"))
                print("       token     =", (d.get("accessToken") or "")[:16], "...")
            else:
                print("  ③ 登录结果   : ❌ 失败 ->", r2)
        except Exception as e:
            print("  ❌ 请求异常:", str(e)[:100])
        print()

    print("=" * 64)
    print("  下一步：小程序登录页输入手机号 → 点「获取验证码」→ 输入 9999")
    print("          别忘了勾选下方的《用户协议》复选框，否则无法提交")
    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
