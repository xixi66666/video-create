import os
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
import hmac
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from .storage import Store, QueueFull
from .engine import Engine
from .profiles import load_profiles


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)
    voice: str


class StartRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^run_[a-zA-Z0-9_-]{8,90}$")
    projectId: str
    mode: str = Field(pattern="^(FIXTURE|LIVE)$")
    node: dict
    input: dict
    models: dict
    inputFingerprint: str
    executionMode: str = Field(pattern="^(GENERATE_TEXT|PLAN_ONLY)$")
    limits: dict
    fixtureRework: bool = True
    # 可选会诊；默认保留原来的单专家执行方式。
    consultationRoles: list[str] = Field(default_factory=list, max_length=6)
    consultationComparison: bool = False


def create_app(root=None, token=None):
    store = Store(Path(root or os.getenv("CREATOR_RUNTIME_DATA", "./data")))
    engine = Engine(store, Path(root or os.getenv("CREATOR_RUNTIME_DATA", "./data")))
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="creator-agent")
    secret = token or os.getenv("CREATOR_RUNTIME_TOKEN", "")

    def auth(x_creator_token: str = Header(default="")):
        if not secret or not hmac.compare_digest(x_creator_token, secret):
            raise HTTPException(401, "内部运行服务需要认证")

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        # 已持久化且未开始的任务可重投；RUNNING 的中断不能盲目重试。
        for row in store.recoverable():
            if row["status"] == "QUEUED":
                pool.submit(engine.run, row["id"])
            elif row["status"] == "WAITING_ACCEPTANCE" and store.get(row["id"])["decision"]:
                pool.submit(engine.run, row["id"], store.get(row["id"])["decision"])
        yield
        pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Creator Agent Runtime", lifespan=lifespan, dependencies=[Depends(auth)], docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.engine = store, engine

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"detail": str(exc)[:300]})

    @app.exception_handler(KeyError)
    async def missing(request: Request, exc: KeyError):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "运行不存在"})

    @app.post("/speech/mimo")
    def speech_mimo(body: SpeechRequest):
        from .speech import synthesize
        return synthesize(body.text, body.voice)

    @app.get("/health")
    def health():
        return {"status": "UP", "engine": "LangGraph + Deep Agents", "liveModelsEnabled": os.getenv("CREATOR_ENABLE_LIVE_MODELS", "false").lower() == "true", "providerValidation": "NOT_ASSESSED_BY_HEALTH_CHECK"}

    @app.get("/profiles")
    def profiles():
        from .expert_tools import tools_for_role
        live_enabled = os.getenv("CREATOR_ENABLE_LIVE_MODELS", "false").lower() == "true"
        response = []
        for key, p in load_profiles().items():
            if key in {"SUPERVISOR", "REVIEWER"}:
                continue
            declared = p["tools"]
            base = [name for name in declared if name in {"read_file", "read_inputs", "submit_candidate"}]
            fixture = base + [item.name for item in tools_for_role(key, declared, mode="FIXTURE")]
            live = (base + [item.name for item in tools_for_role(key, declared, mode="LIVE")]) if live_enabled else []
            response.append({**{k: p[k] for k in ("id", "name", "version", "lifecycle", "domainVerified", "sha256")},
                             "tools": fixture, "declaredTools": declared,
                             "availableTools": {"FIXTURE": fixture, "LIVE": live},
                             "availabilityNote": "仅表示当前注册条件，实际来源、目录及服务仍需在调用时验证。"})
        return response

    @app.post("/runs", status_code=202)
    def start(request: StartRun):
        if len(json.dumps(request.input, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 400000:
            raise ValueError("输入过大，请缩减任务或引用材料")
        payload = request.model_dump(exclude={"id"})
        if not request.consultationComparison:
            payload.pop("consultationComparison", None)
        if not request.consultationRoles:
            payload.pop("consultationRoles", None)
        # 已受理运行的幂等重投只核对原请求并返回原状态；配置变更不能伪造新运行或阻碍交付确认。
        try:
            saved = store.get(request.id)
        except KeyError:
            saved = None
        if saved is not None:
            payload["profiles"] = saved["payload"]["profiles"]
            store.create(request.id, payload, max_pending=50)
            return saved
        if request.mode == "LIVE" and os.getenv("CREATOR_ENABLE_LIVE_MODELS", "false").lower() != "true":
            raise HTTPException(409, "服务器已关闭真实模型调用")
        if request.mode == "LIVE":
            from .models import ModelConfigurationError, build_model
            authorized = set(os.getenv("CREATOR_APPROVED_AGENT_MODELS", "").split(","))
            snapshots = [(role, request.models.get(role, {})) for role in ("supervisor", "worker", "reviewer")]
            snapshots += [(role, request.models.get("consultant_" + role, request.models.get("worker", {}))) for role in request.consultationRoles]
            for role, model in snapshots:
                if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not model["id"] or model["id"] not in authorized:
                    raise HTTPException(409, "模型不在操作者授权白名单")
                # 构造客户端及校验引用，不进行网络或模型调用；缺失凭据不应受理后才失败。
                try:
                    build_model(model, role.upper(), request.model_dump())
                except ModelConfigurationError:
                    raise
                except Exception:
                    # 第三方配置异常可能包含凭据或用户输入，不将其写入日志或响应。
                    raise HTTPException(400, "模型客户端初始化失败，请检查服务配置。") from None
        limits = request.limits
        for key, low, high in [("maxModelCalls", 3, 60), ("maxSeconds", 10, 300), ("maxReworks", 0, 2)]:
            if type(limits.get(key)) is not int or not low <= limits[key] <= high:
                raise ValueError(f"运行限制无效：{key}")
        profiles = load_profiles()
        role = request.node.get("agentRole")
        if not isinstance(role, str) or role not in profiles or role in {"SUPERVISOR", "REVIEWER"}:
            raise ValueError("专家角色不存在")
        consultants = request.consultationRoles
        if len(set(consultants)) != len(consultants) or any(
            r == role or r not in profiles or r in {"SUPERVISOR", "REVIEWER"} for r in consultants
        ):
            raise ValueError("会诊角色必须互不重复，且为不同于主责的专家")
        if request.consultationComparison and len(consultants) < 2:
            raise ValueError("会诊对照至少需要两位专家")
        payload["profiles"] = {r: profiles[r] for r in {role, "SUPERVISOR", "REVIEWER", *consultants}}
        try:
            created = store.create(request.id, payload, max_pending=50,
                                   created_event={"mode": request.mode, "inputFingerprint": request.inputFingerprint})
        except QueueFull:
            raise HTTPException(429, "运行队列已满，请稍后再试") from None
        if created:
            pool.submit(engine.run, request.id)
        return store.get(request.id)

    @app.get("/runs/{run_id}")
    def detail(run_id: str):
        result = store.get(run_id)
        result.pop("payload")
        return result

    @app.get("/runs/{run_id}/events")
    def events(run_id: str, after: int = 0):
        store.get(run_id)
        return store.events(run_id, max(0, after))

    @app.post("/runs/{run_id}/decision")
    def decide(run_id: str, body: dict):
        value = body.get("decision")
        if not isinstance(value, str) or value not in {"ACCEPT", "REJECT"}:
            raise ValueError("决定无效")
        outcome = store.claim_decision(run_id, value)
        if outcome in {"CONFLICT", "INVALID"}:
            raise HTTPException(409, "运行当前不能采纳或拒绝")
        saved = store.get(run_id)
        if saved["status"] == "WAITING_ACCEPTANCE":
            pool.submit(engine.run, run_id, value)
        if outcome == "SAME":
            return saved
        return {"status": "RESUMING"}

    @app.post("/runs/{run_id}/cancel")
    def cancel(run_id: str):
        if not store.cancel(run_id):
            raise HTTPException(409, "此状态无法取消")
        return {"status": "CANCELLED"}

    return app


app = create_app()
