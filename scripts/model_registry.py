"""被测模型注册：configs/models.yaml 的分组、每个模型在某个 mode 下的请求参数、对应的 API 客户端。

- main / thinking_only：经百炼（.env 的 LLM_BASE_URL / LLM_API_KEY），参数 = modes[mode] 再叠加条目里的 params[mode]。
- regression：精度回归的自部署模型（SGLang），经 regression_base_url（SSH 隧道）访问，参数只取条目里的 params[mode]，
  不与 modes 合并（百炼的 enable_thinking 顶层参数对 SGLang 无效，关思考改用 chat_template_kwargs）。
- opencode_go：经 OpenCode Go（.env 的 OPENCODE_API_KEY，Anthropic Messages 格式，Oct 15 晚思考对照用来跑百炼现金不够的
  qwen3.8-flash），参数只取条目里的 params[mode]；关思考用 thinking: {type: disabled}，开思考不传 thinking（服务端默认开、无预算上限）。
  条目里的 api_model 是 Go 上的模型名；模型 ID 加后缀与百炼区分，缓存、判分、分析都按这个 ID 分开。
"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "configs/models.yaml"
GROUPS = ("main", "thinking_only", "regression", "opencode_go")
GO_URL = "https://opencode.ai/inference/go/anthropic/v1/messages"


def load_cfg():
    return yaml.safe_load(MODELS.read_text(encoding="utf-8"))


def entries(cfg):
    """{模型 ID: (分组, 条目)}"""
    return {m["id"]: (g, m) for g in GROUPS for m in cfg.get(g) or []}


def params(cfg, model, mode):
    group, entry = entries(cfg)[model]
    own = (entry.get("params") or {}).get(mode)
    if group in ("regression", "opencode_go"):
        if own is None:
            raise SystemExit(f"{model} 没有 mode={mode} 的参数")
        return dict(own)
    return {**cfg["modes"][mode], **(own or {})}


def is_local(cfg, model):
    return entries(cfg)[model][0] == "regression"


class GoClient:
    """OpenCode Go 的 Anthropic Messages 流式调用；stream_chat 见到它就走 _stream_go。"""

    def __init__(self, api_model):
        from verify_three_vote import load_env
        load_env()
        self.api_model = api_model
        self.key = os.environ["OPENCODE_API_KEY"]


def make_client(cfg, model):
    from openai import OpenAI
    group, entry = entries(cfg)[model]
    if group == "opencode_go":
        return GoClient(entry["api_model"])
    if is_local(cfg, model):
        return OpenAI(base_url=cfg["regression_base_url"], api_key="EMPTY", timeout=1800)
    from verify_three_vote import load_env
    load_env()
    # 流式读超时 180 秒：思考期间推理 token 持续下发，不会误触；只防止流卡住不动（Oct 15 思考对照冒烟时卡过 20 分钟）
    return OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"], timeout=180)


STALL_S, TOTAL_S = 120, 2400


def stream_chat(client, req, extra, stall_s=STALL_S, total_s=TOTAL_S):
    """流式调用，返回 {content, reasoning, finish_reason, served_model, usage, ttft_s, ttfa_s, latency_s}。

    看门狗：连续 stall_s 秒没有新的 token、或总时长超过 total_s，就关掉连接并抛 TimeoutError（由调用方重试）。
    原因：Oct 15 思考对照冒烟时 qwen3.8-max 开思考的流会中途卡住，连接一直保持（读超时不触发），一次卡了 20 多分钟。
    """
    import threading
    import time
    if isinstance(client, GoClient):
        return _stream_go(client, req, extra, stall_s, total_s)
    out = {"content": "", "reasoning": "", "finish_reason": None, "served_model": None, "usage": None,
           "ttft_s": None, "ttfa_s": None}
    t0 = time.monotonic()
    last = [t0]
    stream = client.chat.completions.create(**req, extra_body=extra)
    stop, killed = threading.Event(), []

    def watchdog():
        while not stop.wait(5):
            now = time.monotonic()
            if now - last[0] > stall_s or now - t0 > total_s:
                killed.append(f"{'无新 token ' + str(stall_s) + ' 秒' if now - last[0] > stall_s else '总时长超 ' + str(total_s) + ' 秒'}")
                try:
                    stream.response.close()
                except Exception:  # noqa: BLE001
                    pass
                return

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        for chunk in stream:
            out["served_model"] = chunk.model or out["served_model"]
            if chunk.usage:
                out["usage"] = chunk.usage.model_dump()
            for ch in chunk.choices:
                # 百炼的推理字段是 reasoning_content；OpenCode Go 的 Chat Completions 是 reasoning
                c = ch.delta.content or ""
                r = getattr(ch.delta, "reasoning_content", None) or getattr(ch.delta, "reasoning", None) or ""
                now = time.monotonic()
                if c or r:
                    last[0] = now
                if (c or r) and out["ttft_s"] is None:
                    out["ttft_s"] = round(now - t0, 2)  # 首 token（含推理）
                if c and out["ttfa_s"] is None:
                    out["ttfa_s"] = round(now - t0, 2)  # 首个答案 token
                out["content"] += c
                out["reasoning"] += r
                out["finish_reason"] = ch.finish_reason or out["finish_reason"]
    except Exception:
        if killed:
            raise TimeoutError(f"看门狗中断：{killed[0]}") from None
        raise
    finally:
        stop.set()
    if killed:
        raise TimeoutError(f"看门狗中断：{killed[0]}")
    out["latency_s"] = round(time.monotonic() - t0, 2)
    return out


def _stream_go(client, req, extra, stall_s, total_s):
    """OpenAI 风格的 req 转成 Anthropic Messages 请求，解析 SSE；返回与 stream_chat 相同的字段。

    Go 不单独报思考 token：usage 的 reasoning_tokens 记 None，思考长度看 reasoning 字符数。
    文档要求自报 User-Agent、每个对话带固定的 x-opencode-session（这里每次调用是一个对话）。
    """
    import json
    import threading
    import time
    import uuid

    import httpx
    msgs = req["messages"]
    body = {"model": client.api_model, "max_tokens": req["max_tokens"], "stream": True,
            "messages": [m for m in msgs if m["role"] != "system"],
            **{k: req[k] for k in ("temperature", "top_p") if k in req}, **extra}
    system = [m["content"] for m in msgs if m["role"] == "system"]
    if system:
        body["system"] = system[0]
    headers = {"User-Agent": "telecom-om-eval/0.1", "x-opencode-session": uuid.uuid4().hex,
               "content-type": "application/json", "anthropic-version": "2023-06-01",
               "Authorization": f"Bearer {client.key}"}
    out = {"content": "", "reasoning": "", "finish_reason": None, "served_model": None, "usage": None,
           "ttft_s": None, "ttfa_s": None}
    t0 = time.monotonic()
    last, killed, stop = [t0], [], threading.Event()
    tin = tout = 0
    with httpx.stream("POST", GO_URL, headers=headers, json=body, timeout=httpx.Timeout(180, connect=30)) as r:
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.read().decode('utf-8', 'replace')[:300]}")

        def watchdog():
            while not stop.wait(5):
                now = time.monotonic()
                if now - last[0] > stall_s or now - t0 > total_s:
                    killed.append(f"无新 token {stall_s} 秒" if now - last[0] > stall_s else f"总时长超 {total_s} 秒")
                    r.close()
                    return

        threading.Thread(target=watchdog, daemon=True).start()
        try:
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                typ = ev.get("type")
                if typ == "message_start":
                    msg = ev.get("message") or {}
                    out["served_model"] = msg.get("model")
                    tin = (msg.get("usage") or {}).get("input_tokens") or 0
                elif typ == "content_block_delta":
                    d = ev.get("delta") or {}
                    c, rz = d.get("text") or "", d.get("thinking") or ""
                    now = time.monotonic()
                    if c or rz:
                        last[0] = now
                        if out["ttft_s"] is None:
                            out["ttft_s"] = round(now - t0, 2)
                    if c and out["ttfa_s"] is None:
                        out["ttfa_s"] = round(now - t0, 2)
                    out["content"] += c
                    out["reasoning"] += rz
                elif typ == "message_delta":
                    sr = (ev.get("delta") or {}).get("stop_reason")
                    out["finish_reason"] = {"end_turn": "stop", "max_tokens": "length"}.get(sr, sr)
                    u = ev.get("usage") or {}
                    tin = u.get("input_tokens") or tin
                    tout = u.get("output_tokens") or tout
                elif typ == "error":
                    raise RuntimeError(f"Go 返回错误：{json.dumps(ev, ensure_ascii=False)[:300]}")
        except Exception:
            if killed:
                raise TimeoutError(f"看门狗中断：{killed[0]}") from None
            raise
        finally:
            stop.set()
    if killed:
        raise TimeoutError(f"看门狗中断：{killed[0]}")
    out["usage"] = {"prompt_tokens": tin, "completion_tokens": tout, "completion_tokens_details": {"reasoning_tokens": None}}
    out["latency_s"] = round(time.monotonic() - t0, 2)
    return out
