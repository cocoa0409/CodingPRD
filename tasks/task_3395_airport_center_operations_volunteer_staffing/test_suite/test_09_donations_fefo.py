"""Donated inventory: FEFO head enforcement and created_at tie-break,
exact depletion, expired-lot and over-quantity consume rejections."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    TEST_USERS,
    assert_donation_lot,
    consume_lot,
    create_center,
    create_donation_lot,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

MGR = TEST_USERS["manager_headers"]


def test_fefo_head_enforced(api: ApiClient):
    """PRD §3.6: "The candidate set is the center's `AVAILABLE` lots with `remaining_qty` greater than 0 and `expiry_date` on or after the current clock date; the FEFO head is the candidate with the earliest `expiry_date`, ties broken by `created_at` ascending — never by `id`."
    PRD §3.6: "Consuming a lot that is not the FEFO head is rejected with `ERR_FEFO_VIOLATION`, and asking for more than the lot's `remaining_qty` is `ERR_INSUFFICIENT_QUANTITY`."

    Design: Corner/calculations/fefo_head_enforced
    """
    set_clock()
    center = create_center(
        name="Beth Center",
        airport_code="DAL",
        occupancy_cap=25,
        required_daily_confirmed_assignments=1,
    )
    lot_a = create_donation_lot(
        center["id"],
        item_name="chips",
        received_qty=5,
        expiry_date="2026-09-20",
        declared_value_cents=300,
    )
    lot_b = create_donation_lot(
        center["id"],
        item_name="fruit cups",
        received_qty=5,
        expiry_date="2026-09-10",
        declared_value_cents=300,
    )

    # Lot B expires earlier (2026-09-10 < 2026-09-20), so B is the head.
    denied = api.consume_donation_lot(lot_a["id"], {"quantity": 1}, MGR)
    validate_error(denied, ApiErrorId.ERR_FEFO_VIOLATION)

    ok = api.consume_donation_lot(lot_b["id"], {"quantity": 1}, MGR)
    data = validate_success(ok, 200)
    assert data["remaining_qty"] == 4, (
        f"consuming the FEFO head succeeds and decrements, got "
        f"{data['remaining_qty']}"
    )
    assert data["status"] == "AVAILABLE"


def test_fefo_tiebreak_earliest_created(api: ApiClient):
    """PRD §3.6: "The candidate set is the center's `AVAILABLE` lots with `remaining_qty` greater than 0 and `expiry_date` on or after the current clock date; the FEFO head is the candidate with the earliest `expiry_date`, ties broken by `created_at` ascending — never by `id`."

    Design: Corner/calculations/fefo_tiebreak_earliest_created
    """
    set_clock()
    center = create_center(
        name="Gimel Center",
        airport_code="HRL",
        occupancy_cap=25,
        required_daily_confirmed_assignments=1,
    )
    # Identical expiry dates: the earlier-created lot (C) is the head.
    lot_c = create_donation_lot(
        center["id"],
        item_name="soap",
        category="HYGIENE",
        received_qty=3,
        expiry_date="2026-09-15",
        declared_value_cents=100,
    )
    lot_d = create_donation_lot(
        center["id"],
        item_name="soap",
        category="HYGIENE",
        received_qty=3,
        expiry_date="2026-09-15",
        declared_value_cents=100,
    )

    denied = api.consume_donation_lot(lot_d["id"], {"quantity": 1}, MGR)
    validate_error(denied, ApiErrorId.ERR_FEFO_VIOLATION)

    ok = api.consume_donation_lot(lot_c["id"], {"quantity": 1}, MGR)
    data = validate_success(ok, 200)
    assert data["remaining_qty"] == 2, (
        f"the earlier-created lot is the FEFO head and is consumable, got "
        f"remaining {data['remaining_qty']}"
    )


def test_consume_exact_depletion_boundary(api: ApiClient):
    """PRD §3.6: "A successful consume decrements `remaining_qty` by the quantity; a lot drawn to exactly 0 becomes `DEPLETED`, while a partial consume leaves the lot `AVAILABLE` with stock remaining."
    PRD §3.6: "When the candidate set is empty, the failure is `ERR_LOT_EXPIRED` if the target lot itself is expired — its `expiry_date` earlier than the current date — and `ERR_INVALID_STATE` when the target is simply not `AVAILABLE`."
    PRD §3.6: "`DEPLETED` and `DISCARDED_EXPIRED` are terminal."

    Design: Difficulty/boundary_precision_check/consume_exact_depletion_boundary
    """
    set_clock()
    center = create_center(
        name="Mu Center",
        airport_code="PHX",
        occupancy_cap=30,
        required_daily_confirmed_assignments=2,
    )
    lot = create_donation_lot(
        center["id"],
        item_name="water case",
        category="BEVERAGE",
        received_qty=5,
        expiry_date="2026-09-20",
        declared_value_cents=400,
    )

    # quantity == remaining_qty exactly: allowed, and depletes the lot.
    ok = api.consume_donation_lot(lot["id"], {"quantity": 5}, MGR)
    data = validate_success(ok, 200)
    assert data["remaining_qty"] == 0
    assert data["status"] == "DEPLETED", (
        f"a lot drawn to exactly 0 becomes DEPLETED, got {data['status']!r}"
    )

    denied = api.consume_donation_lot(lot["id"], {"quantity": 1}, MGR)
    validate_error(denied, ApiErrorId.ERR_INVALID_STATE)


def test_lot_expired_consume_rejected(api: ApiClient):
    """PRD §3.6: "When the candidate set is empty, the failure is `ERR_LOT_EXPIRED` if the target lot itself is expired — its `expiry_date` earlier than the current date — and `ERR_INVALID_STATE` when the target is simply not `AVAILABLE`."
    PRD §3.6: "Lots whose `expiry_date` falls behind the current clock date are moved to `DISCARDED_EXPIRED` by the operations checkpoint and leave the FEFO candidate set — and, as §3.8 details, the center's donation value totals."

    Design: Corner/errors/lot_expired_consume_rejected
    """
    set_clock()
    center = create_center(
        name="Vav2 Center",
        airport_code="CID",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    lot = create_donation_lot(
        center["id"],
        item_name="milk boxes",
        category="BEVERAGE",
        received_qty=4,
        expiry_date="2026-09-05",
        declared_value_cents=200,
    )

    # Expiry 2026-09-05 is now in the past; no run_ops has discarded the
    # lot yet, but it is already excluded from the FEFO candidate set.
    set_clock("2026-09-06T00:00:00Z")
    resp = api.consume_donation_lot(lot["id"], {"quantity": 1}, MGR)
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED)

    rows, _meta = validate_paginated(api.list_donation_lots(center["id"], MGR))
    assert rows[0]["id"] == lot["id"]
    assert rows[0]["remaining_qty"] == 4, "the rejected consume decrements nothing"
    assert rows[0]["status"] == "AVAILABLE", (
        "only the operations checkpoint moves the lot to DISCARDED_EXPIRED"
    )


def test_consume_over_remaining_rejected(api: ApiClient):
    """PRD §3.6: "Consuming a lot that is not the FEFO head is rejected with `ERR_FEFO_VIOLATION`, and asking for more than the lot's `remaining_qty` is `ERR_INSUFFICIENT_QUANTITY`."

    Design: Corner/errors/consume_over_remaining_rejected
    """
    set_clock()
    center = create_center(
        name="Zayin2 Center",
        airport_code="DBQ",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    lot = create_donation_lot(
        center["id"],
        item_name="trail mix",
        received_qty=5,
        expiry_date="2026-09-20",
        declared_value_cents=250,
    )

    resp = api.consume_donation_lot(lot["id"], {"quantity": 6}, MGR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_QUANTITY)

    rows, _meta = validate_paginated(api.list_donation_lots(center["id"], MGR))
    assert rows[0]["remaining_qty"] == 5, (
        "an over-quantity rejection must not decrement remaining_qty"
    )
    assert rows[0]["status"] == "AVAILABLE"
