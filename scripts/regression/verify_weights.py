"""精度回归权重校验（在 AutoDL 服务器上跑）：本地每个文件的 sha256 / 大小与 HF 固定 commit 公布的一致。

三档权重（Spec「精度回归与发版门禁」，STATUS Oct 15）：
  BF16  Qwen/Qwen3.8-27B                @ 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0（从 ModelScope 下载）
  FP8   Qwen/Qwen3.8-27B-FP8            @ 017b9c7af6b5689d5dd426a76e0bc077eb5ca20a（从 ModelScope 下载）
  W4A16 barrydeen/Qwen3.8-27B-AWQ-4bit  @ e6b4b8b025f85b3e18f13281db576e0b7d5fe314（从 HF 下载）
ModelScope 的 master 与 HF 的固定 commit 不一定同步，所以一律按 HF 的哈希核对：LFS 文件比 sha256，其余比大小。

用法：python verify_weights.py [--root /root/autodl-tmp/models]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

TIERS = {
    "qwen3.8-27b-bf16": ("Qwen/Qwen3.8-27B", "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"),
    "qwen3.8-27b-fp8": ("Qwen/Qwen3.8-27B-FP8", "017b9c7af6b5689d5dd426a76e0bc077eb5ca20a"),
    "qwen3.8-27b-w4a16": ("barrydeen/Qwen3.8-27B-AWQ-4bit", "e6b4b8b025f85b3e18f13281db576e0b7d5fe314"),
}


def hf_tree(repo, rev):
    url = f"https://huggingface.co/api/models/{repo}/tree/{rev}?recursive=true"
    out = subprocess.run(["bash", "-c", f"source /etc/network_turbo >/dev/null 2>&1; curl -s --max-time 60 '{url}'"],
                         capture_output=True, text=True).stdout
    return [x for x in json.loads(out) if x["type"] == "file"]


def sha256(path, buf=16 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(buf):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/root/autodl-tmp/models")
    args = ap.parse_args()
    bad = 0
    for name, (repo, rev) in TIERS.items():
        d = Path(args.root) / name
        files = hf_tree(repo, rev)
        n_lfs = n_ok = 0
        problems = []
        for x in files:
            p = d / x["path"]
            if not p.exists():
                problems.append(f"缺文件 {x['path']}")
                continue
            if os.path.getsize(p) != x["size"]:
                problems.append(f"大小不符 {x['path']}：本地 {os.path.getsize(p)}，HF {x['size']}")
                continue
            lfs = x.get("lfs")
            if lfs:
                n_lfs += 1
                if sha256(p) != lfs["oid"]:
                    problems.append(f"sha256 不符 {x['path']}")
                    continue
            n_ok += 1
        size = sum(x["size"] for x in files) / 1e9
        print(f"{name}: {repo}@{rev[:10]}  HF 文件 {len(files)} 个（LFS {n_lfs}），{size:.1f} GB；通过 {n_ok}，问题 {len(problems)}")
        for pr in problems:
            print("   ", pr)
        bad += len(problems)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
