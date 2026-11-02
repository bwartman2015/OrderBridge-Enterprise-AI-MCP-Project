"""Dashboard page and its data endpoint."""


def test_dashboard_page(api):
    r = api.get("/dashboard")
    assert r.status_code == 200
    assert "OrderBridge" in r.text and "/dashboard/data" in r.text


def test_dashboard_data(api):
    d = api.get("/dashboard/data").json()
    assert set(d) >= {"recent_orders", "low_stock", "pending_approvals", "audit", "outbox", "status_counts"}
    assert d["at_risk_count"] == 5
    assert len(d["low_stock"]) == 4
    assert d["purchase_orders"][0]["po_number"] == "RPO-000001"
