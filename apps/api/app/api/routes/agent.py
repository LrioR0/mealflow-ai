from fastapi import APIRouter, HTTPException, status

from app.schemas.agent import (
    AgentRunView,
    CreateAgentRunRequest,
    ReviseAgentRunRequest,
)
from app.services.agent_service import create_demo_run, get_demo_run, revise_demo_run

router = APIRouter(prefix="/agent/runs", tags=["agent"])


@router.post("", response_model=AgentRunView, status_code=status.HTTP_201_CREATED)
def create_agent_run(payload: CreateAgentRunRequest) -> AgentRunView:
    # The scaffold returns the deterministic baseline. Replace constraint parsing with
    # LLMProvider + LangGraph without changing this HTTP contract.
    return create_demo_run(payload.request_text)


@router.get("/{run_id}", response_model=AgentRunView)
def get_agent_run(run_id: str) -> AgentRunView:
    run = get_demo_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@router.post("/{run_id}/revise", response_model=AgentRunView)
def revise_agent_run(run_id: str, payload: ReviseAgentRunRequest) -> AgentRunView:
    run = revise_demo_run(run_id, payload.expected_diners, payload.budget_limit_cents)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run
