"""场景题定稿前修订：为被改批次生成 v3 文件（保留 v1/v2 作审计痕迹）。

1. 补参考答案缺口：build_judge_probes.py 的映射发现 10 个要点在参考答案里没写到
   （data/scenarios/judge_probes/reference_gaps.md）。每处只补一两句，内容只取该要点自身的文字，
   不引入要点以外的新主张；要点、权重、扣分项、高危操作都不动。
2. 待核验项分诊（data/scenarios/residuals_triage.csv）后的小修：只改不计分的 source_note。

用法：uv run python scripts/apply_freeze_fixes.py
生成：data/scenarios/drafts/<batch>.v3.json（仅被改批次）；随后需重跑 merge_scenario_drafts.py，
再在有百炼 key 的机器上重跑 build_judge_probes.py segment / build（只重切参考答案变了的题）。
"""
import json
from pathlib import Path

DRAFTS = Path(__file__).resolve().parents[1] / "data/scenarios/drafts"


def load(batch):
    return json.loads((DRAFTS / f"{batch}.v2.json").read_text())


def save(batch, data):
    (DRAFTS / f"{batch}.v3.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))


def Q(data, idx):
    return [q for q in data["questions"] if q["local_idx"] == idx][0]


def P(q, pid):
    return [p for p in q["rubric_points"] if p["id"] == pid][0]


def after(q, anchor, added, field="reference_answer"):
    """在 anchor 之后插入 added；anchor 必须唯一出现。"""
    assert q[field].count(anchor) == 1, f"锚点不唯一或缺失于 {field}: {anchor[:40]}"
    q[field] = q[field].replace(anchor, anchor + added)


# ---------------- diag-ran：SC-D01 P8 / SC-D02 P8 / SC-D07 P8 ----------------
d = load("diag-ran")
after(Q(d, 1), "保留变更前后配置备份以便再次回退。",
      "后续改进：RLF 类参数调整须有场景论证，先小范围试点，变更单附验证指标。")
after(Q(d, 2), "异常则删除新增邻区回退。",
      "流程上把新站开通的双向邻区核对纳入开通清单，必要时在受控范围内启用 ANR 并审核其结果。")
after(Q(d, 7), "指标回升后再推开",
      "，用接入成功率、平均前导次数和上行 RSSI 的前后对比验证效果，并保留回退方案")
save("diag-ran", d)

# ---------------- diag-transport：SC-D16 P3 ----------------
d = load("diag-transport")
after(Q(d, 4), "防火墙入向 ICMP 丢弃同步增长。",
      "排除：IPsec SA 正常且小包能通，不是隧道或 SA 故障；改走原路径一切正常，不是服务器或应用故障；"
      "丢包随包长阶跃（1400 以下全通、1420 以上稳定不通）而非随机出现，不是链路质量丢包。")
save("diag-transport", d)

# ---------------- diag-oam：SC-D20 P7 ----------------
d = load("diag-oam")
after(Q(d, 3), "通知客服回复投诉用户。",
      "后续：路由策略变更前后增加按目的地址段的时延与重传基线监测和回归验证，把此类变更纳入影响评估。")
save("diag-oam", d)

# ---------------- cons-a：SC-C01 P8 ----------------
d = load("cons-a")
after(Q(d, 1), "04:00 后继续观察至少一个业务高峰后才拆 B。",
      "变更管理上，割接期间冻结同池及相关网元的其他变更，提前通知 HSS、SGW、计费、客服与值守团队，明确指挥与联络机制。")
save("cons-a", d)

# ---------------- cons-b：SC-C10 P4 source_note（不计分） ----------------
d = load("cons-b")
q = Q(d, 4)  # SC-C10：条号凭记忆引用，去掉条号即无需核对；计分文字只写“不少于六个月”，不受影响
assert q["title"].startswith("日志与性能数据"), q["title"]
P(q, "P4")["source_note"] = P(q, "P4")["source_note"].replace(
    "《网络安全法》第二十一条要求留存网络日志不少于六个月", "《网络安全法》关于留存网络日志不少于六个月的规定（条号未核对）")
assert "第二十一条" not in P(q, "P4")["source_note"]
save("cons-b", d)

# ---------------- supp-a：SC-D23 P3 / SC-D24 P4 / SC-D25 P7 / SC-D26 P4 ----------------
d = load("supp-a")
after(Q(d, 1), "拒绝注册。",
      "#62 的触发条件是注册请求的 Requested NSSAI 中没有任何一个 S-NSSAI 可用：该行业终端只请求切片 A，"
      "而 AMF-1 在本 TA 不支持切片 A，请求的切片全部不可用，所以拒绝；若只是部分请求切片不可用，"
      "AMF 应接受注册并返回不含该切片的 Allowed NSSAI，而不是拒绝。")
after(Q(d, 2), "而不是无线质差或呼叫失败。",
      "VoLTE 的 SIP 信令走 QCI 5 承载，语音媒体（RTP）走 QCI 1 的 GBR 承载。")
after(Q(d, 3), "注意不要在业务时段直接重启 MME-A 或 HSS。",
      "后续：S6a 链路与 Diameter 对端增加监控告警与冗余，MME 池健康与容量纳入巡检。")
after(Q(d, 4), "闲时资源充裕则正常。",
      "背景：5QI 决定资源类型（GBR/非 GBR）、优先级与时延预算；保障比特率（GFBR）只由 GBR QoS Flow 提供，"
      "非 GBR 的缺省 5QI（通常为 5QI 9）没有每流保障，只受 Session-AMBR/UE-AMBR 上限约束。")
save("supp-a", d)

print("已生成 v3：diag-ran, diag-transport, diag-oam, cons-a, cons-b, supp-a")
