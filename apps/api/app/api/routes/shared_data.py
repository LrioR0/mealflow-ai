from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.db.models import CookingRecord, ProcurementItem, Workspace
from app.db.session import SessionLocal
from app.schemas.shared_data import (
    CookingRecordCreate,
    CookingRecordUpdate,
    CookingRecordView,
    ProcurementItemCreate,
    ProcurementItemUpdate,
    ProcurementItemView,
)

router = APIRouter(tags=["shared-data"])


def _ensure_workspace(session, workspace_id: str) -> None:
    if session.get(Workspace, workspace_id) is None:
        raise HTTPException(status_code=404, detail="工作区不存在")


def _procurement_view(item: ProcurementItem) -> ProcurementItemView:
    return ProcurementItemView(
        id=item.id,
        workspace_id=item.workspace_id,
        ingredient=item.ingredient,
        quantity=item.quantity,
        unit=item.unit,
        checked=item.checked,
        source=item.source,
        source_id=item.source_id,
        checked_at=item.checked_at,
    )


@router.get("/workspaces/{workspace_id}/procurement-items", response_model=list[ProcurementItemView])
def list_procurement_items(workspace_id: str) -> list[ProcurementItemView]:
    with SessionLocal() as session:
        _ensure_workspace(session, workspace_id)
        rows = session.scalars(
            select(ProcurementItem)
            .where(ProcurementItem.workspace_id == workspace_id)
            .order_by(ProcurementItem.checked, ProcurementItem.created_at.desc())
        ).all()
        return [_procurement_view(row) for row in rows]


@router.post("/workspaces/{workspace_id}/procurement-items", response_model=ProcurementItemView, status_code=status.HTTP_201_CREATED)
def create_procurement_item(workspace_id: str, payload: ProcurementItemCreate) -> ProcurementItemView:
    with SessionLocal() as session:
        _ensure_workspace(session, workspace_id)
        item = ProcurementItem(
            workspace_id=workspace_id,
            ingredient=payload.ingredient,
            quantity=payload.quantity,
            unit=payload.unit,
            checked=payload.checked,
            source=payload.source,
            source_id=payload.source_id,
            checked_at=datetime.now(timezone.utc) if payload.checked else None,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return _procurement_view(item)


@router.patch("/procurement-items/{item_id}", response_model=ProcurementItemView)
def update_procurement_item(item_id: str, payload: ProcurementItemUpdate) -> ProcurementItemView:
    with SessionLocal() as session:
        item = session.get(ProcurementItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="采购项不存在")
        for field in ("ingredient", "quantity", "unit"):
            value = getattr(payload, field)
            if value is not None:
                setattr(item, field, value)
        if payload.checked is not None:
            item.checked = payload.checked
            item.checked_at = datetime.now(timezone.utc) if payload.checked else None
        session.commit()
        session.refresh(item)
        return _procurement_view(item)


@router.delete("/procurement-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_procurement_item(item_id: str) -> None:
    with SessionLocal() as session:
        item = session.get(ProcurementItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="采购项不存在")
        session.delete(item)
        session.commit()


def _cooking_view(record: CookingRecord) -> CookingRecordView:
    return CookingRecordView(
        id=record.id,
        workspace_id=record.workspace_id,
        dish_name=record.dish_name,
        cook=record.cook,
        cooked_at=record.cooked_at,
        servings=record.servings,
        duration_minutes=record.duration_minutes,
        difficulty=record.difficulty,
        tags=record.tags or [],
        ingredients=record.ingredients,
        story=record.story,
        steps=record.steps or [],
        rating=float(record.rating),
        next_time_note=record.next_time_note,
        image=record.image,
        reviews=record.reviews or [],
    )


@router.get("/workspaces/{workspace_id}/cooking-records", response_model=list[CookingRecordView])
def list_cooking_records(workspace_id: str) -> list[CookingRecordView]:
    with SessionLocal() as session:
        _ensure_workspace(session, workspace_id)
        rows = session.scalars(
            select(CookingRecord)
            .where(CookingRecord.workspace_id == workspace_id)
            .order_by(CookingRecord.cooked_at.desc(), CookingRecord.created_at.desc())
        ).all()
        return [_cooking_view(row) for row in rows]


@router.post("/workspaces/{workspace_id}/cooking-records", response_model=CookingRecordView, status_code=status.HTTP_201_CREATED)
def create_cooking_record(workspace_id: str, payload: CookingRecordCreate) -> CookingRecordView:
    with SessionLocal() as session:
        _ensure_workspace(session, workspace_id)
        record = CookingRecord(**payload.model_dump(exclude={"workspace_id"}), workspace_id=workspace_id)
        session.add(record)
        session.commit()
        session.refresh(record)
        return _cooking_view(record)


@router.patch("/cooking-records/{record_id}", response_model=CookingRecordView)
def update_cooking_record(record_id: str, payload: CookingRecordUpdate) -> CookingRecordView:
    with SessionLocal() as session:
        record = session.get(CookingRecord, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="下厨记录不存在")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(record, field, value)
        session.commit()
        session.refresh(record)
        return _cooking_view(record)


@router.delete("/cooking-records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cooking_record(record_id: str) -> None:
    with SessionLocal() as session:
        record = session.get(CookingRecord, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="下厨记录不存在")
        session.delete(record)
        session.commit()
