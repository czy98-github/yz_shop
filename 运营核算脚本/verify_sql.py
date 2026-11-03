# -*- coding: utf-8 -*-
"""校验运营方案 SQL 引用的表/列在真实 DDL 中存在（yixiang-drink-open.sql）"""
import re, sys

DDL = "/Users/tristan/Documents/tencent/Workbuddy/MiniProgram/yshop-drink/yshop-drink-boot3/sql/yixiang-drink-open.sql"
sql_text = open(DDL, encoding='utf-8', errors='ignore').read()

schema = {}
for m in re.finditer(r"CREATE TABLE `([^`]+)` \((.*?)\n\) ENGINE=", sql_text, re.S):
    tbl, body = m.group(1), m.group(2)
    cols = set(re.findall(r"^\s*`([^`]+)`\s", body, re.M))
    schema[tbl] = cols

# 本方案新增（DDL 变更项，尚未存在于基座）
NEW = {
    "yshop_store_order": {"biz_date","dept_id","site_id","stall_id","source_type","completed_at",
                          "closed_at","cancelled_at","subscription_expired_at","operator_id",
                          "pay_channel","cancel_reason_code","close_reason_code","expired_reason_code"},
    "yshop_store_order_status": {"order_id"},
    "yshop_store_order_cart_info": {"biz_date","site_id","dept_id"},
    "yshop_user": {"emp_no","dept_id","site_id"},
}

def check(sql, tables_cols):
    """tables_cols: {table: [cols]}"""
    errs = []
    for tbl, cols in tables_cols.items():
        if tbl not in schema:
            errs.append(f"表不存在: {tbl}")
            continue
        avail = schema[tbl] | NEW.get(tbl, set())
        for c in cols:
            if c not in avail:
                errs.append(f"{tbl}.{c} 不存在")
    return errs

QUERIES = {
"Q1 日订餐趋势": {
 "sql": """SELECT DATE(o.create_time) AS biz_date, COUNT(*) AS order_cnt,
       SUM(CASE WHEN o.paid = 1 THEN 1 ELSE 0 END) AS paid_cnt,
       SUM(CASE WHEN o.status = 3 THEN 1 ELSE 0 END) AS completed_cnt,
       SUM(CASE WHEN o.paid = 1 AND o.status = 3 THEN o.pay_price ELSE 0 END) AS completed_amount,
       SUM(CASE WHEN o.status = 4 THEN 1 ELSE 0 END) AS closed_cnt,
       SUM(CASE WHEN o.status = 5 THEN 1 ELSE 0 END) AS cancelled_cnt,
       SUM(CASE WHEN o.status = 6 THEN 1 ELSE 0 END) AS sub_expired_cnt
FROM yshop_store_order o
WHERE o.deleted = b'0' AND o.create_time >= :begin AND o.create_time < :end
GROUP BY DATE(o.create_time) ORDER BY biz_date;""",
 "cols": {"yshop_store_order": ["create_time","paid","status","pay_price","deleted","id","uid","shop_id","order_id"]}},

"Q2 菜品销量TopN": {
 "sql": """SELECT c.product_id, c.title AS dish_name, SUM(c.number) AS qty,
       SUM(c.number * IFNULL(c.price,0)) AS amount, COUNT(DISTINCT c.oid) AS order_cnt
FROM yshop_store_order_cart_info c
JOIN yshop_store_order o ON o.id = c.oid AND o.deleted = b'0'
WHERE o.paid = 1 AND o.status = 3
  AND o.create_time >= :begin AND o.create_time < :end
GROUP BY c.product_id, c.title ORDER BY qty DESC LIMIT :topN;""",
 "cols": {"yshop_store_order_cart_info": ["product_id","title","number","price","oid"],
          "yshop_store_order": ["id","paid","status","create_time","deleted"]}},

"Q3 时段分布": {
 "sql": """SELECT HOUR(o.create_time) AS hh, COUNT(*) AS order_cnt,
       SUM(CASE WHEN o.status = 3 THEN 1 ELSE 0 END) AS completed_cnt
FROM yshop_store_order o
WHERE o.deleted = b'0' AND o.create_time >= :begin AND o.create_time < :end
GROUP BY HOUR(o.create_time) ORDER BY hh;""",
 "cols": {"yshop_store_order": ["create_time","status","deleted"]}},

"Q4 门店/园区维度": {
 "sql": """SELECT o.shop_id, IFNULL(s.name,'未知档口') AS shop_name,
       COUNT(*) AS order_cnt, SUM(o.pay_price) AS amount,
       COUNT(DISTINCT o.uid) AS emp_cnt
FROM yshop_store_order o
LEFT JOIN yshop_store_shop s ON s.id = o.shop_id
WHERE o.deleted = b'0' AND o.paid = 1 AND o.create_time >= :begin AND o.create_time < :end
GROUP BY o.shop_id, s.name ORDER BY amount DESC;""",
 "cols": {"yshop_store_order": ["shop_id","uid","pay_price","paid","create_time","deleted"],
          "yshop_store_shop": ["id","name","status","min_price","delivery_price","address","lng","lat"]}},

"Q5 三类断点归因": {
 "sql": """SELECT s.change_type, COUNT(*) AS cnt, COUNT(DISTINCT s.oid) AS order_cnt
FROM yshop_store_order_status s
JOIN yshop_store_order o ON o.id = s.oid AND o.deleted = b'0'
WHERE s.change_time >= :begin AND s.change_time < :end
  AND s.change_type IN ('timeout_close','user_cancel','subscription_expired','pickup_verified')
GROUP BY s.change_type;""",
 "cols": {"yshop_store_order_status": ["oid","change_type","change_time","change_message"],
          "yshop_store_order": ["id","deleted"]}},

"Q6 取餐率/弃单率/取消率": {
 "sql": """SELECT COUNT(*) AS submit_cnt,
       SUM(CASE WHEN o.paid = 1 THEN 1 ELSE 0 END) AS paid_cnt,
       SUM(CASE WHEN o.status = 3 THEN 1 ELSE 0 END) AS completed_cnt,
       SUM(CASE WHEN o.status = 4 THEN 1 ELSE 0 END) AS closed_cnt,
       SUM(CASE WHEN o.status = 5 THEN 1 ELSE 0 END) AS cancelled_cnt,
       SUM(CASE WHEN o.status = 6 THEN 1 ELSE 0 END) AS sub_expired_cnt
FROM yshop_store_order o
WHERE o.deleted = b'0' AND o.create_time >= :begin AND o.create_time < :end;""",
 "cols": {"yshop_store_order": ["paid","status","create_time","deleted"]}},

"Q7 工作日复购率(5工作日滚动)": {
 "sql": """WITH paid_day AS (
  SELECT o.uid AS uid, DATE(o.create_time) AS biz_date
  FROM yshop_store_order o
  WHERE o.deleted = b'0' AND o.paid = 1 AND o.create_time >= :begin AND o.create_time < :end
  GROUP BY o.uid, DATE(o.create_time)
), wd AS (
  SELECT DISTINCT biz_date FROM paid_day WHERE DAYOFWEEK(biz_date) BETWEEN 2 AND 6
), cal AS (
  SELECT biz_date, ROW_NUMBER() OVER (ORDER BY biz_date) AS wd_idx FROM wd
), j AS (
  SELECT p.uid, p.biz_date, c.wd_idx FROM paid_day p JOIN cal c ON c.biz_date = p.biz_date
), agg AS (
  SELECT uid, COUNT(*) AS active_days FROM j GROUP BY uid
)
SELECT COUNT(*) AS bound_active_cnt,
       SUM(CASE WHEN a.active_days >= 3 THEN 1 ELSE 0 END) AS light_repeat_cnt,
       SUM(CASE WHEN a.active_days >= 5 THEN 1 ELSE 0 END) AS heavy_repeat_cnt
FROM agg a;""",
 "cols": {"yshop_store_order": ["uid","paid","create_time","deleted"]}},

"Q8 沉默/流失名单": {
 "sql": """SELECT u.id AS uid, u.real_name, u.now_money,
       DATEDIFF(:today, MAX(o.create_time)) AS idle_workdays,
       COUNT(DISTINCT DATE(o.create_time)) AS active_days
FROM yshop_user u
LEFT JOIN yshop_store_order o ON o.uid = u.id AND o.paid = 1 AND o.deleted = b'0'
WHERE u.deleted = b'0' AND u.status = 1
GROUP BY u.id, u.real_name, u.now_money
HAVING active_days = 0 OR idle_workdays >= 10
ORDER BY idle_workdays DESC;""",
 "cols": {"yshop_user": ["id","real_name","now_money","deleted","status","mobile","login_date","pay_count","integral","level"],
          "yshop_store_order": ["uid","paid","create_time","deleted"]}},

"Q9 备餐预测(同星期几历史基准)": {
 "sql": """SELECT c.product_id, c.title AS dish_name,
       DAYOFWEEK(o.create_time) AS dow,
       COUNT(DISTINCT DATE(o.create_time)) AS sale_days,
       SUM(c.number) AS total_qty,
       ROUND(SUM(c.number) / COUNT(DISTINCT DATE(o.create_time)), 2) AS avg_qty_per_day
FROM yshop_store_order_cart_info c
JOIN yshop_store_order o ON o.id = c.oid AND o.deleted = b'0'
WHERE o.paid = 1 AND o.status = 3
  AND o.create_time >= :begin AND o.create_time < :end
GROUP BY c.product_id, c.title, DAYOFWEEK(o.create_time)
ORDER BY c.product_id, dow;""",
 "cols": {"yshop_store_order_cart_info": ["product_id","title","number","oid"],
          "yshop_store_order": ["id","paid","status","create_time","deleted"]}},

"Q10 餐补消耗与对账": {
 "sql": """SELECT DATE(o.pay_time) AS biz_date, o.pay_type,
       COUNT(*) AS order_cnt, SUM(o.pay_price) AS amount
FROM yshop_store_order o
WHERE o.deleted = b'0' AND o.paid = 1 AND o.pay_time >= :begin AND o.pay_time < :end
GROUP BY DATE(o.pay_time), o.pay_type ORDER BY biz_date;""",
 "cols": {"yshop_store_order": ["pay_time","pay_type","paid","pay_price","deleted","refund_price","refund_status"]}},

"Q11 异常订单风控扫描": {
 "sql": """SELECT o.id, o.order_id, o.uid, o.total_num, o.pay_price, o.status, o.create_time,
       (SELECT COUNT(*) FROM yshop_store_order_status s
         WHERE s.oid = o.id AND s.change_type = 'pickup_verified') AS verify_cnt
FROM yshop_store_order o
WHERE o.deleted = b'0' AND o.paid = 1
  AND o.create_time >= :begin
  AND (o.total_num >= 5 OR o.pay_price < 1
       OR o.status NOT IN (1,2,3,4,5,6));""",
 "cols": {"yshop_store_order": ["id","order_id","uid","total_num","pay_price","status","create_time","paid","deleted","real_name"],
          "yshop_store_order_status": ["oid","change_type"]}},

"Q12 菜品销售与商品主数据对齐": {
 "sql": """SELECT p.id, p.store_name, p.shop_id, p.cate_id, p.price, p.stock, p.sales,
       p.is_show, p.is_hot, p.is_best, p.is_new, c.name AS cate_name
FROM yshop_store_product p
LEFT JOIN yshop_store_product_category c ON c.id = CAST(p.cate_id AS UNSIGNED)
WHERE p.deleted = b'0' AND p.shop_id = :shopId
ORDER BY p.is_show DESC, p.sales DESC;""",
 "cols": {"yshop_store_product": ["id","store_name","shop_id","cate_id","price","stock","sales","is_show","is_hot","is_best","is_new","deleted","cost","create_time"],
          "yshop_store_product_category": ["id","name","parent_id","status","shop_id","deleted"]}},

"Q13 REQ-01 固定菜品占比(5工作日滑动)": {
 "sql": """WITH cal AS (
  SELECT d AS biz_date, ROW_NUMBER() OVER (ORDER BY d) AS wd_idx
  FROM (SELECT DISTINCT DATE(create_time) AS d FROM yshop_store_order
         WHERE deleted = b'0' AND paid = 1 AND status = 3) x
  WHERE DAYOFWEEK(x.d) BETWEEN 2 AND 6
), day_dish AS (
  SELECT o.uid AS uid, DATE(o.create_time) AS biz_date,
         GROUP_CONCAT(DISTINCT c.product_id ORDER BY c.product_id) AS dish_set
  FROM yshop_store_order o
  JOIN yshop_store_order_cart_info c ON c.oid = o.id
  WHERE o.deleted = b'0' AND o.paid = 1 AND o.status = 3
  GROUP BY o.uid, DATE(o.create_time)
), j AS (
  SELECT dd.uid, dd.dish_set, cal.wd_idx FROM day_dish dd JOIN cal ON cal.biz_date = dd.biz_date
), runs AS (
  SELECT uid, dish_set,
    ROW_NUMBER() OVER (PARTITION BY uid, dish_set ORDER BY wd_idx)
  - ROW_NUMBER() OVER (PARTITION BY uid ORDER BY wd_idx) AS grp
  FROM j
)
SELECT COUNT(DISTINCT CASE WHEN r.run_len >= 5 THEN r.uid END) AS fixed5_uid,
       COUNT(DISTINCT r.uid) AS total_uid
FROM (SELECT uid, dish_set, grp, COUNT(*) AS run_len FROM runs
       GROUP BY uid, dish_set, grp) r;""",
 "cols": {"yshop_store_order": ["uid","paid","status","create_time","deleted"],
          "yshop_store_order_cart_info": ["oid","product_id"]}},
}

print("== 表结构解析 ==")
print(f"  解析到 {len(schema)} 张表")
print("\n== SQL 引用校验 ==")
fail = 0
for name, q in QUERIES.items():
    errs = check(q["sql"], q["cols"])
    tables = sorted(set(re.findall(r"\b(yshop_[a-z_]+)\b", q["sql"])))
    if errs:
        fail += 1
        print(f"  ❌ {name}: " + "; ".join(errs))
    else:
        print(f"  ✅ {name:34s} 引用表: {', '.join(tables)}")
print(f"\n结果: {len(QUERIES)-fail}/{len(QUERIES)} 条 SQL 通过列存在性校验")

print("\n== 基座已有 vs 需新增 DDL 列 ==")
for tbl, cols in NEW.items():
    have = sorted(c for c in cols if c in schema.get(tbl, set()))
    need = sorted(c for c in cols if c not in schema.get(tbl, set()))
    print(f"  {tbl}: 已存在 {have if have else '无'} | 需新增 {need}")
sys.exit(1 if fail else 0)
