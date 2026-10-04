"""Boundaries and windows: hold threshold inclusivity, quality threshold
boundary, half-open wave windows, closed enrollment windows."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    affiliate_additional_practice,
    approve_enrollment,
    complete_wave_and_refresh,
    create_pool,
    create_statement,
    create_wave_for,
    enter_allocation,
    finalize_statement,
    get_success_data,
    post_batch,
    set_clock,
    settle_batch,
    setup_affiliated,
    setup_group_market,
    setup_onboarding_with_active_contract,
    setup_two_affiliated_practices,
    submit_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)

GA = TEST_USERS["group_admin_headers"]
GFC = TEST_USERS["group_financial_controller_headers"]
CC = TEST_USERS["credentialing_coordinator_headers"]


# ---------------------------------------------------------------------------
# Difficulty queue: boundary_precision_check
# ---------------------------------------------------------------------------

def test_distribution_hold_boundary_exact_threshold_pays(api):
    """PRD §3.6: "Third, the group's `distribution_hold_threshold_cents`
    decides: a payable total at or above the threshold pays out in full —
    `payout_cents` equals the payable total and `carried_forward_out_cents` is
    zero — while a payable total strictly below the threshold pays nothing
    this month and carries the entire payable total forward into
    `carried_forward_out_cents`."
    PRD §3.6: "The boundary is inclusive on the paying side: exactly the
    threshold pays out."

    Design: Difficulty/boundary_precision_check/distribution_hold_boundary_exact_threshold_pays_one_below_holds
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    # gross 5376 -> fee round_half_up(376.32) = 376 -> net 5000: exactly the
    # default 5,000-cent hold threshold.
    batch = post_batch(practice, contract, period="2026-09", posted_amount_cents=5376)
    settle_batch(batch, 0)
    final = finalize_statement(create_statement(practice, period="2026-09"))
    assert final["gross_collections_cents"] == 5376
    assert final["shared_services_fee_cents"] == 376
    assert final["net_distribution_cents"] == 5000
    assert final["payout_cents"] == 5000
    assert final["carried_forward_out_cents"] == 0


def test_distribution_hold_boundary_one_cent_below_holds(api):
    """PRD §3.6: "while a payable total strictly below the threshold pays
    nothing this month and carries the entire payable total forward into
    `carried_forward_out_cents`."

    Design: Difficulty/boundary_precision_check/distribution_hold_boundary_exact_threshold_pays_one_below_holds
    """
    ctx = setup_affiliated()
    practice = ctx["practice"]
    contract = ctx["contract"]

    # gross 5375 -> fee round_half_up(376.25) = 376 -> net 4999: one below.
    batch = post_batch(practice, contract, period="2026-09", posted_amount_cents=5375)
    settle_batch(batch, 0)
    final = finalize_statement(create_statement(practice, period="2026-09"))
    assert final["gross_collections_cents"] == 5375
    assert final["shared_services_fee_cents"] == 376
    assert final["net_distribution_cents"] == 4999
    assert final["payout_cents"] == 0
    assert final["carried_forward_out_cents"] == 4999


def test_incentive_quality_threshold_exactly_60_scores(api):
    """PRD §3.7: "Allocation evaluates every `ENTERED` allocation: those at
    or above the threshold become `SCORED`; those strictly below become
    `INELIGIBLE` with `share_cents` zero and `weight` null."

    Design: Difficulty/boundary_precision_check/incentive_quality_threshold_exactly_60_scores_59_point_9_ineligible
    """
    ctx = setup_affiliated()
    pool = create_pool(ctx["contract"], period="2026-09", pool_amount_cents=1000000)
    alloc = enter_allocation(pool, ctx["practice"], quality_score=60.0, attributed_lives=1000)
    validate_success(api.close_entries_incentive_pool(pool["id"], GFC))
    validate_success(api.allocate_incentive_pool(pool["id"], GFC))

    after = validate_success(api.get_incentive_allocation(alloc["id"], GA))
    assert after["status"] == "SCORED"
    assert after["weight"] == pytest.approx(60000.0, abs=1e-6)
    assert after["share_cents"] == 1000000

    pool_after = validate_success(api.get_incentive_pool(pool["id"], GA))
    assert pool_after["allocated_total_cents"] == 1000000


def test_incentive_quality_threshold_59_point_9_ineligible(api):
    """PRD §3.7: "Allocation evaluates every `ENTERED` allocation: those at
    or above the threshold become `SCORED`; those strictly below become
    `INELIGIBLE` with `share_cents` zero and `weight` null."
    PRD §3.7: "requires at least one `ENTERED` allocation whose `quality_score`
    is at least the pool's `quality_threshold`, else
    `ERR_NO_ELIGIBLE_ALLOCATIONS`."

    Design: Difficulty/boundary_precision_check/incentive_quality_threshold_exactly_60_scores_59_point_9_ineligible
    """
    ctx = setup_two_affiliated_practices()
    pool = create_pool(ctx["contract"], period="2026-09", pool_amount_cents=1000000)
    alloc_pass = enter_allocation(pool, ctx["practice"], quality_score=60.0, attributed_lives=1000)
    alloc_fail = enter_allocation(pool, ctx["practice2"], quality_score=59.9, attributed_lives=1000)
    validate_success(api.close_entries_incentive_pool(pool["id"], GFC))
    validate_success(api.allocate_incentive_pool(pool["id"], GFC))

    fail_after = validate_success(api.get_incentive_allocation(alloc_fail["id"], GA))
    assert fail_after["status"] == "INELIGIBLE"
    assert fail_after["share_cents"] == 0
    assert fail_after["weight"] is None

    pass_after = validate_success(api.get_incentive_allocation(alloc_pass["id"], GA))
    assert pass_after["status"] == "SCORED"
    assert pass_after["share_cents"] == 1000000


# ---------------------------------------------------------------------------
# Difficulty queue: resource_temporal_overlap
# ---------------------------------------------------------------------------

def test_wave_windows_half_open_shared_boundary_allowed(api):
    """PRD §2.10: "Wave cutover windows are half-open intervals: the start
    date is inclusive and the end date is exclusive, so one wave's
    `cutover_end_date` may coincide with another wave's `cutover_start_date`
    in the same market without overlap."

    Design: Difficulty/resource_temporal_overlap/wave_windows_half_open_shared_boundary_allowed_one_day_earlier_rejected
    """
    ctx = setup_group_market()
    wave1 = create_wave_for(ctx["market"])
    assert wave1["status"] == "PLANNED"

    # Adjacent: start == existing end shares only the boundary instant.
    wave2 = validate_success(api.create_implementation_wave(
        {
            "market_id": ctx["market"]["id"],
            "wave_code": "W2-ADJ",
            "cutover_start_date": "2026-12-31",
            "cutover_end_date": "2027-03-31",
        },
        GA,
    ), expected_status=201)
    assert wave2["status"] == "PLANNED"

    rows, meta = validate_paginated(api.list_implementation_waves(GA))
    assert len(rows) == 2


def test_wave_windows_one_day_overlap_rejected(api):
    """PRD §3.3: "Within one market, cutover windows of waves not yet
    `COMPLETE` must not overlap under half-open semantics — a shared boundary
    instant is permitted — and an overlapping plan is rejected with
    `ERR_WAVE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/wave_windows_half_open_shared_boundary_allowed_one_day_earlier_rejected
    """
    ctx = setup_group_market()
    create_wave_for(ctx["market"])  # occupies [2026-08-01, 2026-12-31)

    validate_success(api.create_implementation_wave(
        {
            "market_id": ctx["market"]["id"],
            "wave_code": "W2-ADJ",
            "cutover_start_date": "2026-12-31",
            "cutover_end_date": "2027-03-31",
        },
        GA,
    ), expected_status=201)

    # 2026-12-30 lies inside [2026-08-01, 2026-12-31): overlap with W1.
    resp = api.create_implementation_wave(
        {
            "market_id": ctx["market"]["id"],
            "wave_code": "W3-OVER",
            "cutover_start_date": "2026-12-30",
            "cutover_end_date": "2027-03-31",
        },
        GA,
    )
    validate_error(resp, ApiErrorId.ERR_WAVE_WINDOW_OVERLAP, expected_status=409)

    rows, meta = validate_paginated(api.list_implementation_waves(GA))
    assert len(rows) == 2


def test_enrollment_window_day_after_termination_is_free(api):
    """PRD §2.10: "Credentialing enrollment windows, by contrast, are
    closed intervals over `[effective_date, termination_date]`: the
    termination day itself is occupied, and the next day is free."

    Design: Difficulty/resource_temporal_overlap/enrollment_windows_closed_interval_termination_day_occupied_next_day_free
    """
    ctx = setup_affiliated()
    provider = ctx["provider"]
    contract = ctx["contract"]

    # Close the existing window at 2027-02-28.
    validate_success(api.terminate_credentialing_enrollment(
        ctx["enrollment"]["id"], {"termination_date": "2027-02-28"}, CC
    ))

    set_clock("2026-12-03T00:00:00Z")
    # application 2026-12-03 + 90-day STANDARD lag = 2027-03-03: the day after
    # the closed window's termination date — free.
    enrollment = submit_enrollment(
        provider, contract, channel="STANDARD", requested_effective_date="2027-03-03"
    )
    approved = validate_success(api.approve_credentialing_enrollment(enrollment["id"], CC))
    assert approved["status"] == "EFFECTIVE"
    assert approved["effective_date"] == "2027-03-03"


def test_enrollment_window_termination_day_itself_is_occupied(api):
    """PRD §3.4: "Approval also enforces window exclusivity: the closed
    interval from the new enrollment's `effective_date` through its
    `termination_date` must not overlap any other non-`TERMINATED` enrollment
    for the same provider and contract — under closed-interval semantics the
    termination day itself is occupied and the next day is free — and an
    overlap is rejected with `ERR_ENROLLMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/enrollment_windows_closed_interval_termination_day_occupied_next_day_free
    """
    ctx = setup_affiliated()
    provider = ctx["provider"]
    contract = ctx["contract"]

    # Existing window [2026-11-30, 2027-02-28] (terminated but the closed
    # interval still occupies through the termination day).
    validate_success(api.terminate_credentialing_enrollment(
        ctx["enrollment"]["id"], {"termination_date": "2027-02-28"}, CC
    ))

    set_clock("2026-12-03T00:00:00Z")
    # EXPEDITED: application 2026-12-03 + 30 days = 2027-01-02, inside the
    # closed window; requested 2027-01-15 is within the 45-day span cap.
    enrollment = submit_enrollment(
        provider, contract, channel="EXPEDITED", requested_effective_date="2027-01-15"
    )
    resp = api.approve_credentialing_enrollment(enrollment["id"], CC)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_WINDOW_OVERLAP, expected_status=409)

    after = validate_success(api.get_credentialing_enrollment(enrollment["id"], CC))
    assert after["status"] == "SUBMITTED"
