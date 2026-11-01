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
from .storage import Store
from .engine import Engine
from .profiles import load_profiles


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
        for row in store.list():
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

    @app.get("/health")
    def health():
        return {"status": "UP", "engine": "LangGraph + Deep Agents", "liveModelsEnabled": os.getenv("CREATOR_ENABLE_LIVE_MODELS", "false").lower() == "true", "fixtureOnlyValidated": True}

    @app.get("/profiles")
    def profiles():
        return [{k: p[k] for k in ("id", "name", "version", "lifecycle", "domainVerified", "tools", "sha256")} for key, p in load_profiles().items() if key not in {"SUPERVISOR", "REVIEWER"}]

    @app.post("/runs", status_code=202)
    def start(request: StartRun):
        if request.mode == "LIVE" and os.getenv("CREATOR_ENABLE_LIVE_MODELS", "false").lower() != "true":
            raise HTTPException(409, "服务器已关闭真实模型调用")
        if request.mode == "LIVE":
            from .models import build_model
            authorized = set(os.getenv("CREATOR_APPROVED_AGENT_MODELS", "").split(","))
            for role in ("supervisor", "worker", "reviewer"):
                model = request.models.get(role, {})
                if not model.get("id") or model["id"] not in authorized:
                    raise HTTPException(409, "模型不在操作者授权白名单")
                # 构造客户端及校验引用，不进行网络或模型调用；缺失凭据不应受理后才失败。
                build_model(model, role.upper(), request.model_dump())
        limits = request.limits
        for key, low, high in [("maxModelCalls", 3, 60), ("maxTotalTokens", 0, 100000), ("maxOutputTokens", 100, 4096), ("maxSeconds", 10, 300), ("maxReworks", 0, 2)]:
            if type(limits.get(key)) is not int or not low <= limits[key] <= high:
                raise ValueError(f"运行限制无效：{key}")
        if 0 < limits["maxTotalTokens"] < 100:
            raise ValueError("运行限制无效：maxTotalTokens")
        if len(json.dumps(request.input)) > 400000:
            raise ValueError("输入过大，请缩减任务或引用材料")
        payload = request.model_dump(exclude={"id"})
        profiles = load_profiles()
        role = request.node.get("agentRole")
        if role not in profiles:
            raise ValueError("专家角色不存在")
        # 重投使用已保存的 Skills/模型/知识快照，不受配置后续变化影响。
        try:
            saved = store.get(request.id)["payload"]
            payload["profiles"] = saved["profiles"]
        except KeyError:
            if sum(r["status"] in {"QUEUED", "RUNNING"} for r in store.list()) >= 50:
                raise HTTPException(429, "运行队列已满，请稍后再试")
            payload["profiles"] = {r: profiles[r] for r in {role, "SUPERVISOR", "REVIEWER"}}
        if store.create(request.id, payload):
            store.event(request.id, "RUN_CREATED", mode=request.mode, inputFingerprint=request.inputFingerprint)
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
        saved = store.get(run_id)
        if value not in {"ACCEPT", "REJECT"}:
            raise ValueError("决定无效")
        if saved["decision"] == value:
            if saved["status"] == "WAITING_ACCEPTANCE":
                pool.submit(engine.run, run_id, value)
            return saved
        if saved["status"] != "WAITING_ACCEPTANCE":
            raise HTTPException(409, "运行当前不能采纳或拒绝")
        store.decision(run_id, value)
        pool.submit(engine.run, run_id, value)
        return {"status": "RESUMING"}

    @app.post("/runs/{run_id}/cancel")
    def cancel(run_id: str):
        saved = store.get(run_id)
        if saved["status"] not in {"QUEUED", "RUNNING", "WAITING_ACCEPTANCE"}:
            raise HTTPException(409, "此状态无法取消")
        store.status(run_id, "CANCELLED")
        store.event(run_id, "CANCELLED")
        return {"status": "CANCELLED"}

    return app


app = create_app()
