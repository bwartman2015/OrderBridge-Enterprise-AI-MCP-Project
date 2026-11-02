"""Inventory endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from orderbridge.api.deps import get_session
from orderbridge.services.inventory import inventory_snapshot, list_low_stock

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/low-stock", summary="SKUs at or below their reorder point")
def low_stock(session: Session = Depends(get_session)) -> list[dict]:
    return list_low_stock(session)


@router.get("/{sku}", summary="Stock for one SKU, per warehouse")
def get_inventory(sku: str, session: Session = Depends(get_session)) -> dict:
    """On hand, allocated and available (on hand minus allocated) per warehouse."""
    return inventory_snapshot(session, sku)
