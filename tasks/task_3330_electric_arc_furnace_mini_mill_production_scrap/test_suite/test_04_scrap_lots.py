"""Scrap lot receipt corners: moisture boundary and dry_tons (PRD §3.2)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    make_mill, make_contract,
)

PO = TEST_USERS["procurement_officer_headers"]


def _lot_payload(**overrides):
    payload = {
        "received_on": "2026-09-03",
        "tons_received": 10,
        "moisture_pct": 0.0,
        "cu_pct": 0.001,
        "mn_pct": 0.004,
    }
    payload.update(overrides)
    return payload


def test_scrap_lot_moisture_boundary_and_dry_tons():
    """PRD §3.2: "a `moisture_pct` moisture fraction of gross weight that defaults to
    0.0 and must lie between 0.0 and 0.30 inclusive"
    PRD §3.2: "The server computes the lot's `dry_tons` as `tons_received` multiplied
    by one minus `moisture_pct`, initializes `remaining_tons` to that dry figure, sets
    the lot `status` to `RECEIVED`"

    Design: Corner/entities/scrap_lot_moisture_boundary_and_dry_tons
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract = make_contract(mill["id"], supplier_name="River Metals Recycling",
                             contract_price_cents=39000, committed_tons=100)

    ok = validate_success(
        api_client.record_lot(mill["id"], contract["id"],
                              _lot_payload(moisture_pct=0.30), PO),
        201,
    )
    assert ok["dry_tons"] == 7.0, f"dry_tons must be 10*(1-0.30)=7.0, got {ok['dry_tons']}"
    assert ok["remaining_tons"] == 7.0
    assert ok["status"] == "RECEIVED"

    bad = api_client.record_lot(
        mill["id"], contract["id"],
        _lot_payload(received_on="2026-09-04", moisture_pct=0.31), PO,
    )
    validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST, 400)
