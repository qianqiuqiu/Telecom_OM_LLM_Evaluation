"""注册 EvalScope 基准 `teleqna_mcq`：沿用 general_mcq 的加载、抽取与打分，只把提示模板换成英文单选模板。

原因：general_mcq 在 __init__ 中固定使用中文模板，dataset_args 里的 prompt_template 会被覆盖；
TeleQnA 题目为英文，统一用 EvalScope 自带的英文模板（要求输出 'ANSWER: X'）。
由 scripts/run_objective.py 导入，不单独运行。
"""

from evalscope.api.benchmark import BenchmarkMeta
from evalscope.api.registry import register_benchmark
from evalscope.benchmarks.general_mcq.general_mcq_adapter import GeneralMCQAdapter
from evalscope.constants import Tags
from evalscope.utils.multi_choices import MultipleChoiceTemplate

TEMPLATE = MultipleChoiceTemplate.SINGLE_ANSWER


@register_benchmark(
    BenchmarkMeta(
        name='teleqna_mcq',
        pretty_name='TeleQnA-Ops-MCQ',
        description='TeleQnA ops-relevant subset (731 items), English single-answer template.',
        tags=[Tags.MULTIPLE_CHOICE, Tags.CUSTOM],
        dataset_id='teleqna_mcq',
        subset_list=['orig'],
        metric_list=['acc'],
        few_shot_num=0,
        train_split='dev',
        eval_split='val',
        prompt_template=TEMPLATE,
    )
)
class TeleQnAMCQAdapter(GeneralMCQAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prompt_template = TEMPLATE
