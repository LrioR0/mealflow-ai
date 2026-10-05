"""Kiosk 终端路由（docs/api.md、docs/评分终端设计.md）。

设备令牌只能读取当前已发布菜单并提交匿名反馈，不能调用管理端或 Agent 接口；
反馈定位由服务端按设备绑定站点解析，请求体不携带用户身份。
"""

from fastapi import APIRouter, Header, HTTPException, status

from app.schemas.kiosk import FeedbackAccepted, FeedbackCreate, KioskMenuView
from app.services.feedback_service import (
    KioskAuthError,
    NoPublishedMenuError,
    RateLimitedError,
    current_menu,
    submit_feedback,
)

router = APIRouter(prefix="/kiosk", tags=["kiosk"])


@router.get("/current-menu", response_model=KioskMenuView)
def get_current_menu(x_kiosk_token: str | None = Header(default=None)) -> KioskMenuView:
    try:
        return current_menu(x_kiosk_token)
    except KioskAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except NoPublishedMenuError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/feedback", response_model=FeedbackAccepted, status_code=status.HTTP_201_CREATED)
def post_feedback(
    payload: FeedbackCreate,
    x_kiosk_token: str | None = Header(default=None),
) -> FeedbackAccepted:
    try:
        return submit_feedback(x_kiosk_token, payload)
    except KioskAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except RateLimitedError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except NoPublishedMenuError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
