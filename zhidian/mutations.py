"""Finite controlled functional faults for measuring the teaching test suites."""
from .catalog import TASKS


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("故障注入锚点已变化，不能静默生成无效实验。")
    return source.replace(old, new, 1)


def range_overfit_fir() -> str:
    return replace_once(TASKS["fir"]["solution"], "y <= x + 2*d1 - d2;", "if x > 12 or x < -12 then\n          y <= 0;\n        else\n          y <= x + 2*d1 - d2;\n        end if;")


def mutation_cases() -> list[dict]:
    cases = [{"id": task_id + "_teaching_fault", "task_id": task_id, "name": task["title"] + "：内置概念错误", "source": task["starter"]} for task_id, task in TASKS.items()]
    counter, fir = TASKS["counter"]["solution"], TASKS["fir"]["solution"]
    cases.extend([
        {"id": "counter_step_two", "task_id": "counter", "name": "计数步长从 1 变为 2", "source": replace_once(counter, "count <= count + 1;", "count <= count + 2;")},
        {"id": "counter_falling_edge", "task_id": "counter", "name": "上升沿误用为下降沿", "source": replace_once(counter, "rising_edge(clk)", "falling_edge(clk)")},
        {"id": "fir_coefficient_sign", "task_id": "fir", "name": "FIR 第三系数符号错误", "source": replace_once(fir, "y <= x + 2*d1 - d2;", "y <= x + 2*d1 + d2;")},
        {"id": "fir_public_range_overfit", "task_id": "fir", "name": "仅迎合公开测试输入范围的特判", "source": range_overfit_fir()},
    ])
    return cases
