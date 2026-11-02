"""Request bodies for the REST API (Pydantic validates them before our code runs)."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderLineIn(BaseModel):
    sku: str = Field(min_length=1, max_length=30, description="Product SKU, e.g. BOTTLE-1L")
    qty: int = Field(gt=0, le=100_000, description="Quantity ordered; must be greater than 0")
    unit_price: Decimal = Field(ge=0, le=Decimal("99999999.99"), description="Price per unit")

    @field_validator("sku")
    @classmethod
    def _upper_sku(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("unit_price")
    @classmethod
    def _two_decimals(cls, value: Decimal) -> Decimal:
        # 12.5 and 12.50 should count as the same request for idempotency.
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class OrderCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "partner_code": "PEAK",
                    "po_number": "PK-API-0001",
                    "requested_ship_date": "2030-01-15",
                    "lines": [
                        {"sku": "BOTTLE-1L", "qty": 24, "unit_price": 28.80},
                        {"sku": "LAMP-HEAD", "qty": 6, "unit_price": 41.60},
                    ],
                }
            ]
        }
    )

    partner_code: str = Field(min_length=1, max_length=20, description="SWIFT, PEAK or GRANITE")
    po_number: str = Field(min_length=1, max_length=30, description="Customer's purchase order number")
    requested_ship_date: date | None = None
    lines: list[OrderLineIn] = Field(min_length=1, max_length=200)


class ShipRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"carrier": "UPS", "tracking_number": "1Z999AA10123456784"}]}
    )

    carrier: str = Field(min_length=1, max_length=30)
    tracking_number: str = Field(min_length=1, max_length=50)
