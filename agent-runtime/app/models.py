"""付费开关独立于模型登记；测试模型不走任何网络。"""
import json
import os
from typing import Any
from urllib.parse import urlsplit
import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI


class ModelConfigurationError(ValueError):
    """由本项目生成、可安全返回的固定配置错误。"""


class FixtureModel(BaseChatModel):
    role: str
    node: dict
    attempt: int = 0
    force_rework: bool = True
    names: list[str] = []
    consultation_roles: list[str] = []
    skill_file: str = ""
    consultation_comparison: bool = False

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
                tool, args = "read_file", {"file_path": self.skill_file}
            elif used.count("read_file") < 2:
                tool, args = "read_file", {"file_path": "/knowledge/SUPERVISOR.md"}
            elif used.count("task") < len(self.consultation_roles) + 1:
                roles = [*self.consultation_roles, self.node["agentRole"]]
                target = roles[used.count("task")]
                tool, args = "task", {"subagent_type": target, "description": "读取独立 Skill、知识和输入；会诊角色提交意见，主责角色提交候选。"}
        elif self.role == "REVIEWER":
            if not used:
                tool, args = "read_file", {"file_path": self.skill_file}
            elif used.count("read_file") < 2:
                tool, args = "read_file", {"file_path": "/knowledge/REVIEWER.md"}
            elif "submit_review" not in used:
                failed = self.force_rework and self.attempt == 0
                tool, args = "submit_review", {"verdict": "REVISE" if failed else "PASS", "issues": ["测试：补充证据边界"] if failed else [], "summary": "仅为测试评审，不代表领域质量验收。"}
        else:
            if not used:
                tool, args = "read_file", {"file_path": self.skill_file}
            elif used.count("read_file") < 2:
                tool, args = "read_file", {"file_path": f"/knowledge/{self.role}.md"}
            elif "read_inputs" not in used:
                tool = "read_inputs"
            elif "submit_opinion" in self.names and "submit_opinion" not in used:
                tool, args = "submit_opinion", {"analysis": "测试会诊意见，仅验证协作链路。",
                    "sources": [], "uncertainties": ["测试模型，未核验事实。"]}
            elif "submit_candidate" in self.names and "submit_candidate" not in used:
                tool, args = "submit_candidate", {
                    "fields": {k: "测试占位：请由创作者补充真实材料" for k in self.node["output"]["requiredFields"]},
                    "body": f"【测试模型产物，不可直接发布】\n{self.node['name']} · 第 {self.attempt + 1} 版\n此内容仅验证真实委派、工具调用、评审和返工链路。",
                    "sources": [], "uncertainties": ["未调用真实模型；未进行资料检索或媒体制作。"]}
                if self.consultation_comparison:
                    args["consultation_comparison"] = {"summary": "测试会诊意见，仅验证对照链路。", "differences": []}
        message = AIMessage(content="测试步骤已结束", tool_calls=[{"name": tool, "args": args, "id": f"fixture-{len(messages)}"}] if tool else [])
        message.usage_metadata = {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}
        return ChatResult(generations=[ChatGeneration(message=message)])


def _credential_host_guard(credential_ref: str, base_url: str) -> bool:
    """可选的凭据目的地约束；未配置时保留原有供应商行为。"""
    raw = os.getenv("CREATOR_CREDENTIAL_HOST_GUARDS")
    if raw is None:
        return False
    try:
        guards = json.loads(raw)
        if not isinstance(guards, dict) or any(
            not isinstance(key, str) or not isinstance(hosts, list) or not hosts
            or any(not isinstance(host, str) or not host or host != host.lower()
                   or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in host)
                   for host in hosts)
            for key, hosts in guards.items()
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise ModelConfigurationError("凭据目的地限制配置无效") from None
    if credential_ref not in guards:
        return False
    try:
        url = urlsplit(base_url)
        allowed = (url.scheme == "https" and url.hostname in guards[credential_ref]
                   and url.port in (None, 443) and url.username is None and url.password is None
                   and not url.query and not url.fragment)
    except (ValueError, TypeError):
        allowed = False
    if not allowed:
        raise ModelConfigurationError("模型服务地址不符合凭据目的地限制")
    return True


def build_model(snapshot: dict, role: str, payload: dict, attempt=0):
    if payload["mode"] == "FIXTURE":
        from .profiles import skill_path
        profile = payload.get("profiles", {}).get(role)
        file_path = skill_path(profile) if profile else f"/skills/{role.lower().replace('_', '-')}-skill/SKILL.md"
        return FixtureModel(role=role, node=payload["node"], attempt=attempt,
                            force_rework=payload.get("fixtureRework", True),
                            consultation_roles=payload.get("consultationRoles", []), skill_file=file_path,
                            consultation_comparison=payload.get("consultationComparison", False))
    if os.getenv("CREATOR_ENABLE_LIVE_MODELS", "false").lower() != "true":
        raise ModelConfigurationError("真实模型调用被服务器开关关闭")
    if snapshot.get("protocol") not in {"CHAT_COMPLETIONS_COMPATIBLE", "RESPONSES"}:
        raise ModelConfigurationError("此协议的 Agent 适配器尚未实现")
    credential_ref = snapshot.get("credentialRef", "")
    guarded = _credential_host_guard(credential_ref, snapshot.get("baseUrl", ""))
    credential = os.getenv(credential_ref)
    if not credential:
        raise ModelConfigurationError("模型认证环境变量尚未设置")
    params = snapshot.get("parameters", {})
    allowed = {"temperature", "top_p", "reasoning_effort"}
    if set(params) - allowed:
        raise ModelConfigurationError("Agent 适配器目前只允许 temperature/top_p/reasoning_effort 参数")
    if "reasoning_effort" in params and (snapshot["protocol"] != "CHAT_COMPLETIONS_COMPATIBLE" or params["reasoning_effort"] != "none"):
        raise ModelConfigurationError("reasoning_effort 当前仅支持 Chat Completions 协议的 none")
    # 受限凭据不跟随重定向，防止服务端将认证请求转发到其他目的地。
    clients = {"http_client": httpx.Client(follow_redirects=False),
               "http_async_client": httpx.AsyncClient(follow_redirects=False)} if guarded else {}
    endpoint = urlsplit(snapshot["baseUrl"])
    timeout = 90 if endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1" and endpoint.port else 45
    return ChatOpenAI(model=snapshot["remoteModelId"], base_url=snapshot["baseUrl"], api_key=credential,
                      use_responses_api=snapshot["protocol"] == "RESPONSES", store=False,
                      max_retries=0, timeout=timeout, **params, **clients)
