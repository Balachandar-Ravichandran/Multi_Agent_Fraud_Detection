"""FastAPI entry point -- the single chat endpoint, the two read-only case
endpoints (PRD Section 14), and the frontend chat UI (Section 4.1).

Live-tested: see CLAUDE.md for what's been run against a real
ANTHROPIC_API_KEY and what hasn't.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.events import LOGS_DIR
from orchestrator.graph import build_graph
from orchestrator.state import GraphState
from tools.invoice_pdf import extract_invoice_fields

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Multi-Agent Procurement Fraud Detection")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")

_compiled_graph = build_graph()


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")

# In-memory session/case state -- Section 16 NFR caps concurrent sessions at
# 1 by design, so this is not a target to scale past for this submission.
SESSIONS: dict[str, dict] = {}
COMPLETED_CASES: dict[str, GraphState] = {}


@app.post("/api/v1/chat")
async def chat(
    message: str = Form(...),
    session_id: str = Form(...),
    file: UploadFile | None = File(None),
):
    session = SESSIONS.get(session_id, {})
    raw_fields: dict = {}

    if file is not None:
        if file.content_type != "application/pdf":
            raise HTTPException(status_code=400, detail="Unsupported file type; only application/pdf is accepted.")
        pdf_bytes = await file.read()
        try:
            raw_fields = extract_invoice_fields(pdf_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    prior_case = COMPLETED_CASES.get(session.get("invoice_id", "")) if not file else None
    initial_state: GraphState = {
        "qa_question": message,
        "raw_fields": raw_fields,
        "invoice_id": session.get("invoice_id", ""),
        "vendor_id": (prior_case or {}).get("vendor_id", ""),
        "po_reference": (prior_case or {}).get("po_reference", ""),
        "draft_report": (prior_case or {}).get("draft_report"),
        "job_results": (prior_case or {}).get("job_results", []),
        "status": session.get("status", "planning"),
        "conversation_history": session.get("conversation_history", []),
    }

    try:
        final_state = _compiled_graph.invoke(initial_state, {"recursion_limit": 25})
    except Exception as exc:  # noqa: BLE001 -- Section 14.1's 500 contract is intentionally broad
        raise HTTPException(status_code=500, detail=f"Unhandled pipeline error: {exc}")

    invoice_id = final_state.get("invoice_id", "")
    history = final_state.get("conversation_history", []) + [
        {"role": "user", "content": message}, {"role": "assistant", "content": final_state.get("message", "")},
    ]
    SESSIONS[session_id] = {
        "invoice_id": invoice_id, "run_id": final_state.get("run_id"),
        "status": final_state.get("status"), "conversation_history": history,
    }
    if invoice_id:
        COMPLETED_CASES[invoice_id] = final_state

    return {
        "session_id": session_id,
        "mode": final_state.get("mode"),
        "status": final_state.get("status"),
        "message": final_state.get("message", ""),
    }


@app.get("/api/v1/case/{invoice_id}")
async def get_case(invoice_id: str):
    state = COMPLETED_CASES.get(invoice_id)
    if state is None or state.get("draft_report") is None:
        raise HTTPException(status_code=404, detail=f"No case with invoice_id {invoice_id}")

    return {
        "report": state["draft_report"].model_dump(),
        "job_results": [r.model_dump() for r in state.get("job_results", [])],
    }


@app.get("/api/v1/case/{invoice_id}/log")
async def get_case_log(invoice_id: str):
    state = COMPLETED_CASES.get(invoice_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No case with invoice_id {invoice_id}")

    log_path = LOGS_DIR / f"run_{state['run_id']}.jsonl"
    if not log_path.exists():
        return {"events": []}

    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    return {"events": [json.loads(line) for line in lines]}
