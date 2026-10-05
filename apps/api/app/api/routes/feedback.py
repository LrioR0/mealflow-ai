"""反馈聚合路由（docs/api.md：GET /feedback/summary、每日菜单与反馈）。"""

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.feedback import DailyFeedbackDay, FeedbackSummaryView
from app.services.feedback_service import daily_feedback, feedback_summary

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.get("/summary", response_model=FeedbackSummaryView)
def get_feedback_summary(
    workspace_id: str = Query(min_length=1),
    meal_service_id: str = Query(min_length=1),
) -> FeedbackSummaryView:
    try:
        return feedback_summary(workspace_id, meal_service_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/daily", response_model=list[DailyFeedbackDay])
def get_daily_feedback(
    workspace_id: str = Query(min_length=1),
) -> list[DailyFeedbackDay]:
    try:
        return daily_feedback(workspace_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
