"""Pool periods: close gate on ungraded lots, half-open membership, provisional
statement creation, pool window overlap, and the shoulder-week multiplier."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_pool_payload, close_pool_payload,
    set_clock, create_grower, create_released_variety, create_active_agreement,
    create_plant_lot, plan_planting, confirm_planting, create_lot_in_transit,
    create_harvest_window,
    receive_lot, submit_grade, certify_lot, create_pool, close_pool,
    settle_pool, get_pool, get_harvest_lot, find_statement,
    setup_lot_received, setup_lot_certified,
)

SETTLEMENT = TEST_USERS["settlement_officer_headers"]
STANDARD_SCORES = dict(flavor_brix=9.5, firmness_g=320,
                       appearance_score=75, defect_pct=4.0)


def _corner_pool(api, settle=False):
    """H1 (net 1150 PREMIUM, compliant) plus HY (net 800 STANDARD) received
    exactly at week_end 2026-10-12T00:00:00Z — excluded from the half-open
    pool window. Pool STRAWBERRY [2026-10-05, 2026-10-12) closed at 500."""
    bundle = setup_lot_certified()  # H1 GRADED/CERTIFIED PREMIUM
    set_clock("2026-10-11T18:30:00Z")
    hy = create_lot_in_transit(bundle["planting"], bundle["grower"],
                               harvested_at="2026-10-11T18:00:00Z",
                               gross_weight_kg=900, tare_weight_kg=100)
    set_clock("2026-10-12T00:00:00Z")
    hy = receive_lot(hy["id"], received_at="2026-10-12T00:00:00Z",
                     pulp_temp_c_at_receipt=3.0)
    hy = submit_grade(hy["id"], **STANDARD_SCORES)
    hy = certify_lot(hy["id"])
    pool = create_pool()
    pool = close_pool(pool["id"], 500)
    if settle:
        pool = settle_pool(pool["id"], 520)
    stmt = find_statement(pool["id"], bundle["grower"]["id"])
    return {"bundle": bundle, "hy": get_harvest_lot(hy["id"]),
            "pool": get_pool(pool["id"]), "statement": stmt}


def test_pool_close_blocked_by_ungraded_lot(api):
    """PRD section 3.8: "every harvest lot whose planting's variety has the
    pool's `berry_type` and whose `received_at` falls inside the pooling window
    must have reached a certified grade or outright rejection — that is,
    `grade_status` `CERTIFIED` or `lot_status` `REJECTED` — or the close is
    rejected with `ERR_POOL_HAS_UNGRADED_LOTS`."

    Design: Difficulty/cross_entity_state_dependency/pool_close_requires_certified_lots
    """
    bundle = setup_lot_received()  # H1 received in-window, never graded
    pool = create_pool()
    set_clock("2026-10-12T00:00:00Z")
    resp = api.close_pool_period(pool["id"], close_pool_payload(), SETTLEMENT)
    validate_error(resp, ApiErrorId.ERR_POOL_HAS_UNGRADED_LOTS)
    assert get_pool(pool["id"])["status"] == "OPEN"
    rows, meta = validate_paginated(api.list_settlement_statements(
        SETTLEMENT, params={"pool_period_id": pool["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_pool_close_succeeds_once_lot_certified(api):
    """PRD section 3.8: "Closing also stamps `closed_at` from the logical clock,
    increments the pool's `version` by 1, and moves the pool `OPEN → CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/pool_close_requires_certified_lots
    """
    bundle = setup_lot_received()
    submit_grade(bundle["harvest_lot"]["id"])
    certify_lot(bundle["harvest_lot"]["id"])
    pool = create_pool()
    set_clock("2026-10-12T00:00:00Z")
    closed = close_pool(pool["id"], 500)
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None
    stmt = find_statement(pool["id"], bundle["grower"]["id"])
    assert stmt["status"] == "PROVISIONAL"


def test_pool_membership_half_open_window(api):
    """PRD section 3.8: "The included lots are those with `grade_status`
    `CERTIFIED`, a `grade` other than `REJECT`, a planting whose variety
    matches the pool's `berry_type`, and a `received_at` inside the half-open
    pooling window."

    Design: Corner/calculations/pool_membership_half_open_window
    """
    s = _corner_pool(api, settle=False)
    rows, meta = validate_paginated(api.list_harvest_lots(
        SETTLEMENT, params={"pool_period_id": s["pool"]["id"]}))
    assert len(rows) == 1 and meta["total_count"] == 1
    assert rows[0]["id"] == s["bundle"]["harvest_lot"]["id"]
    h1 = get_harvest_lot(s["bundle"]["harvest_lot"]["id"])
    assert h1["pool_period_id"] == s["pool"]["id"]
    assert h1["lot_gross_provisional_cents"] == 540500
    hy = s["hy"]
    assert hy["pool_period_id"] is None, "received_at == week_end is outside"
    assert hy["lot_status"] == "GRADED"
    assert hy["lot_gross_provisional_cents"] is None


def test_close_creates_provisional_statements_and_stamps_lots(api):
    """PRD section 3.8: "At close, one settlement statement is created per
    grower with at least one included lot, starting in `PROVISIONAL`."
    PRD section 3.8: "Each included lot is stamped with the pool's id as its
    `pool_period_id` and assigned a `lot_gross_provisional_cents`".

    Design: Corner/endpoints/close_creates_provisional_statements_and_stamps_lots
    """
    s = _corner_pool(api, settle=False)
    pool = s["pool"]
    assert pool["status"] == "CLOSED"
    assert pool["total_net_kg"] == 1150
    assert pool["total_weighted_kg"] == 1322.5
    assert pool["gross_pool_revenue_cents"] == 575000
    assert pool["marketing_fee_cents"] == 34500
    assert pool["net_pool_revenue_cents"] == 540500
    assert pool["provisional_pool_rate"] == pytest.approx(408.6957, abs=5e-5)
    assert pool["pool_distributable_cents"] == 540500
    rows, meta = validate_paginated(api.list_settlement_statements(
        SETTLEMENT, params={"pool_period_id": pool["id"]}))
    assert len(rows) == 1 and meta["total_count"] == 1
    stmt = rows[0]
    assert stmt["status"] == "PROVISIONAL"
    assert stmt["provisional_net_cents"] == 540500
    assert stmt["gross_cents"] is None
    assert stmt["net_cents"] is None
    h1 = get_harvest_lot(s["bundle"]["harvest_lot"]["id"])
    assert h1["pool_period_id"] == pool["id"]
    assert h1["lot_gross_provisional_cents"] == 540500
    assert s["hy"]["pool_period_id"] is None


def test_pool_window_overlap_adjacency(api):
    """PRD section 3.8: "One pool per berry type may cover a given week: a new
    pool whose window overlaps an existing pool of the same `berry_type` is
    rejected with `ERR_POOL_WINDOW_OVERLAP` — half-open intervals again, so
    pure adjacency is allowed."

    Design: Corner/validations/pool_window_overlap_adjacency
    """
    set_clock("2026-06-01T00:00:00Z")
    create_pool()  # STRAWBERRY [2026-10-05, 2026-10-12)
    resp = api.create_pool_period(
        create_pool_payload(week_start="2026-10-12T00:00:00Z",
                            week_end="2026-10-19T00:00:00Z"), SETTLEMENT)
    validate_success(resp, 201)
    resp2 = api.create_pool_period(
        create_pool_payload(week_start="2026-10-11T00:00:00Z",
                            week_end="2026-10-18T00:00:00Z"), SETTLEMENT)
    validate_error(resp2, ApiErrorId.ERR_POOL_WINDOW_OVERLAP)


def _shoulder_scenario(api):
    """G2 chain through certified H3 (net 2000 STANDARD, received 2026-10-08)
    and certified H4 (net 1000 STANDARD, received 2026-10-13, 5h compliant)."""
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    g2 = create_grower(legal_name="Coastal Berry Co")
    a2 = create_active_agreement(g2, variety,
                                 cultural_practice_codes=["CONVENTIONAL"])
    l2 = create_plant_lot(a2, variety, quantity_plants=3000)
    create_harvest_window(variety)  # window needed for the confirm booking
    p2 = plan_planting(a2, l2, g2, planned_plants=2500)
    set_clock("2026-08-02T00:00:00Z")
    p2 = confirm_planting(p2, g2, 2500)
    set_clock("2026-10-08T06:30:00Z")
    h3 = create_lot_in_transit(p2, g2, harvested_at="2026-10-08T06:00:00Z",
                               gross_weight_kg=2050, tare_weight_kg=50)
    set_clock("2026-10-08T12:30:00Z")
    h3 = receive_lot(h3["id"], received_at="2026-10-08T12:00:00Z",
                     pulp_temp_c_at_receipt=2.8)
    h3 = submit_grade(h3["id"], **STANDARD_SCORES)
    certify_lot(h3["id"])
    set_clock("2026-10-13T06:30:00Z")
    h4 = create_lot_in_transit(p2, g2, harvested_at="2026-10-13T06:00:00Z",
                               gross_weight_kg=1050, tare_weight_kg=50)
    set_clock("2026-10-13T11:30:00Z")
    h4 = receive_lot(h4["id"], received_at="2026-10-13T11:00:00Z",
                     pulp_temp_c_at_receipt=3.0)
    h4 = submit_grade(h4["id"], **STANDARD_SCORES)
    certify_lot(h4["id"])
    return {"variety": variety, "g2": g2, "h3": h3, "h4": h4}


def test_shoulder_week_multiplier_applied_after_fee(api):
    """PRD section 3.8: "Seventh, the pool rate is the base rate multiplied by
    1.10 and rounded half-up to 4 decimal places when the pool is a shoulder
    week, and simply the base rate otherwise".
    PRD section 3.8: "Eighth, `pool_distributable_cents` is
    `net_pool_revenue_cents` multiplied by 1.10 for a shoulder week — or taken
    unchanged otherwise — rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/pool_rate_conditional_shoulder_mode_a
    """
    s = _shoulder_scenario(api)
    pool = create_pool(week_start="2026-10-12T00:00:00Z",
                       week_end="2026-10-19T00:00:00Z", is_shoulder_week=True)
    set_clock("2026-10-19T00:00:00Z")
    close_pool(pool["id"], 400)
    pool = settle_pool(pool["id"], 400)
    pool = get_pool(pool["id"])
    assert pool["total_net_kg"] == 1000
    assert pool["total_weighted_kg"] == 1000
    assert pool["gross_pool_revenue_cents"] == 400000
    assert pool["marketing_fee_cents"] == 24000
    assert pool["net_pool_revenue_cents"] == 376000
    assert pool["final_pool_rate"] == pytest.approx(413.6, abs=5e-5), (
        "376.0000 x 1.10 shoulder multiplier applied after the fee carve-out")
    assert pool["pool_distributable_cents"] == 413600, (
        "shoulder distributable exceeds net revenue: brand-funded incentive")
    h4 = get_harvest_lot(s["h4"]["id"])
    assert h4["lot_gross_final_cents"] == 413600
    stmt = find_statement(pool["id"], s["g2"]["id"])
    assert stmt["gross_cents"] == 413600
    assert stmt["net_cents"] == 413600


def test_non_shoulder_identical_inputs_price_lower(api):
    """PRD section 3.8: "the pool rate is the base rate multiplied by 1.10 and
    rounded half-up to 4 decimal places when the pool is a shoulder week, and
    simply the base rate otherwise".

    Design: Difficulty/combinatorial_formula/pool_rate_conditional_shoulder_mode_a
    """
    s = _shoulder_scenario(api)
    pool = create_pool()  # [2026-10-05, 2026-10-12), NOT shoulder, price 400
    set_clock("2026-10-12T00:00:00Z")
    close_pool(pool["id"], 400)
    pool = settle_pool(pool["id"], 400)
    pool = get_pool(pool["id"])
    assert pool["total_net_kg"] == 2000  # H3 only
    assert pool["gross_pool_revenue_cents"] == 800000
    assert pool["net_pool_revenue_cents"] == 752000
    assert pool["final_pool_rate"] == pytest.approx(376.0, abs=5e-5), (
        "same price and weight class, no shoulder flag: rate is 10% lower")
    h3 = get_harvest_lot(s["h3"]["id"])
    assert h3["lot_gross_final_cents"] == 752000
