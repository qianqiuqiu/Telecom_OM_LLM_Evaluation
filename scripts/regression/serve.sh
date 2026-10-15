#!/bin/bash
# 精度回归：在 AutoDL 上用 SGLang 起某一档 qwen3.8-27b（STATUS D3）。三档除 --model-path / --served-model-name 外参数完全相同。
#   注意力与采样不用 FlashInfer（Oct 15 新机器上 FlashInfer 对 SM120 的 JIT 编译失败：系统 CUDA 12.8 不够、
#   改用环境里的 CUDA 13 又与其自带 cccl 头文件不兼容），统一用 triton 注意力 + pytorch 采样，三档相同。
#   KV cache 用 BF16（不用镜像 start.sh 的 fp8_e4m3），不开投机解码 / MTP；量化方式由权重自带的 quantization_config 决定。
#   只监听 127.0.0.1，本机经 SSH 隧道访问：ssh -N -L 30000:127.0.0.1:30000 -p <端口> root@<主机>
# 用法：bash serve.sh bf16|fp8|w4a16
set -euo pipefail
TIER=${1:?用法：serve.sh bf16|fp8|w4a16}
NAME=qwen3.8-27b-$TIER
MODEL=/root/autodl-tmp/models/$NAME
[ -f "$MODEL/config.json" ] || { echo "找不到 $MODEL"; exit 1; }
source /root/miniconda3/etc/profile.d/conda.sh
conda activate qwen38
export LD_LIBRARY_PATH=/root/miniconda3/envs/qwen38/lib:${LD_LIBRARY_PATH:-}
pkill -f "sglang serve" || true
mkdir -p /root/autodl-tmp/logs
exec sglang serve \
  --model-path "$MODEL" \
  --served-model-name "$NAME" \
  --host 127.0.0.1 --port 30000 \
  --kv-cache-dtype auto \
  --attention-backend triton --sampling-backend pytorch \
  --mem-fraction-static 0.85 \
  --context-length 32768 \
  --reasoning-parser qwen3 \
  --random-seed 42 \
  > /root/autodl-tmp/logs/serve_$TIER.log 2>&1
