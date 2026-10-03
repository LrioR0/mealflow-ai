from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, status

from app.core.config import get_settings
from app.schemas.kiosk import FeedbackAccepted, FeedbackCreate

router = APIRouter(prefix="/kiosk", tags=["kiosk"])


def _check_device_token(token: str | None) -> None:
    settings = get_settings()
    if not settings.demo_mode and not token:
        raise HTTPException(status_code=401, detail="Missing kiosk device token")


@router.get("/current-menu")
def current_menu(x_kiosk_token: str | None = Header(default=None)) -> dict:
    _check_device_token(x_kiosk_token)
    return {
        "meal_service": {"name": "午餐", "expected_diners": 120, "status": "published"},
        "menu": [
            {"name": "番茄炒蛋", "kcal_per_serving": 186, "allergens": ["蛋"]},
            {"name": "土豆烧鸡", "kcal_per_serving": 328, "allergens": []},
            {"name": "清炒时蔬", "kcal_per_serving": 92, "allergens": []},
        ],
    }


@router.post("/feedback", response_model=FeedbackAccepted, status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackCreate,
    x_kiosk_token: str | None = Header(default=None),
) -> FeedbackAccepted:
    _check_device_token(x_kiosk_token)
    # Persistence and per-device rate limiting belong in FeedbackService.
    return FeedbackAccepted(id=str(uuid4()))
