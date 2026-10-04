"""Cross-category validation priority pairs (PRD §2.9 ladder)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    brooder_verify,
    create_account,
    create_finalized_propane_sale,
    create_open_store,
    create_provisional_sale,
    create_weighted_sale_payload,
    post_care_log,
    set_clock,
    setup_reserved_order,
    validate_error,
    validate_success,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

FALL_NOW = "2026-09-20T10:00:00Z"


def test_fulfill_state_error_beats_care_log_staleness(api):
    """PRD §2.9: "resource state preconditions at priority 7 (the campaign, schedule, lot, order, sale, account, and event state errors, plus the generic `ERR_INVALID_STATE_TRANSITION`, HTTP 409). Safety rules — brooder checks, brooder freshness, care-log freshness, the hazmat cap, vaccine records — are priority 8 (HTTP 422)."
    PRD §3.4: "an order that a cascade has already moved to `CANCELLED` or `EXPIRED` fails with `ERR_INVALID_STATE_TRANSITION`."

    Design: Difficulty/priority_pair_validation_conflict/fulfill_state_lot_closed_beats_safety_care_log_stale
    """
    ctx = setup_reserved_order()
    brooder_verify(ctx["order"]["id"])
    post_care_log(ctx["lot"]["id"], "FEEDING")

    # Clock moves so the care log is 20h stale at trigger time, then the lot
    # closes: the cascade expires the BROODER_VERIFIED order (state failure)
    # while the stale care log (safety failure) also holds.
    set_clock("2026-03-11T06:00:00Z")
    validate_success(api.close_lot_sale(ctx["lot"]["id"], {}, MGR))

    order = validate_success(api.get_chick_order(ctx["order"]["id"], MGR))
    assert order["status"] == "EXPIRED"

    resp = api.fulfill_chick_order(ctx["order"]["id"], ASSOC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_fulfill_state_error_reported_even_when_lot_also_closed(api):
    """PRD §2.9: "resource state preconditions at priority 7 (the campaign, schedule, lot, order, sale, account, and event state errors, plus the generic `ERR_INVALID_STATE_TRANSITION`, HTTP 409). Safety rules — brooder checks, brooder freshness, care-log freshness, the hazmat cap, vaccine records — are priority 8 (HTTP 422)."
    PRD §3.2: "each lot closure expires its `RESERVED` and `BROODER_VERIFIED` chick orders to `EXPIRED` with the reserved quantity released back to `quantity_on_hand`."

    Design: Difficulty/priority_pair_validation_conflict/fulfill_state_lot_closed_beats_safety_care_log_stale
    """
    ctx = setup_reserved_order()
    brooder_verify(ctx["order"]["id"])
    post_care_log(ctx["lot"]["id"], "FEEDING")
    set_clock("2026-03-11T06:00:00Z")
    validate_success(api.close_lot_sale(ctx["lot"]["id"], {}, MGR))

    resp = api.fulfill_chick_order(ctx["order"]["id"], ASSOC)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    # The cascade's release also ran before the rejected fulfill.
    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["status"] == "SALE_CLOSED"
    assert lot["quantity_on_hand"] == 100


def test_hazmat_cap_beats_insufficient_points(api):
    """PRD §2.9: "Safety rules — brooder checks, brooder freshness, care-log freshness, the hazmat cap, vaccine records — are priority 8 (HTTP 422). ... Fiscal sufficiency (priority 11, `ERR_INSUFFICIENT_POINTS`, HTTP 422) and referential integrity of reversal entries ... close the ladder."
    PRD §3.6: "These checks surface in the global validation order of §2.9 — sale state first, then the hazmat safety cap, then tare feasibility, then point sufficiency."

    Design: Difficulty/priority_pair_validation_conflict/propane_hazmat_cap_beats_insufficient_points
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account()  # zero points: any redemption is insufficient

    # Two 20-gallon finalizations saturate the 40-gallon daily hazmat cap.
    create_finalized_propane_sale(store)
    create_finalized_propane_sale(store)

    sale = create_provisional_sale(
        store,
        sale_kind="PROPANE_EXCHANGE",
        container_class="CYLINDER_20",
        gross_weight_lbs=40,
        loyalty_account_id=account["id"],
    )
    resp = api.finalize_weighted_sale(
        sale["id"], {"measured_tare_lbs": 17, "redeem_points": 9999}, ASSOC
    )
    validate_error(resp, ApiErrorId.ERR_HAZMAT_DAILY_CAP_EXCEEDED)

    sale_after = validate_success(api.get_weighted_sale(sale["id"], ASSOC))
    assert sale_after["status"] == "PROVISIONAL"  # no partial finalize


def test_hazmat_cap_violation_leaves_account_points_untouched(api):
    """PRD §3.6: "For a propane exchange, a safety cap interposes before money moves: the store's `hazmat_gallons_used_today` plus this sale's `propane_gallons` must not exceed the daily hazmat cap of 40 gallons, or finalization fails with `ERR_HAZMAT_DAILY_CAP_EXCEEDED`."
    PRD §3.7: "The `points_balance`, by contrast, is the plain sum of `points_delta` over all ledger entries regardless of age or tier-counting"

    Design: Difficulty/priority_pair_validation_conflict/propane_hazmat_cap_beats_insufficient_points
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account()

    create_finalized_propane_sale(store)
    create_finalized_propane_sale(store)

    sale = create_provisional_sale(
        store,
        sale_kind="PROPANE_EXCHANGE",
        container_class="CYLINDER_20",
        gross_weight_lbs=40,
        loyalty_account_id=account["id"],
    )
    validate_error(
        api.finalize_weighted_sale(
            sale["id"], {"measured_tare_lbs": 17, "redeem_points": 9999}, ASSOC
        ),
        ApiErrorId.ERR_HAZMAT_DAILY_CAP_EXCEEDED,
    )

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert acct["points_balance"] == 0
    sale_after = validate_success(api.get_weighted_sale(sale["id"], ASSOC))
    assert sale_after["status"] == "PROVISIONAL"
    assert sale_after["final_total_cents"] is None
