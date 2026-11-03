"""演示前自检：一次性验证四层就绪状态"""
import json, os, socket, subprocess, urllib.request, urllib.error

for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

WS = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram"
BASE = "http://127.0.0.1:48081"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
rows = []

def req(path, method="GET", data=None, headers=None, timeout=20):
    h = {"User-Agent": "Mozilla/5.0"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    try:
        with opener.open(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:
        return -1, repr(e)

def j(t):
    try:
        return json.loads(t)
    except Exception:
        return {}

def port_open(p):
    s = socket.socket(); s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", p)); return True
    except Exception:
        return False
    finally:
        s.close()

def lan_ip():
    try:
        r = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return ""

IP = lan_ip()
print("=" * 78)
print(" 演示前自检 · %s" % __import__("time").strftime("%Y-%m-%d %H:%M:%S"))
print(" 局域网 IP: %s" % IP)
print("=" * 78)

print("\n【1】端口监听")
for name, p in [("MySQL", 3306), ("Redis", 6379), ("后端", 48081), ("管理端", 3000)]:
    ok = port_open(p)
    print("  %s %-8s :%d" % ("✅" if ok else "❌", name, p))

print("\n【2】后端健康")
code, body = req("/actuator/health")
d = j(body)
print("  %s /actuator/health -> HTTP %s %s" % ("✅" if d.get("status") == "UP" else "❌", code, body[:60]))

print("\n【3】管理端登录（演示用主账号）")
code, body = req("/admin-api/system/auth/login", "POST", {"username": "admin", "password": "admin123"})
d = j(body)
token = (d.get("data") or {}).get("accessToken")
print("  %s admin/admin123 -> code=%s token=%s" % ("✅" if token else "❌", d.get("code"), "有" if token else "无"))
AH = {"Authorization": "Bearer %s" % token} if token else {}

print("\n【4】管理端核心接口")
for label, path in [
    ("用户列表", "/admin-api/system/user/page?pageNo=1&pageSize=5"),
    ("门店列表", "/admin-api/store/shop/page?pageNo=1&pageSize=5"),
    # 注意：管理端前端硬编码 isShow=1 & stock=1，直连 API 必须带上这两个参数，
    # 否则商品列表返回 total=0（并非缺陷，是前端默认筛选条件）
    ("商品列表", "/admin-api/product/store-product/page?pageNo=1&pageSize=5&isShow=1&stock=1"),
    ("订单列表", "/admin-api/order/store-order/page?pageNo=1&pageSize=5"),
    ("订单统计", "/admin-api/order/store-order/count"),
]:
    code, body = req(path, headers=AH)
    d = j(body)
    dd = d.get("data")
    extra = ""
    if isinstance(dd, dict):
        extra = "total=%s" % dd.get("total")
    elif isinstance(dd, list):
        extra = "list=%d" % len(dd)
    print("  %s %-10s code=%s %s" % ("✅" if d.get("code") == 0 else "❌", label, d.get("code"), extra))

print("\n【5】订单导出（演示要展示的真实文件）")
r = urllib.request.Request(BASE + "/admin-api/order/store-order/export-excel", headers=AH)
try:
    with opener.open(r, timeout=30) as resp:
        raw = resp.read()
    is_xlsx = raw[:2] == b"PK"
    print("  %s export-excel -> %d 字节  %s" % ("✅" if is_xlsx else "❌", len(raw),
          "真实 XLSX(ZIP魔数PK)" if is_xlsx else "非 xlsx"))
except Exception as e:
    print("  ❌ export-excel -> %r" % e)

print("\n【6】小程序端登录（演示用员工账号）")
code, body = req("/app-api/member/auth/login", "POST", {"mobile": "15136175246", "password": "Test@123456"})
d = j(body)
uid = (d.get("data") or {}).get("userId")
print("  %s 15136175246 -> code=%s uid=%s" % ("✅" if uid else "❌", d.get("code"), uid))
UH = {"Authorization": "Bearer %s" % (d.get("data") or {}).get("accessToken")} if uid else {}

print("\n【7】小程序端核心接口（需 shop_id=2）")
for label, path in [
    ("商品分类", "/app-api/product/products?shop_id=2"),
    ("商品详情", "/app-api/product/detail/15"),
    ("我的订单", "/app-api/order/list?type=0&status=-1&page=1&limit=3"),
]:
    code, body = req(path, headers=UH)
    d = j(body)
    dd = d.get("data")
    extra = ""
    if isinstance(dd, list):
        extra = "%d 项" % len(dd)
    elif isinstance(dd, dict):
        extra = "cartInfo=%d" % len(dd.get("cartInfo") or [])
    print("  %s %-10s code=%s %s" % ("✅" if d.get("code") == 0 else "❌", label, d.get("code"), extra))

print("\n【8】演示数据就绪度")
MY = WS + "/.toolchain/mysql/mysql-8.4.11-macos15-x86_64/bin/mysql"
def sql(q):
    p = subprocess.run([MY, "--socket=/tmp/mysql-deli.sock", "-u", "root", "-proot",
                        "-D", "yixiang-drink-open", "--default-character-set=utf8mb4", "-N", "-e", q],
                       capture_output=True, text=True, timeout=20)
    return "\n".join(l for l in p.stdout.splitlines()
                     if l.strip() and not l.startswith("mysql:") and "[Warning]" not in l)
for label, q in [
    ("订单总数", "SELECT COUNT(*) FROM yshop_store_order WHERE deleted=0"),
    ("订单商品明细", "SELECT COUNT(*) FROM yshop_store_order_cart_info"),
    ("订单状态流水", "SELECT COUNT(*) FROM yshop_store_order_status"),
    ("上架商品", "SELECT COUNT(*) FROM yshop_store_product WHERE is_show=1"),
    ("门店", "SELECT COUNT(*) FROM yshop_store_shop WHERE status=1"),
    ("用户地址", "SELECT COUNT(*) FROM yshop_user_address WHERE uid=11"),
    ("管理账号", "SELECT COUNT(*) FROM system_users"),
]:
    print("  %-14s %s" % (label, sql(q)))

print("\n" + "=" * 78)
print(" 自检结束")
print("=" * 78)
