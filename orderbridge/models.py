"""SQLAlchemy ORM models. These mirror db/schema.sql, which is the source of truth."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, ForeignKey, ForeignKeyConstraint, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

TimestampTZ = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    pass


class Partner(Base):
    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(10))
    edi_isa_id: Mapped[str] = mapped_column(String(15), unique=True)


class Product(Base):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(30), primary_key=True)
    description: Mapped[str] = mapped_column(String(200))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    reorder_point: Mapped[int] = mapped_column(Integer)
    reorder_qty: Mapped[int] = mapped_column(Integer)
    lead_time_days: Mapped[int] = mapped_column(Integer)

    inventory: Mapped[list[Inventory]] = relationship(
        back_populates="product", order_by="Inventory.warehouse"
    )


class Inventory(Base):
    __tablename__ = "inventory"

    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"), primary_key=True)
    warehouse: Mapped[str] = mapped_column(String(20), primary_key=True)
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    allocated: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship(back_populates="inventory")

    @property
    def available(self) -> int:
        """Stock that is physically here and not promised to another order."""
        return self.on_hand - self.allocated


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"))
    po_number: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(15), default="RECEIVED")
    requested_ship_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())

    partner: Mapped[Partner] = relationship()
    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", order_by="OrderLine.line_no", cascade="all, delete-orphan"
    )
    allocations: Mapped[list[OrderAllocation]] = relationship(
        order_by="OrderAllocation.id", cascade="all, delete-orphan"
    )
    shipments: Mapped[list[Shipment]] = relationship(order_by="Shipment.id")


class OrderLine(Base):
    __tablename__ = "order_lines"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped[Order] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class OrderAllocation(Base):
    __tablename__ = "order_allocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "line_no"], ["order_lines.order_id", "order_lines.line_no"]
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"))
    warehouse: Mapped[str] = mapped_column(String(20))
    qty: Mapped[int] = mapped_column(Integer)


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    carrier: Mapped[str] = mapped_column(String(30))
    tracking_number: Mapped[str] = mapped_column(String(50))
    shipped_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())


class ReplenishmentProposal(Base):
    __tablename__ = "replenishment_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"))
    qty: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    proposed_by: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10), default="PENDING")
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decided_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    decision_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())

    product: Mapped[Product] = relationship()


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(30), unique=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("replenishment_proposals.id"))
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(10), default="OPEN")
    approved_by: Mapped[str] = mapped_column(String(100))
    expected_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())
    actor: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(30))
    tool_or_endpoint: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[str] = mapped_column(String(10))
    detail: Mapped[str | None] = mapped_column(Text)


class OutboxEvent(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(TimestampTZ)
    last_error: Mapped[str | None] = mapped_column(Text)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=func.now())
