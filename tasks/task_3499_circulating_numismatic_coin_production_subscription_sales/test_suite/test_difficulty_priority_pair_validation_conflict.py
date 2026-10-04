"""Difficulty rule priority_pair_validation_conflict (PRD §2.7): when one
request violates two rules on different ladder rungs, the earliest rung that
fails produces the response and later rungs are never consulted — state beats
fiscal, referential beats temporal, referential beats fiscal."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_allocation_payload,
    create_product_payload,
)
from test_helpers.fixtures import (
    create_authorized_purchaser,
    create_denomination,
    create_fed_order,
    create_product,
    create_run,
    set_ap_status,
    set_clock,
    setup_bullion_issue,
)

LIAISON = TEST_USERS["fed_liaison_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
MANAGER = TEST_USERS["program_manager_headers"]


def test_run_start_state_error_beats_blanks_fiscal_error(api):
    """PRD §2.7: "Validations are evaluated as a fixed ladder; the earliest rung
    that fails produces the response, and later rungs are never consulted."
    PRD §2.7 (rung 5): "Transitions carrying a dedicated domain error raise it
    (for example `ERR_RUN_NOT_STARTABLE`, `ERR_ORDER_NOT_PAYABLE`,
    `ERR_LOT_NOT_RECEIVABLE`); any other invalid from-state falls back to
    `ERR_INVALID_STATE_TRANSITION` (422); an OCC mismatch raises
    `ERR_STALE_VERSION` (412)."
    PRD §3.3: "The linked order must be in `SCHEDULED` or `FULFILLING`; starting
    a run that is not in `PLANNED` or `REWORK`, or whose order sits in any other
    state, is rejected with `ERR_RUN_NOT_STARTABLE` (422)."
    PRD §2.7 (rung 10): "Fiscal limits — household order limits
    (`ERR_HOUSEHOLD_LIMIT_EXCEEDED`, 422), bullion pool sufficiency
    (`ERR_POOL_INSUFFICIENT`, 422), and blank stock sufficiency
    (`ERR_BLANKS_INSUFFICIENT`, 422)."

    Design: Difficulty/priority_pair_validation_conflict/run_start_state_error_beats_blanks_fiscal_error
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    create_denomination(api)  # QUARTER with blank_stock_pieces == 0 (no lots)
    fed_order = create_fed_order(api, quantity_ordered_pieces=50000)
    resp = api.cancel_fed_order(fed_order["id"], LIAISON)
    validate_success(resp)
    # Run creation against the CANCELLED order requires only order existence.
    run = create_run(
        api, fed_order["id"], facility="DENVER", press_line="P3",
        planned_start="2026-10-07T08:00:00Z", planned_end="2026-10-07T12:00:00Z",
        planned_quantity=50000)

    # Both gates would fail — order CANCELLED (rung 5) and blank stock 0 <
    # 50000 (rung 10) — and the earlier rung wins.
    resp = api.start_production_run(run["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_STARTABLE)


def test_product_unknown_program_beats_release_gap_temporal(api):
    """PRD §2.7: "Validations are evaluated as a fixed ladder; the earliest rung
    that fails produces the response, and later rungs are never consulted."
    PRD §2.7 (rung 6): "Referential integrity — body references resolve:
    `denomination_code` to an existing denomination (`ERR_UNKNOWN_DENOMINATION`,
    422), a supplied `program_id` to an existing program
    (`ERR_UNKNOWN_PROGRAM`, 422), `product_id` to an existing product
    (`ERR_UNKNOWN_PRODUCT`, 422), a current spot price established for the
    commodity or metal (`ERR_SPOT_PRICE_MISSING`, 422), and the authorized
    purchaser existing in `APPROVED` status (`ERR_AP_NOT_APPROVED`, 422)."
    PRD §2.7 (rung 8): "Temporal rules — press-window overlap
    (`ERR_PRESS_WINDOW_OVERLAP`, 409), release-family gap
    (`ERR_RELEASE_GAP_VIOLATION`, 409), billing due date
    (`ERR_BILLING_NOT_DUE`, 422), and clock monotonicity
    (`ERR_CLOCK_REGRESSION`, 422)."
    PRD §3.6: "Releases within a family must stand at least 24 hours apart: a
    new `release_datetime` less than 24 hours away from any non-`WITHDRAWN`
    product in the same `product_family` is rejected with
    `ERR_RELEASE_GAP_VIOLATION` (409), while a gap of exactly 24 hours passes."

    Design: Difficulty/priority_pair_validation_conflict/product_unknown_program_beats_release_gap_temporal
    """
    create_product(
        api, product_code="GAP-1", product_family="GAPF", product_type="PROOF_SET",
        price_cents=2000, mintage_limit=100, household_order_limit=10,
        release_datetime="2026-10-01T14:00:00Z")

    # Both rules fail — unknown program_id (rung 6) and a 1-hour release gap
    # against GAP-1 (rung 8) — and the earlier rung wins.
    resp = api.create_product(
        create_product_payload(
            product_code="GAP-2", program_id=NON_EXISTENT_UUID,
            product_family="GAPF", product_type="PROOF_SET", price_cents=2000,
            mintage_limit=50, household_order_limit=10,
            release_datetime="2026-10-01T15:00:00Z"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_PROGRAM)


def test_allocation_ap_status_error_beats_pool_fiscal_error(api):
    """PRD §2.7: "Validations are evaluated as a fixed ladder; the earliest rung
    that fails produces the response, and later rungs are never consulted."
    PRD §2.7 (rung 6): "Referential integrity — body references resolve:
    `denomination_code` to an existing denomination (`ERR_UNKNOWN_DENOMINATION`,
    422), a supplied `program_id` to an existing program
    (`ERR_UNKNOWN_PROGRAM`, 422), `product_id` to an existing product
    (`ERR_UNKNOWN_PRODUCT`, 422), a current spot price established for the
    commodity or metal (`ERR_SPOT_PRICE_MISSING`, 422), and the authorized
    purchaser existing in `APPROVED` status (`ERR_AP_NOT_APPROVED`, 422)."
    PRD §2.7 (rung 10): "Fiscal limits — household order limits
    (`ERR_HOUSEHOLD_LIMIT_EXCEEDED`, 422), bullion pool sufficiency
    (`ERR_POOL_INSUFFICIENT`, 422), and blank stock sufficiency
    (`ERR_BLANKS_INSUFFICIENT`, 422)."
    PRD §3.8: "The request names an `authorized_purchaser_id` — the firm must
    exist and be in `APPROVED`, otherwise `ERR_AP_NOT_APPROVED` (422) — a
    `quantity_units` of at least 1 (`ERR_QUANTITY_INVALID`, 400) that does not
    exceed the issue's `remaining_pool_units` (`ERR_POOL_INSUFFICIENT`, 422),
    and the OCC field `expected_bullion_issue_version` described in §2.6."

    Design: Difficulty/priority_pair_validation_conflict/allocation_ap_status_error_beats_pool_fiscal_error
    """
    issue = setup_bullion_issue(api, name="AGE 2026", total_pool_units=10)
    ap = create_authorized_purchaser(api, name="Suspended Dealer", tier="T1")
    set_ap_status(api, ap["id"], "SUSPENDED")

    # Both rules fail — the purchaser is SUSPENDED (rung 6) and 50 > remaining
    # pool 10 (rung 10) — and the earlier rung wins.
    resp = api.create_allocation(
        issue["id"],
        create_allocation_payload(
            authorized_purchaser_id=ap["id"], quantity_units=50,
            expected_bullion_issue_version=issue["version"]),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_AP_NOT_APPROVED)
