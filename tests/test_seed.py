"""The seed data contains the deliberate demo scenarios."""

from sqlalchemy import func, select

from orderbridge.models import Inventory, Order, OrderAllocation, Partner, Product
from orderbridge.services.inventory import find_at_risk_orders, list_low_stock


def test_seed_volumes(session):
    assert session.scalar(select(func.count()).select_from(Partner)) == 3
    assert session.scalar(select(func.count()).select_from(Product)) == 25
    assert session.scalar(select(func.count()).select_from(Order)) == 40
    warehouses = set(session.scalars(select(Inventory.warehouse)))
    assert warehouses == {"WH-EAST", "WH-WEST"}


def test_low_stock_skus(session):
    assert {s["sku"] for s in list_low_stock(session)} == {"TENT-2P-ULT", "FUEL-230", "FILTER-SQZ", "LAMP-HEAD"}


def test_at_risk_orders_with_exactly_one_short(session):
    at_risk = find_at_risk_orders(session, 2)
    assert len(at_risk) == 5
    short = [o for o in at_risk if not o["can_fully_allocate"]]
    assert len(short) == 1
    assert short[0]["po_number"] == "PK-10005"
    assert short[0]["short_lines"][0]["sku"] == "TENT-2P-ULT"
    assert any("Short on TENT-2P-ULT" in r for r in short[0]["reasons"])


def test_inventory_allocated_matches_allocations(session):
    alloc = dict(
        session.execute(
            select(OrderAllocation.sku + "@" + OrderAllocation.warehouse, func.sum(OrderAllocation.qty)).group_by(
                OrderAllocation.sku, OrderAllocation.warehouse
            )
        ).all()
    )
    for inv in session.scalars(select(Inventory)):
        assert inv.allocated == alloc.get(f"{inv.sku}@{inv.warehouse}", 0)
