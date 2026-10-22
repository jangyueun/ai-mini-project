"""all_total 통합 실습 — FastAPI 백엔드 (Wave 1·3·12·14 축 + 전체 조립).

- Wave 1  : lifespan에서 Agent 번들(MCP 연결·LLM·그래프)을 프로세스당 정확히 1회 생성,
            app.state로 모든 요청이 공유 (creation_count/instance_id로 증명)
- Wave 2  : mcp_server.py를 subprocess(stdio)로 기동해 연결 유지
- Wave 3  : GET /chat/stream — 그래프 실행 과정을 SSE 이벤트로 스트리밍
- Wave 12 : 대화 이력을 SQLite(session.db)에 저장 — 재시작해도 유지
- Wave 14 : SUPERVISOR_VERSION(v1/v2) 환경변수로 legacy/신형 파이프라인 즉시 전환
- LangSmith: 요청당 chat_request 루트 run 아래로 노드·LLM·MCP 호출이 계층 기록됨
"""
import asyncio
import json
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()   # LANGCHAIN_TRACING_V2 / API_KEY / PROJECT — import보다 먼저

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from pydantic import BaseModel, Field

from agent.deps import SupervisorDeps
from agent.fake_llm import FastLLM, QualityLLM
from agent.graph import build_graph
from agent.mcp_client import MCPClient
from agent.session_store import SqliteSessionStore
from agent.supervisor_v1 import run_v1

CREATION_COUNT = 0   # Wave 1 — 프로세스 내 Agent 번들 생성 횟수 (항상 1이어야 정상)


class ChatRequest(BaseModel):   # Wave 1 — Pydantic 요청 검증
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(default="default", min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")


def _build_llms():
    """LLM_BACKEND=fake(기본, 결정론) | ollama(로컬 실모델) | openai(실제 OpenAI API)."""
    backend = os.environ.get("LLM_BACKEND", "fake")
    if backend == "ollama":
        from agent.ollama_llm import OllamaFastLLM, OllamaQualityLLM
        fast = OllamaFastLLM(os.environ.get("OLLAMA_FAST_MODEL", "qwen3:0.6b"),
                             usd_per_1k_tokens=0.00015)
        quality = OllamaQualityLLM(os.environ.get("OLLAMA_QUALITY_MODEL", "qwen3:8b"),
                                   usd_per_1k_tokens=0.005)
        return backend, fast, quality
    if backend == "openai":
        from agent.openai_llm import OpenAIFastLLM, OpenAIQualityLLM
        fast = OpenAIFastLLM(os.environ.get("OPENAI_FAST_MODEL", "gpt-4o-mini"),
                             usd_per_1k_tokens=0.00015)
        quality = OpenAIQualityLLM(os.environ.get("OPENAI_QUALITY_MODEL", "gpt-4o"),
                                   usd_per_1k_tokens=0.005)
        return backend, fast, quality
    fast = FastLLM("fast-model-stub", usd_per_1k_tokens=0.00015)
    quality = QualityLLM("quality-model-stub", usd_per_1k_tokens=0.005)
    return backend, fast, quality


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CREATION_COUNT
    CREATION_COUNT += 1
    mcp = MCPClient()
    await mcp.start()   # Wave 2 — MCP subprocess는 서버 수명 동안 딱 1개
    backend, fast_llm, quality_llm = _build_llms()
    app.state.llm_backend = backend
    deps = SupervisorDeps(
        fast_llm=fast_llm,
        quality_llm=quality_llm,
        mcp=mcp,
        session_store=SqliteSessionStore(),
        version=os.environ.get("SUPERVISOR_VERSION", "v2"),
    )
    app.state.deps = deps
    app.state.graph = build_graph(deps) if deps.version == "v2" else None
    app.state.instance_id = id(deps)
    app.state.session_locks = {}
    yield
    await mcp.stop()
    deps.session_store.close()
    try:   # 종료 전 LangSmith 배치 전송 플러시 — kill 시 run이 pending으로 남는 것 방지
        from langchain_core.tracers.langchain import wait_for_all_tracers
        wait_for_all_tracers()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "instance_id": app.state.instance_id,
            "creation_count": CREATION_COUNT,
            "supervisor_version": app.state.deps.version,
            "llm_backend": app.state.llm_backend,
            "fast_llm": app.state.deps.fast_llm.name,
            "quality_llm": app.state.deps.quality_llm.name}


@app.get("/version")
async def version():
    return {"supervisor_version": app.state.deps.version}


def _metadata(result: dict, run_id: str | None) -> dict:
    return {
        "route": result.get("route"),
        "task_count": len(result.get("tasks", [])),
        "gate_removed": result.get("gate_removed", 0),
        "replan_rounds": result.get("replan_rounds", 0),
        "retry_count": result.get("retry_count", 0),
        "parallel_elapsed": result.get("parallel_elapsed"),
        "validation_attempts": result.get("validation_attempts", 0),
        "validation_status": result.get("validation_status"),
        "validation_issues": result.get("validation_issues", []),
        "cost_usd": result.get("cost_usd", 0.0),
        "llm_backend": app.state.llm_backend,
        "supervisor_version": app.state.deps.version,
        "instance_id": app.state.instance_id,
        "langsmith_run_id": run_id,
    }


def _session_lock(thread_id: str) -> asyncio.Lock:
    return app.state.session_locks.setdefault(thread_id, asyncio.Lock())


def _validate_thread(thread_id: str) -> None:
    # GET/DELETE도 POST와 같은 ID 규칙 사용.
    ChatRequest(message="check", thread_id=thread_id)


def _input_state(message: str, thread_id: str) -> dict:
    store = app.state.deps.session_store
    return {"query": message, "thread_id": thread_id, "history": store.load(thread_id),
            "context": store.context(thread_id), "events": [], "cost_usd": 0.0}


@app.get("/sessions/{thread_id}")
async def get_session(thread_id: str):
    try:
        _validate_thread(thread_id)
    except ValueError:
        raise HTTPException(422, "대화 ID 형식이 올바르지 않습니다.")
    store = app.state.deps.session_store
    return {"thread_id": thread_id, "messages": store.messages(thread_id),
            "context": store.context(thread_id), "busy": _session_lock(thread_id).locked()}


@app.delete("/sessions/{thread_id}")
async def delete_session(thread_id: str):
    try:
        _validate_thread(thread_id)
    except ValueError:
        raise HTTPException(422, "대화 ID 형식이 올바르지 않습니다.")
    lock = _session_lock(thread_id)
    if lock.locked():
        raise HTTPException(409, "답변 생성이 끝난 뒤 삭제해 주세요.")
    async with lock:
        app.state.deps.session_store.clear(thread_id)
    return {"deleted": True, "thread_id": thread_id}


@traceable(name="chat_request")
async def _handle_chat(message: str, thread_id: str) -> tuple[dict, str | None]:
    deps = app.state.deps
    initial = _input_state(message, thread_id)
    if deps.version == "v2":
        result = await app.state.graph.ainvoke(initial)
    else:
        result = await run_v1(deps, message, thread_id, initial["history"])
    deps.session_store.save_turn(thread_id, message, result)
    rt = get_current_run_tree()
    return result, (str(rt.id) if rt else None)


@app.post("/chat")
async def chat(req: ChatRequest):
    lock = _session_lock(req.thread_id)
    if lock.locked():
        raise HTTPException(409, "같은 대화의 이전 답변을 기다려 주세요.")
    async with lock:
        result, run_id = await _handle_chat(req.message, req.thread_id)
    return {"reply": result["final"], "events": result.get("events", []),
            "metadata": _metadata(result, run_id)}


@app.get("/chat/stream")
async def chat_stream(message: str, thread_id: str = "default"):
    try:
        req = ChatRequest(message=message.strip(), thread_id=thread_id)
    except ValueError:
        raise HTTPException(422, "질문 또는 대화 ID 형식이 올바르지 않습니다.")
    lock = _session_lock(thread_id)
    if lock.locked():
        raise HTTPException(409, "같은 대화의 이전 답변을 기다려 주세요.")

    def event(data):
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def gen():
        async with lock:
            deps = app.state.deps
            try:
                initial = _input_state(req.message, thread_id)
                if deps.version != "v2":
                    result = await run_v1(deps, req.message, thread_id, initial["history"])
                    for ev in result["events"]:
                        yield event(ev)
                else:
                    seen = 0
                    result = dict(initial)
                    async for mode, payload in app.state.graph.astream(
                            initial, stream_mode=["updates", "custom"]):
                        if mode == "custom":
                            yield event(payload)
                            continue
                        for node_name, delta in payload.items():
                            result.update(delta)
                            for ev in (delta.get("events") or [])[seen:]:
                                yield event({**ev, "node": node_name})
                            if delta.get("events"):
                                seen = len(delta["events"])
                # 최종 이벤트 전에 저장해서 답변 직후 새로고침해도 복원한다.
                deps.session_store.save_turn(thread_id, req.message, result)
                yield event({"type": "FinalAnswer", "reply": result["final"],
                             "prompt": result.get("last_prompt"), "saved": True})
            except Exception:
                # 연결 정보·API 키가 포함될 수 있는 예외 본문은 화면에 노출하지 않는다.
                yield event({"type": "StreamError", "message": "처리에 실패했어요. 이 요청은 저장되지 않았어요. 서버 상태를 확인한 뒤 다시 보내 주세요."})
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
