"""REST API tests, including idempotency and validation."""

from tests.helpers import audit_rows, outbox_types

NEW_ORDER = {
    "partner_code": "PEAK",
    "po_number": "PK-API-1",
    "requested_ship_date": "2030-01-15",
    "lines": [{"sku": "BOTTLE-1L", "qty": 5, "unit_price": 28.8}],
}


def test_list_and_get_orders(api):
    orders = api.get("/orders").json()
    assert len(orders) == 40
    one = api.get(f"/orders/{orders[0]['id']}").json()
    assert one["po_number"] == orders[0]["po_number"]
    assert "lines" in one and "shipments" in one
    assert len(api.get("/orders", params={"status": "SHIPPED"}).json()) == 10


def test_unknown_order_is_404(api):
    r = api.get("/orders/99999")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_inventory_endpoint(api):
    r = api.get("/inventory/tent-2p-ult")  # case-insensitive
    assert r.status_code == 200
    body = r.json()
    assert body["sku"] == "TENT-2P-ULT"
    assert {w["warehouse"] for w in body["warehouses"]} == {"WH-EAST", "WH-WEST"}
    assert body["total_available"] == body["total_on_hand"] - body["total_allocated"]
    assert api.get("/inventory/NOPE").status_code == 404


def test_post_requires_idempotency_key(api):
    r = api.post("/orders", json=NEW_ORDER)
    assert r.status_code == 400
    assert "Idempotency-Key" in r.json()["detail"]


def test_idempotent_replay_returns_same_response(api):
    headers = {"Idempotency-Key": "key-1"}
    first = api.post("/orders", json=NEW_ORDER, headers=headers)
    assert first.status_code == 201
    second = api.post("/orders", json=NEW_ORDER, headers=headers)
    assert second.status_code == 201
    assert second.json() == first.json()
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert len(api.get("/orders", params={"limit": 500}).json()) == 41  # 40 seeded + 1
    # Only ONE order.received event despite two calls.
    assert outbox_types().count("order.received") == 1


def test_same_key_different_body_is_409(api):
    headers = {"Idempotency-Key": "key-2"}
    assert api.post("/orders", json=NEW_ORDER, headers=headers).status_code == 201
    changed = {**NEW_ORDER, "lines": [{"sku": "BOTTLE-1L", "qty": 6, "unit_price": 28.8}]}
    r = api.post("/orders", json=changed, headers=headers)
    assert r.status_code == 409
    assert "different request body" in r.json()["detail"]


def test_validation_unknown_sku_and_bad_qty(api):
    bad_sku = {**NEW_ORDER, "lines": [{"sku": "NOT-A-SKU", "qty": 1, "unit_price": 1}]}
    r = api.post("/orders", json=bad_sku, headers={"Idempotency-Key": "k3"})
    assert r.status_code == 422
    assert "Unknown SKU(s): NOT-A-SKU" in r.json()["detail"]

    zero_qty = {**NEW_ORDER, "lines": [{"sku": "BOTTLE-1L", "qty": 0, "unit_price": 1}]}
    r = api.post("/orders", json=zero_qty, headers={"Idempotency-Key": "k4"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "lines.0.qty"
    assert "greater than 0" in r.json()["detail"]


def test_duplicate_po_is_409(api):
    assert api.post("/orders", json=NEW_ORDER, headers={"Idempotency-Key": "a"}).status_code == 201
    r = api.post("/orders", json=NEW_ORDER, headers={"Idempotency-Key": "b"})
    assert r.status_code == 409
    assert "Duplicate PO" in r.json()["detail"]


def test_allocate_then_ship_generates_856(api, edi_dirs):
    created = api.post("/orders", json=NEW_ORDER, headers={"Idempotency-Key": "ship-1"}).json()
    alloc = api.post(f"/orders/{created['id']}/allocate").json()
    assert alloc["allocated"] is True
    r = api.post(f"/orders/{created['id']}/ship", json={"carrier": "ups", "tracking_number": "1Z999"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "SHIPPED"
    assert body["shipments"][0]["carrier"] == "UPS"
    asn = edi_dirs / "outbound" / body["asn_file"]
    assert asn.exists() and "ST*856" in asn.read_text()
    assert "order.shipped" in outbox_types()
    # Shipping an already-shipped order is a conflict.
    assert api.post(f"/orders/{created['id']}/ship", json={"carrier": "UPS", "tracking_number": "x"}).status_code == 409


def test_writes_are_audited(api):
    api.post("/orders", json=NEW_ORDER, headers={"Idempotency-Key": "aud", "X-Actor": "erp-sync"})
    rows = audit_rows()
    assert rows[-1].actor == "erp-sync" and rows[-1].tool_or_endpoint == "POST /orders" and rows[-1].result == "OK"
