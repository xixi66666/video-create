"""付费开关独立于模型登记；测试模型不走任何网络。"""
import json
import os
from typing import Any
from urllib.parse import urlsplit
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI


class FixtureModel(BaseChatModel):
    role: str
    node: dict
    attempt: int = 0
    force_rework: bool = True
    names: list[str] = []

    @property
    def _llm_type(self):
        return "workbench-fixture"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"names": [getattr(t, "name", t.get("name", "") if isinstance(t, dict) else "") for t in tools]})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # 此模型只用于框架与控制面验收，绝不伪装专业产物或真实模型能力。
        used = [m.name for m in messages if isinstance(m, ToolMessage)]
        tool, args = "", {}
        if self.role == "SUPERVISOR":
            if not used:
                tool, args = "read_file", {"file_path": "/skills/SUPERVISOR/SKILL.md"}
            elif used.count("read_file") < 2:
                tool, args = "read_file", {"file_path": "/knowledge/SUPERVISOR.md"}
            elif "task" not in used:
                tool, args = "task", {"subagent_type": self.node["agentRole"], "description": "执行指定节点；必须读取独立 Skill、知识、输入，再提交结构化候选。"}
        elif self.role == "REVIEWER":
            if not used:
                tool, args = "read_file", {"file_path": "/skills/REVIEWER/SKILL.md"}
            elif used.count("read_file") < 2:
                tool, args = "read_file", {"file_path": "/knowledge/REVIEWER.md"}
            elif "submit_review" not in used:
                failed = self.force_rework and self.attempt == 0
                tool, args = "submit_review", {"verdict": "REVISE" if failed else "PASS", "issues": ["测试：补充证据边界"] if failed else [], "summary": "仅为测试评审，不代表领域质量验收。"}
        else:
            if not used:
                tool, args = "read_file", {"file_path": f"/skills/{self.role}/SKILL.md"}
            elif used.count("read_file") < 2:
                tool, args = "read_file", {"file_path": f"/knowledge/{self.role}.md"}
            elif "read_inputs" not in used:
                tool = "read_inputs"
            elif "submit_candidate" not in used:
                tool, args = "submit_candidate", {
                    "fields": {k: "测试占位：请由创作者补充真实材料" for k in self.node["output"]["requiredFields"]},
                    "body": f"【测试模型产物，不可直接发布】\n{self.node['name']} · 第 {self.attempt + 1} 版\n此内容仅验证真实委派、工具调用、评审和返工链路。",
                    "sources": [], "uncertainties": ["未调用真实模型；未进行资料检索或媒体制作。"]}
        message = AIMessage(content="测试步骤已结束", tool_calls=[{"name": tool, "args": args, "id": f"fixture-{len(messages)}"}] if tool else [])
        message.usage_metadata = {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}
        return ChatResult(generations=[ChatGeneration(message=message)])


def build_model(snapshot: dict, role: str, payload: dict, attempt=0):
    if payload["mode"] == "FIXTURE":
        return FixtureModel(role=role, node=payload["node"], attempt=attempt, force_rework=payload.get("fixtureRework", True))
    if os.getenv("CREATOR_ENABLE_LIVE_MODELS", "false").lower() != "true":
        raise ValueError("真实模型调用被服务器开关关闭")
    if snapshot.get("protocol") not in {"CHAT_COMPLETIONS_COMPATIBLE", "RESPONSES"}:
        raise ValueError("此协议的 Agent 适配器尚未实现")
    credential = os.getenv(snapshot.get("credentialRef", ""))
    if not credential:
        raise ValueError("模型认证环境变量尚未设置")
    params = snapshot.get("parameters", {})
    allowed = {"temperature", "top_p", "reasoning_effort"}
    if set(params) - allowed:
        raise ValueError("Agent 适配器不支持指定的模型参数")
    if "reasoning_effort" in params and params["reasoning_effort"] not in {"none", "low", "high", "max"}:
        raise ValueError("reasoning_effort 参数不合法")
    endpoint = urlsplit(snapshot["baseUrl"])
    # 本机 CPU 推理可能比远端服务慢；不改变远端供应商的单次超时。
    timeout = 90 if endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1" and endpoint.port else 45
    return ChatOpenAI(model=snapshot["remoteModelId"], base_url=snapshot["baseUrl"], api_key=credential,
                      use_responses_api=snapshot["protocol"] == "RESPONSES", store=False,
                      max_tokens=payload["limits"]["maxOutputTokens"], max_retries=0, timeout=timeout, **params)
