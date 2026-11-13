"""无外部访问权限的确定性领域计算工具。"""
import math
import os
import statistics
from fractions import Fraction

from langchain_core.tools import tool

RESEARCH_ROLES = {"FACT_CHECK", "TOPIC_RESEARCH", "PACKAGING", "PUBLISHER", "BUSINESS"}


def _research_tool_names():
    """只报告部署配置已具备的能力；网络或来源可用性仍须实际核验。"""
    if os.getenv("CREATOR_RESEARCH_ENABLED", "false").lower() != "true":
        return set()
    from .research_tools import ResearchError, _configured, _validated_url
    try:
        hosts = _configured()
    except ResearchError:
        return set()
    names = {"read_research_page"}
    if os.getenv("CREATOR_RESEARCH_PROVIDER", "").lower() == "deepseek":
        if os.getenv("DEEPSEEK_API_KEY"):
            names.add("search_research_sources")
    else:
        try:
            parts, _ = _validated_url(os.getenv("CREATOR_RESEARCH_SEARCH_URL", ""), hosts)
            if not parts.query:
                names.add("search_research_sources")
        except ResearchError:
            pass
    return names


@tool
def summarize_numeric_data(values: list[float]) -> dict:
    """计算用户提供数值的描述统计；不能导入数据或推断总体和因果关系。最多 1000 个有限数值。"""
    if not 1 <= len(values) <= 1000 or any(not math.isfinite(x) or abs(x) > 1e100 for x in values):
        raise ValueError("请输入 1 至 1000 个绝对值不超过 1e100 的有限数值")
    return {"count": len(values), "mean": statistics.mean(values), "median": statistics.median(values),
            "min": min(values), "max": max(values),
            "sampleStandardDeviation": statistics.stdev(values) if len(values) >= 2 else None,
            "note": "描述性统计；样本来源、口径和选择偏差需要另行核实。"}


@tool
def calculate_proportion_interval(successes: int, trials: int) -> dict:
    """计算二项比例及 95% Wilson 置信区间；仅适用于独立、同分布二项观测。"""
    if trials < 1 or trials > 1_000_000_000 or successes < 0 or successes > trials:
        raise ValueError("要求 0 ≤ successes ≤ trials，且 trials 在 1 至 1000000000 之间")
    z = 1.959963984540054
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return {"successes": successes, "trials": trials, "proportion": p,
            "confidenceLevel": 0.95, "method": "Wilson score", "lower": max(0.0, center - margin),
            "upper": min(1.0, center + margin),
            "note": "假设观测独立且成功概率相同；不校正抽样偏差，也不证明因果。"}


@tool
def frames_to_duration(frames: int, fps_numerator: int, fps_denominator: int = 1) -> dict:
    """按精确有理帧率把帧数换算为时长；不生成 SMPTE 时间码，也不处理 drop-frame。"""
    if not 0 <= frames <= 10_000_000 or not 1 <= fps_numerator <= 1_000_000 or not 1 <= fps_denominator <= 100_000:
        raise ValueError("帧数或帧率超出允许范围")
    fps = Fraction(fps_numerator, fps_denominator)
    if not Fraction(1, 1) <= fps <= Fraction(240, 1):
        raise ValueError("帧率必须在 1 至 240 fps 之间")
    seconds = Fraction(frames, 1) / fps
    return {"frames": frames, "fps": f"{fps.numerator}/{fps.denominator}",
            "seconds": float(seconds), "exactSeconds": f"{seconds.numerator}/{seconds.denominator}",
            "note": "帧数换算时长，不是时间码；素材帧率须由外部工具或用户提供。"}


def tools_for_role(role: str, allowed_names=None, mode="FIXTURE") -> list:
    """按角色、固定的授权快照和部署开关注册工具。测试模式绝不访问外部数据。"""
    result = []
    if role in {"ANALYST", "BUSINESS", "FEEDBACK"}:
        result.extend([summarize_numeric_data, calculate_proportion_interval])
    if role in {"DIRECTOR", "EDITOR", "VIDEO", "CAPTURE", "QUALITY"}:
        result.append(frames_to_duration)
    if mode == "LIVE":
        if role in RESEARCH_ROLES:
            from .research_tools import read_research_page, search_research_sources
            ready = _research_tool_names()
            result.extend(item for item in [read_research_page, search_research_sources] if item.name in ready)
        if role in {"LIBRARIAN", "QUALITY", "AUDIO", "IMAGE", "VIDEO", "EDITOR", "ART_CONTINUITY"}:
            from .local_media_tools import make_local_media_tools
            enabled = os.getenv("CREATOR_LOCAL_MEDIA_ENABLED", "false").lower() == "true"
            result.extend(make_local_media_tools(os.getenv("CREATOR_LOCAL_MEDIA_ROOT"), enabled))
    if allowed_names is not None:
        allowed = set(allowed_names)
        result = [item for item in result if item.name in allowed]
    return result
