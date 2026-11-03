# -*- coding: utf-8 -*-
"""特色菜订餐小程序 · 运营增长方案关键数值核算"""

# ---------- 1. 基座实测基线（种子数据） ----------
base = dict(shops=2, products=11, orders=7, users=2, status_rows=105, menus=530,
            count_orderCount=7, count_priceCount=12.01, count_goodsCount=11, count_userCount=2)
print("== 1. 基座实测基线 ==")
for k, v in base.items():
    print(f"  {k:22s} = {v}")
print("  注：以上为 yshop 种子数据，非真实经营数据；运营口径基线须在试点首日重采。")

# ---------- 2. 在册规模与渗透目标 ----------
ROSTER = 2000
BG1_bind_rate = 0.60
BG2_week_active_rate = 0.35
BG3_wpo_week = 3000
print("\n== 2. 渗透与 WPO 分解 ==")
bound = ROSTER * BG1_bind_rate
week_active = ROSTER * BG2_week_active_rate
print(f"  BG1 绑定人数 = {ROSTER} x {BG1_bind_rate:.0%} = {bound:.0f} 人")
print(f"  BG2 周活下单员工 = {ROSTER} x {BG2_week_active_rate:.0%} = {week_active:.0f} 人/周")
print(f"  WPO 3000 单/周 ÷ 周活 {week_active:.0f} 人 = 人均 {BG3_wpo_week/week_active:.2f} 单/周/人")
# 达成 WPO 所需绑定率（按人均 4.3 单/周 反推）
per_capita = BG3_wpo_week / week_active
need_bound = BG3_wpo_week / per_capita
print(f"  → 需绑定 >= {need_bound:.0f} 人（= 在册 {need_bound/ROSTER:.1%}）才能达成 WPO 3000")
# 达成 WPO 所需周活（按人均 3.5 单/周）
for pc in (3.0, 3.5, 4.0, 4.3):
    print(f"    人均 {pc:.1f} 单/周 → 需周活 {BG3_wpo_week/pc:.0f} 人（占在册 {BG3_wpo_week/pc/ROSTER:.1%}）")

# ---------- 3. 订单量与容量换算（对齐运维方案 §6.1：峰值 24 QPS / 目标 36 QPS / 日订单 3600） ----------
print("\n== 3. 容量换算（运维基线：日订单 3600、峰值 24 QPS、容量目标 36 QPS）==")
for label, bound_n in (("V1.0 试点(1园区/2部门)", 80), ("V1.0 上线2周", 1000), ("首月稳态 BG1", bound)):
    wk_orders = bound_n * per_capita
    day_orders = wk_orders / 5
    # 30% 集中在 11:00-11:30 → 0.5 单/s；按 3x 尖峰
    peak = (day_orders * 0.30) / (30 * 60) * 3
    print(f"  {label:24s} 绑定{bound_n:5.0f}人 → 周单{wk_orders:7.0f} 日单{day_orders:6.0f} 峰值≈{peak:5.2f} QPS"
          f" {'❌超5000需48h通知运维' if day_orders>5000 else '✅远低于运维基线'}")

# ---------- 4. 派单/取餐时长与漏斗 ----------
print("\n== 4. 漏斗反推（PRD 2.4 健康阈值）==")
funnel = [("app_launch→dish_list_expose", 0.95), ("dish_list_expose→cart_add", 0.12),
          ("cart_add→order_submit", 0.60), ("order_submit→pay_success", 0.99),
          ("pay_success→order_complete", 0.90)]
cum = 1.0
for name, r in funnel:
    cum *= r
    print(f"  {name:36s} 段转化 {r:6.1%} → 端到端 {cum:7.3%}")
print(f"  → 端到端每 100 次启动产出 {cum*100:.1f} 笔核销单")
print(f"  → 若要 WPO 3000/周，需 app_launch ≈ {3000/cum:,.0f} 次/周（{3000/cum/2000:.1f} 倍在册人数）")

# ---------- 5. A/B 样本量（比例检验，双侧） ----------
def n_two_prop(p1, p2, alpha=0.05, power=0.8):
    from math import sqrt
    za = 1.959963985; zb = 0.8416212336
    pbar = (p1 + p2) / 2
    return (za + zb) ** 2 * 2 * pbar * (1 - pbar) / (p2 - p1) ** 2
print("\n== 5. A/B 样本量（α=0.05, power=0.8, 双侧）==")
for p1, p2, label in ((0.88, 0.92, "取餐率 88%→92%"), (0.60, 0.70, "绑定→首单 60%→70%"),
                      (0.03, 0.015, "弃单率 3%→1.5%"), (0.12, 0.16, "曝光→加购 12%→16%")):
    n = n_two_prop(p1, p2)
    print(f"  {label:22s} 每组需 {n:,.0f} 核销单 ≈ {n/BG3_wpo_week:.1f} 个 WPO 周")

# ---------- 6. 工作日留存 / 流失分层阈值 ----------
print("\n== 6. 流失分层阈值（工作日口径）==")
layers = [("新用户流失", "绑定后 3 个工作日内未完成 1 次支付成功订单", "首单券/代订兜底/班组长提醒"),
          ("活跃用户衰退", "连续 2 周下单天数下降 ≥50%（且 >0）", "个性化菜品推送/口味回访"),
          ("沉默用户", "连续 10 个工作日无支付成功订单（≈2 个工作周）", "企微机器人 1 条 + 余额提醒"),
          ("深度流失", "连续 20 个工作日无支付成功订单（≈4 个工作周）", "短信（≤1 次/月）+ 花名册复核")]
for a, b, c in layers:
    print(f"  {a:8s} | {b:44s} | {c}")

# ---------- 7. 备餐预测与浪费/缺货 ----------
print("\n== 7. 备餐预测示例（红烧肉 · 周三）==")
hist = [40, 36, 44, 38]           # 近 4 周同星期三销量
w = [0.5, 0.3, 0.2]
base_qty = sum(h * wi for h, wi in zip(hist, w))
weekday_factor, event_factor, new_factor = 1.08, 1.0, 1.0
pred = base_qty * weekday_factor * event_factor * new_factor
prep = round(pred * 1.1)
print(f"  基准量 = {'+'.join(f'{h}x{wi}' for h,wi in zip(hist,w))} = {base_qty:.1f} 份")
print(f"  预测 = {base_qty:.1f} x {weekday_factor} x {event_factor} x {new_factor} = {pred:.1f} 份")
print(f"  安全余量 1.1 → 备餐 {prep} 份")
for actual in (prep, int(pred*0.8), int(pred*1.25)):
    waste = (prep - actual) / prep
    short = 1.0 if actual >= prep else 0.0
    print(f"    实际 {actual:3d} 份 → 浪费率 {waste:6.1%} | 售罄={'是' if actual>=prep else '否'} | 偏差 {abs(actual-pred)/pred:5.1%}")

# ---------- 8. 餐补消耗与预算 ----------
print("\n== 8. 餐补/预算量级测算 ==")
avg_order = 18.0
for n, label in ((1200, "首月稳态(绑定60%)"), (2000, "全量在册")):
    day_orders = n * per_capita / 5
    day_amt = day_orders * avg_order
    print(f"  {label:18s} 日单 {day_orders:6.0f} → 日餐补支出 ¥{day_amt:,.0f} → 月(21.7 工作日) ¥{day_amt*21.7:,.0f}")
print(f"  限额校验：单笔≤100、单日≤150 → 日上限 {2000*150:,.0f} 元，远高于实际支出，无需限流干预")

# ---------- 9. 召回成本 vs LTV ----------
print("\n== 9. 召回成本 / LTV 核算 ==")
weekly_spend = avg_order * 4.3
ltv_8w = weekly_spend * 8
print(f"  员工周均消费 ≈ ¥{weekly_spend:.0f}（客单价 ¥{avg_order} x {per_capita:.1f} 单/周）")
print(f"  8 周毛收入 ≈ ¥{ltv_8w:.0f}")
for inc in (0, 2, 5):
    print(f"  召回激励 ¥{inc}/人 → 成本占 8 周毛收入 {inc/ltv_8w:5.1%}"
          + ("  ✅≤30% 阈值" if inc/ltv_8w <= 0.30 else "  ❌超阈值，不做大批量召回"))

# ---------- 10. 工时节约（BG-4）----------
print("\n== 10. BG-4 工时节约 ==")
stalls, days, old_min, new_min = 2, 21, 15, 5
old_h = stalls * days * old_min / 60
new_h = stalls * days * new_min / 60
print(f"  群接龙汇总 {stalls}档口 x {days}工作日 x {old_min}分 = {old_h:.1f} 小时/周")
print(f"  CSV 对账后 = {stalls} x {days} x {new_min}分 = {new_h:.1f} 小时/周 → 节约 {(1-new_h/old_h):.0%}（目标 ≥50%）")
