# -*- coding: utf-8 -*-
"""修正版：员工·工作日 级规范漏斗（分母单位统一）"""
WPO_WEEK, WORKDAYS, ROSTER = 3000, 5, 2000
print("== 修正后的规范漏斗（分母统一为「员工·日」，每层以员工数计）==")
E5 = WPO_WEEK / WORKDAYS
E4 = E5 / 0.90          # 支付 -> 核销 90%（PRD 取餐率目标）
E3 = E4 / 0.99          # 提交 -> 支付 99%
E2 = E3 / 0.70          # 加购 -> 提交 70%（员工级）
E1 = E2 / 0.80          # 曝光 -> 加购 80%（员工级）
rows = [("E1 菜单曝光员工", E1, "占在册", E1/ROSTER),
        ("E2 加购员工",     E2, "E1→E2", E2/E1),
        ("E3 提交订单员工", E3, "E2→E3", E3/E2),
        ("E4 支付成功员工", E4, "E3→E4", E4/E3),
        ("E5 核销完成员工", E5, "E4→E5", E5/E4)]
for name, v, k, r in rows:
    print(f"  {name:16s} = {v:7.0f} 人/工作日   {k:8s} = {r:6.1%}")
print(f"\n  校验: E5 x {WORKDAYS} 工作日 = {E5*WORKDAYS:.0f} 单/周 = WPO 目标 {WPO_WEEK} ✅")
print(f"  一致性: E1 = {E1:.0f} ≈ 绑定人数 {ROSTER*0.60:.0f}（在册 60%）→ 绑定员工日均打开 1 次 ✅")
print(f"  断点: 员工级加购->提交 仅 {E3/E2:.0%}（事件级 60% 同向），是最大可优化段")

print("\n== 灰度期(V1.0 上线2周) 折算 ==")
for label, bound in (("试点 1 园区/2 部门", 80), ("上线 2 周（绑定 50%）", 1000)):
    scale = bound / (ROSTER*0.60)
    print(f"  {label:22s} 绑定{bound:5d}人 → E5≈{E5*scale:5.0f} 人/日 → WPO≈{E5*scale*WORKDAYS:5.0f} 单/周"
          f" {'✅达 PRD V1.0 门槛(≥500)' if E5*scale*WORKDAYS>=500 else '⚠️未达 500 单/周'}")

print("\n== 三类断点分母（红线二/三）：提交订单 N = 支付 + CLOSED + CANCELLED + SUBSCRIPTION_EXPIRED ==")
N = E3
for label, r in (("支付成功", 0.985), ("超时未付 CLOSED（弃单）", 0.025), ("用户取消 CANCELLED", 0.030),
                 ("预排过期 SUBSCRIPTION_EXPIRED(V1.2)", 0.005)):
    pass
# 用目标反推：支付 99% + 弃单 2.5% + 取消 3% + 预排 0.5% = 105% -> 归一化到 100%
raw = [("支付成功", 0.99), ("超时未付 CLOSED", 0.025), ("用户取消 CANCELLED", 0.03), ("预排过期 SUBSCRIPTION_EXPIRED", 0.005)]
tot = sum(v for _, v in raw)
print(f"  日提交订单 N = {N:.0f}")
for label, v in raw:
    print(f"    {label:32s} 目标占比 {v/tot:6.2%} → {N*v/tot:5.1f} 单/日")

print("\n== 工作日留存/复购口径与目标 ==")
def rolls(days, target):
    return f"最近 {days} 个工作日内有 >= {target} 天支付成功"
for label, days, thr, tgt in (("工作日复购率（轻度）", 5, 3, "≥65%"),
                              ("工作日复购率（重度）", 5, 5, "≥40%"),
                              ("新用户 W1 留存", 5, 1, "≥60%"),
                              ("新用户 W2 留存", 10, 1, "≥50%"),
                              ("新用户 W4 留存", 20, 1, "≥40%")):
    print(f"  {label:18s} 定义: {rolls(days,thr):34s} 目标 {tgt}")
print("  自然日 DAU/MAU 仅辅助：周末无订单 → 自然日 MAU 会系统性低估 5/7，禁止用其做流失判定")
