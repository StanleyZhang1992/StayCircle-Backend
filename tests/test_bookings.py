from __future__ import annotations

from typing import Tuple

from fastapi.testclient import TestClient


def signup(client: TestClient, email: str, password: str, role: str | None = None) -> Tuple[str, dict]:
    payload = {"email": email, "password": password}
    if role:
        payload["role"] = role
    r = client.post("/auth/signup", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    return data["access_token"], data["user"]


def login(client: TestClient, email: str, password: str) -> Tuple[str, dict]:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    return data["access_token"], data["user"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_property(client: TestClient, token: str, title: str, price_cents: int) -> dict:
    r = client.post("/api/v1/properties", headers=auth_headers(token), json={"title": title, "price_cents": price_cents})
    assert r.status_code == 201, r.text
    return r.json()


def create_booking(client: TestClient, token: str, property_id: int, start_date: str, end_date: str) -> dict:
    r = client.post(
        "/api/v1/bookings",
        headers=auth_headers(token),
        json={"property_id": property_id, "start_date": start_date, "end_date": end_date},
    )
    return {"status_code": r.status_code, "data": (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)}


def test_booking_happy_path(client: TestClient):
    # Create landlord and property
    landlord_token, landlord = signup(client, "host@example.com", "changeme123", "landlord")
    prop = create_property(client, landlord_token, "Test Place", 12345)

    # Create tenant and book
    tenant_token, tenant = signup(client, "guest@example.com", "changeme123", "tenant")
    res = create_booking(client, tenant_token, prop["id"], "2025-01-10", "2025-01-12")
    assert res["status_code"] == 201, res["data"]
    booking = res["data"]
    assert booking["property_id"] == prop["id"]
    assert booking["guest_id"] == tenant["id"]
    assert booking["status"] == "reserved"

    # Tenant sees own booking
    r = client.get("/api/v1/bookings/me", headers=auth_headers(tenant_token))
    assert r.status_code == 200
    items = r.json()
    assert any(b["id"] == booking["id"] for b in items)

    # Landlord sees booking for their property
    r = client.get("/api/v1/bookings/me", headers=auth_headers(landlord_token))
    assert r.status_code == 200
    items = r.json()
    assert any(b["id"] == booking["id"] for b in items)


def test_overlap_conflict(client: TestClient):
    landlord_token, _ = signup(client, "host2@example.com", "changeme123", "landlord")
    prop = create_property(client, landlord_token, "Overlap Place", 20000)
    tenant_token, _ = signup(client, "guest2@example.com", "changeme123", "tenant")

    # First booking 10 -> 12
    res1 = create_booking(client, tenant_token, prop["id"], "2025-02-10", "2025-02-12")
    assert res1["status_code"] == 201, res1["data"]

    # Overlapping attempts
    for start, end in [
        ("2025-02-09", "2025-02-11"),
        ("2025-02-11", "2025-02-12"),
        ("2025-02-11", "2025-02-13"),
        ("2025-02-10", "2025-02-12"),
    ]:
        res = create_booking(client, tenant_token, prop["id"], start, end)
        assert res["status_code"] == 409, res["data"]

    # Non-overlapping boundaries (end_date == start_date is not allowed by API)
    res = create_booking(client, tenant_token, prop["id"], "2025-02-12", "2025-02-13")
    assert res["status_code"] == 201, res["data"]


def test_cancel_frees_slot(client: TestClient):
    landlord_token, _ = signup(client, "host3@example.com", "changeme123", "landlord")
    prop = create_property(client, landlord_token, "Cancel Place", 30000)
    tenant_token, _ = signup(client, "guest3@example.com", "changeme123", "tenant")

    res1 = create_booking(client, tenant_token, prop["id"], "2025-03-10", "2025-03-12")
    assert res1["status_code"] == 201, res1["data"]
    booking_id = res1["data"]["id"]

    # Cancel as tenant
    r = client.delete(f"/api/v1/bookings/{booking_id}", headers=auth_headers(tenant_token))
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # Now the same range should be allowed
    res2 = create_booking(client, tenant_token, prop["id"], "2025-03-10", "2025-03-12")
    assert res2["status_code"] == 201, res2["data"]


def test_role_guards(client: TestClient):
    landlord_token, _ = signup(client, "host4@example.com", "changeme123", "landlord")
    prop = create_property(client, landlord_token, "Guard Place", 10000)

    # Landlord cannot create bookings
    res = create_booking(client, landlord_token, prop["id"], "2025-04-10", "2025-04-12")
    assert res["status_code"] == 403, res["data"]

    # Tenant cannot create properties
    tenant_token, _ = signup(client, "guest4@example.com", "changeme123", "tenant")
    r = client.post("/api/v1/properties", headers=auth_headers(tenant_token), json={"title": "Nope", "price_cents": 100})
    assert r.status_code in (401, 403)
