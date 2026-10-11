"""为 TeleQnA 审计范围内的题干计算 embedding，用于语义近重复召回。

题干去掉 [3GPP Release N] 标签后送入 qwen3.7-text-embedding（接口单批上限 10 条）。
结果缓存到 results/audit/embeddings.npz（由原文派生，不入库）；已缓存则跳过。

用法：uv run python scripts/embed_teleqna.py [--force]
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_teleqna import load_items  # noqa: E402

MODEL = "qwen3.7-text-embedding"
BATCH = 10
OUT = ROOT / "results/audit/embeddings.npz"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if OUT.exists() and not args.force:
        print(f"已存在 {OUT.relative_to(ROOT)}，跳过（--force 重算）")
        return

    load_dotenv(ROOT / ".env")
    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"], max_retries=5)
    items = load_items()
    ids = [it["id"] for it in items]
    texts = [it["stem"] for it in items]
    batches = [texts[i:i + BATCH] for i in range(0, len(texts), BATCH)]

    def embed(batch):
        r = client.embeddings.create(model=MODEL, input=batch)
        return [d.embedding for d in sorted(r.data, key=lambda d: d.index)]

    with ThreadPoolExecutor(8) as ex:
        vecs = [v for chunk in ex.map(embed, batches) for v in chunk]
    emb = np.asarray(vecs, dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, ids=np.array(ids), emb=emb, model=MODEL)
    print(f"写出 {OUT.relative_to(ROOT)}：{emb.shape}")


if __name__ == "__main__":
    main()
