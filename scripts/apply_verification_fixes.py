"""应用三票+逐题核验确认的修订，为被改批次生成 v2 文件（保留 v1 作审计痕迹）。

只改核验确认的问题；被 subagent 驳回的三票误判一律不动。
条款号无法离线确认处一律用文档级引用并标注"需人工核对"，不臆造编号。

用法：uv run python scripts/apply_verification_fixes.py
生成：data/scenarios/drafts/<batch>.v2.json（仅被改批次）；随后需重跑 merge_scenario_drafts.py。
"""
import json
from pathlib import Path

DRAFTS = Path(__file__).resolve().parents[1] / "data/scenarios/drafts"


def load(batch):
    return json.loads((DRAFTS / f"{batch}.v1.json").read_text())


def save(batch, data):
    (DRAFTS / f"{batch}.v2.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))


def Q(data, idx):
    return [q for q in data["questions"] if q["local_idx"] == idx][0]


def P(q, pid):
    return [p for p in q["rubric_points"] if p["id"] == pid][0]


def sub(q, field, old, new):
    assert q[field].count(old) >= 1, f"{q.get('id','?')} 未找到待替换片段于 {field}: {old[:40]}"
    q[field] = q[field].replace(old, new)


def suball(q, old, new, fields=("prompt", "root_cause", "reference_answer")):
    for f in fields:
        if old in q[f]:
            q[f] = q[f].replace(old, new)


# ---------------- supp-a：SC-D23(major) / SC-D24 / SC-D26 ----------------
d = load("supp-a")
q = Q(d, 1)  # SC-D23
sub(q, "prompt",
    "| 注册失败表现 | 切片 A 终端在 TAC-1 收到 5GMM 注册拒绝，原因值为 #62（No network slices available）；重试仍失败 |",
    "| 注册失败表现 | 切片 A 终端（单切片专用终端，注册请求的 Requested NSSAI 仅含切片 A）在 TAC-1 收到 5GMM 注册拒绝，原因值为 #62（No network slices available）；重试仍失败 |")
sub(q, "prompt",
    "| AMF-1 本地配置 | 三日前 AMF-1 做过一次扩容/版本相关的配置下发变更（工单评估为“无业务影响”）；变更后 AMF-1 在本 TAC 支持的 S-NSSAI 列表需核对 |",
    "| AMF-1 本地配置 | 三日前 AMF-1 做过一次扩容/版本相关的配置下发变更（工单评估为“无业务影响”） |")
q["root_cause"] = ("AMF-1 一次配置变更后，其在本跟踪区支持的 S-NSSAI 列表缺失切片 A；因该行业终端 Requested NSSAI "
                   "仅含切片 A，请求的切片全部不可用，AMF 遂以 5GMM #62（No network slices available）拒绝注册；"
                   "签约、NSSF、无线与其他 AMF 均正常。")
P(q, "P1")["text"] = ("定位根因为 AMF-1 按 TA 维护的 Supported S-NSSAI 列表在近期变更后缺失切片 A，"
                      "导致该切片在本 TAC 被判为不可用而拒绝注册。")
P(q, "P3")["text"] = ("说明 5GMM 原因值 #62（No network slices available）的含义与触发条件：当 UE 注册请求的 "
                      "Requested NSSAI 中没有任何一个 S-NSSAI 可用/被网络允许时触发（本场景行业终端 Requested NSSAI "
                      "仅含切片 A，AMF-1 在本 TA 缺失对切片 A 的支持，导致请求的全部切片不可用，故 #62）；"
                      "若仅部分请求切片不可用，AMF 应接受注册并返回不含该切片的 Allowed NSSAI，而非拒绝。")
P(q, "P3")["source_note"] = ("5GMM 原因值 #62 见 TS 24.501（5GMM cause IE 表）与注册拒绝流程；网络切片选择、"
                             "AMF 按 TA 维护 Supported S-NSSAI 并生成 Allowed NSSAI 的机制见 TS 23.501。"
                             "Configured NSSAI 为 UE 侧配置，与本机制无直接关系。具体章节/表号建议人工核对。")

q = Q(d, 2)  # SC-D24：媒体面网元更正（P-CSCF 是信令面，媒体面应为 SBC/TrGW）
suball(q, "SBC/P-CSCF", "SBC/TrGW")
P(q, "P3")["text"] = P(q, "P3")["text"].replace("SBC/P-CSCF", "SBC/TrGW")

q = Q(d, 4)  # SC-D26：软化"默认 5QI 9"无题干依据的断言
P(q, "P4")["text"] = ("说明 5QI 决定资源类型（GBR/non-GBR）、优先级与时延预算；有保障比特率（GFBR）由 GBR QoS Flow "
                      "提供，non-GBR（缺省 5QI，通常为 5QI 9）无每流保障，仅有 Session-AMBR/UE-AMBR 上限。")
save("supp-a", d)

# ---------------- diag-transport：SC-D16 / SC-D17 ----------------
d = load("diag-transport")
q = Q(d, 4)  # SC-D16：参考答案与题干现象矛盾
sub(q, "reference_answer", "表现为小包正常、大文件和 TLS 握手卡死",
    "表现为小包正常、大文件传输与 HTTPS 握手后的大包数据传输卡死（本题题干现象为握手完成后卡住）")
q = Q(d, 5)  # SC-D17：G.8271.1 引用不精确
P(q, "P1")["source_note"] = ("IEEE 1588v2 的往返路径对称假设；ITU-T G.8275.1（全定时支持 PTP profile）对路径不对称"
                             "需校准/补偿的要求；链路不对称对同步性能的影响框架见 G.8271 系列"
                             "（G.8271.1 性能平面/参考配置与网络限值）。")
save("diag-transport", d)

# ---------------- kpi-a：SC-K01 / SC-K02 / SC-K06 ----------------
d = load("kpi-a")
q = Q(d, 1)  # SC-K01：KPI 口径与协议阶段映射
P(q, "P2")["source_note"] = ("切换准备/执行/完成阶段划分见 TS 36.300；本题各成功率口径为题干“指标说明”自定义的运维 KPI"
                             "（相关 KPI 定义参见 TS 32.450/32.451 或厂商实现），与协议阶段非严格一一对应。")
q = Q(d, 2)  # SC-K02：与题干流量数据矛盾
sub(q, "reference_answer", "同样的流量吃更多 PRB",
    "即便流量下降（112→94GB）PRB 反而吃更多（每 PRB 承载效率下降）")
q = Q(d, 6)  # SC-K06：与题干"其余指标定义未变更"矛盾
sub(q, "reference_answer",
    "用户数约 +10%、RRC 建立成功率微升不是问题：版本说明里采样方式改了，流量持平，K1 无变化，是统计口径变化。",
    "用户数约 +10% 不是问题：版本说明里采样方式改了（10 秒→1 秒），流量持平、K1 无变化可佐证，是统计口径变化；RRC 建立成功率仅微升约 0.1pp，属正常波动，不是真实改善。")
P(q, "P5")["text"] = ("指出平均 RRC 连接用户数约 +10% 属采样方式调整的统计口径变化（流量持平、K1 无变化可佐证）；"
                      "RRC 建立成功率微升（≤0.1pp）为正常波动，二者均非真实业务增长或改善。")
P(q, "P4")["verifiability"] = "constructed"
P(q, "P4")["source_note"] = ("标准仅支撑 RLF/切换失败触发 RRC 重建立的机制（TS 36.331 §5.3.7 / TS 38.331 §5.3.11）；"
                             "“配置未恢复→切不出→重建立/掉话”为基于表内数据的推断。")
save("kpi-a", d)

# ---------------- cons-a：SC-C02 / SC-C05 ----------------
d = load("cons-a")
q = Q(d, 2)  # SC-C02：PCI 复用要求误挂 TS 38.211
P(q, "P8")["source_note"] = ("TS 38.211 定义 PCI 的构成与取值范围（0~1007）；PCI 冲突/混淆规避与邻区关系约束参见 "
                             "TS 38.300（NR; Overall description，ANR 相关章节），具体条款号未逐条核对。")
q = Q(d, 5)  # SC-C05：光功率不属 Y.1564 范围
P(q, "P6")["text"] = ("新链路验收分层测试：物理层（光功率、误码，用光功率计/OTDR 及光接口标准）与业务层"
                      "（时延、吞吐/丢包，按 ITU-T Y.1564 或 RFC 2544），达标后才承载业务。")
sub(q, "reference_answer", "用业务激活测试（如 ITU-T Y.1564）验证光功率、误码、时延和吞吐后再迁移",
    "用物理层测试（光功率、误码）和业务激活测试（如 ITU-T Y.1564，测时延和吞吐）验证后再迁移")
save("cons-a", d)

# ---------------- cons-b：SC-C07 / SC-C09 / SC-C12 ----------------
d = load("cons-b")
q = Q(d, 1)  # SC-C07：G.8271 引用过笼统
P(q, "P2")["source_note"] = ("TDD 基站间需时间/相位同步：空口同步精度要求见 3GPP TS 38.104/TS 38.133（NR，条款号需人工核对），"
                             "承载网相位同步分配见 ITU-T G.8271 系列（G.8271/G.8271.1/G.8272）。")
q = Q(d, 3)  # SC-C09：分段定位方法不应挂到 3GPP 名下
P(q, "P2")["source_note"] = ("接口划分：5G N3 见 3GPP TS 23.501/23.502，4G S1-U 见 TS 23.401；"
                             "按业务路径分段定位属运维方法，非标准规定内容。")
q = Q(d, 6)  # SC-C12：P3 非 TS 32.551 直接定义的量化指标
P(q, "P3")["verifiability"] = "common_sense"
P(q, "P3")["source_note"] = ("节能试点副作用监控的运维常识；ESM（节能管理）概念参见 3GPP TS 32.551 / TS 28.310，"
                             "具体条款号未核对。")
save("cons-b", d)

# ---------------- diag-ran：SC-D07 ----------------
d = load("diag-ran")
q = Q(d, 7)  # SC-D07：近点用户失败机理解释不清
sub(q, "reference_answer", "受影响的是所有未被最大发射功率限制的用户，所以信号满格的近点用户反而也连不上",
    "由于前导到达基站的接收电平≈目标接收功率、与路损基本无关，目标定得过低使近点（信号满格）与远点用户的前导都低于检测门限，故近点用户同样连不上")
save("diag-ran", d)

# ---------------- diag-oam：SC-D21 / SC-D22 ----------------
d = load("diag-oam")
q = Q(d, 4)  # SC-D21：USER_UNKNOWN 结果码出处
P(q, "P2")["source_note"] = "AIR/ULR 流程见 3GPP TS 29.272；USER_UNKNOWN(5001) 结果码定义见 TS 29.229（由 29.272 引用）。"
q = Q(d, 5)  # SC-D22：RFC 8446 §4.4.2 为 SHOULD，非绝对要求
P(q, "P1")["source_note"] = ("为使客户端能构建到受信根的证书链，服务端应随握手发送中间 CA 证书"
                             "（RFC 8446 第 4.4.2 节对证书链的表述为 SHOULD；TLS 1.2 参见 RFC 5246 第 7.4.2 节）。"
                             "本例客户端信任库缺中间 CA，故须由服务端补发。")
P(q, "P5")["source_note"] = "补全服务端证书链是标准做法（RFC 8446 第 4.4.2 节，表述为 SHOULD）；小范围先试通为变更管理通用原则。"
save("diag-oam", d)

print("已生成 v2：supp-a, diag-transport, kpi-a, cons-a, cons-b, diag-ran, diag-oam")
