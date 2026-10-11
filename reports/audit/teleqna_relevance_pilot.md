# 运维相关度试标

由 `analysis/relevance_pilot_compare.py` 生成，请勿手改。规范见 `docs/rubrics/ops_relevance_v1.md`。

## 一致性

| 对照 | 题数 | 相关度完全一致 | 相关度加权 kappa | 入选（≥2）kappa | 维度一致 | 维度 kappa |
| --- | --- | --- | --- | --- | --- | --- |
| default vs default_v2 | 200 | 78% | 0.682 | 0.593 | 94% | 0.932 |
| default vs haiku | 200 | 75% | 0.717 | 0.599 | 88% | 0.858 |
| default vs haiku_v2 | 199 | 73% | 0.553 | 0.479 | 87% | 0.844 |
| default_v2 vs haiku | 200 | 74% | 0.609 | 0.490 | 92% | 0.907 |
| default_v2 vs haiku_v2 | 199 | 88% | 0.799 | 0.734 | 90% | 0.881 |
| haiku vs haiku_v2 | 199 | 74% | 0.591 | 0.479 | 93% | 0.912 |

## 分布

| 标注者 | 相关度 0 / 1 / 2 / 3 | 入选比例 | 维度分布 |
| --- | --- | --- | --- |
| default | 20 / 115 / 58 / 7 | 32% | RAN 60，CORE 33，TRANSPORT 36，OAM 12，SERVICE 25，SECURITY 10，OTHER 24 |
| default_v2 | 24 / 137 / 38 / 1 | 20% | RAN 65，CORE 34，TRANSPORT 36，OAM 11，SERVICE 24，SECURITY 10，OTHER 20 |
| haiku | 16 / 113 / 66 / 5 | 36% | RAN 68，CORE 31，TRANSPORT 34，OAM 13，SERVICE 20，SECURITY 12，OTHER 22 |
| haiku_v2 | 18 / 145 / 35 / 1 | 18% | RAN 71，CORE 26，TRANSPORT 35，OAM 15，SERVICE 22，SECURITY 9，OTHER 21 |
