"""Job posting pacing: dual-variant calculation, combinatorial cap rules,
budget exhaustion boundary, slot window half-open semantics, and posting
lifecycle preconditions."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    seat_admin_headers, contract_admin_headers,
    setup_assigned_seat, setup_active_posting, set_clock,
    create_posting, add_slot, activate_posting, get_posting, record_spend,
    create_job_posting_payload, create_recruiter, list_seats, assign_first_seat,
    create_and_activate_contract,
)


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/budget_pacing_even_vs_front_loaded_same_spend
# ---------------------------------------------------------------------------

def _setup_two_postings_same_inputs(contract_number="C-PACE-1"):
    ctx = setup_assigned_seat(contract_number=contract_number)
    cid, seat_id = ctx["contract"]["id"], ctx["seat"]["id"]
    jp_even = create_posting(cid, seat_id, title="Even Job")
    jp_front = create_posting(cid, seat_id, title="Front Job", pacing_mode="FRONT_LOADED")
    add_slot(cid, jp_even["id"], slot_date="2026-09-01", reserved_cents=5000)
    add_slot(cid, jp_front["id"], slot_date="2026-09-01", reserved_cents=5000)
    activate_posting(cid, jp_even["id"])
    activate_posting(cid, jp_front["id"])
    return ctx, jp_even, jp_front


def test_pacing_even_rejects_day1_spend_that_front_loaded_accepts():
    """PRD section 3.6: "Under `EVEN` pacing, today's cumulative cap is the
    floor of `budget_cents` multiplied by `elapsed_days` and divided by
    `total_days` — a uniform ramp over the posting's lifetime."
    PRD section 3.6: "Under `FRONT_LOADED` pacing, the first half of the
    period ramps at one-and-a-half times the uniform rate and the second half
    ramps at half the uniform rate."
    PRD section 3.6: "The two variants deliver the same total spend capacity
    by `end_at` but accept a different set of spend events on identical
    inputs; `EVEN` is the uniform ramp, `FRONT_LOADED` concentrates capacity
    in the first half."

    Design: Difficulty/dual_variant_calc/budget_pacing_even_vs_front_loaded_same_spend
    """
    ctx, jp_even, jp_front = _setup_two_postings_same_inputs()
    cid = ctx["contract"]["id"]

    resp_even = record_spend(cid, jp_even["id"], 1200)
    validate_error(resp_even, ApiErrorId.ERR_PACING_VIOLATION)

    resp_front = record_spend(cid, jp_front["id"], 1200)
    data = validate_success(resp_front)
    assert data["spent_cents"] == 1200


def test_pacing_variants_agree_on_spend_beneath_both_caps():
    """PRD section 3.6: "The two variants deliver the same total spend
    capacity by `end_at` but accept a different set of spend events on
    identical inputs; `EVEN` is the uniform ramp, `FRONT_LOADED` concentrates
    capacity in the first half."
    PRD section 3.6: "On acceptance the posting's `spent_cents` increments by
    `amount_cents`."

    Design: Difficulty/dual_variant_calc/budget_pacing_even_vs_front_loaded_same_spend
    """
    ctx, jp_even, jp_front = _setup_two_postings_same_inputs("C-PACE-1B")
    cid = ctx["contract"]["id"]

    resp_even = record_spend(cid, jp_even["id"], 1000)
    assert validate_success(resp_even)["spent_cents"] == 1000

    resp_front = record_spend(cid, jp_front["id"], 1000)
    assert validate_success(resp_front)["spent_cents"] == 1000


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/pacing_nested_min_max_with_daily_cap_and_budget
# ---------------------------------------------------------------------------

def test_pacing_cumulative_cap_beats_daily_cap():
    """PRD section 3.6: "The acceptance test has four parts, all of which
    must hold: (i) `amount_cents` is at least 1; (ii) `amount_cents` does not
    exceed `daily_cap_cents`; (iii) `spent_cents` plus `amount_cents` does
    not exceed today's cumulative pacing cap (defined below); (iv)
    `spent_cents` plus `amount_cents` does not exceed `budget_cents`. A
    violation of any of these is rejected with `ERR_PACING_VIOLATION`."

    Design: Difficulty/combinatorial_formula/pacing_nested_min_max_with_daily_cap_and_budget
    """
    ctx = setup_active_posting(
        budget_cents=9000, daily_cap_cents=2000, pacing_mode="EVEN",
        slot_date="2026-09-01", slot_reserved_cents=2000,
        contract_number="C-PACE-2",
    )
    cid, jp = ctx["contract"]["id"], ctx["posting"]

    resp1 = record_spend(cid, jp["id"], 900)
    assert validate_success(resp1)["spent_cents"] == 900

    # 200 <= daily_cap 2000, but 900+200=1100 > cumulative cap floor(9000/10)=900
    resp2 = record_spend(cid, jp["id"], 200)
    validate_error(resp2, ApiErrorId.ERR_PACING_VIOLATION)


def test_pacing_daily_cap_beats_amount_within_cumulative_cap():
    """PRD section 3.6: "The acceptance test has four parts, all of which
    must hold: (i) `amount_cents` is at least 1; (ii) `amount_cents` does not
    exceed `daily_cap_cents`; (iii) `spent_cents` plus `amount_cents` does
    not exceed today's cumulative pacing cap (defined below); (iv)
    `spent_cents` plus `amount_cents` does not exceed `budget_cents`. A
    violation of any of these is rejected with `ERR_PACING_VIOLATION`."

    Design: Difficulty/combinatorial_formula/pacing_nested_min_max_with_daily_cap_and_budget
    """
    ctx = setup_active_posting(
        budget_cents=10000, daily_cap_cents=100, pacing_mode="EVEN",
        slot_date="2026-09-01", slot_reserved_cents=100,
        contract_number="C-PACE-2B",
    )
    cid, jp = ctx["contract"]["id"], ctx["posting"]

    # cumulative cap day 1 = floor(10000/10) = 1000, but daily cap is 100
    resp = record_spend(cid, jp["id"], 500)
    validate_error(resp, ApiErrorId.ERR_PACING_VIOLATION)

    resp_ok = record_spend(cid, jp["id"], 100)
    assert validate_success(resp_ok)["spent_cents"] == 100


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/budget_exhausted_at_exact_budget
# ---------------------------------------------------------------------------

def _setup_exhaustion_posting(contract_number):
    ctx = setup_assigned_seat(contract_number=contract_number)
    cid, seat_id = ctx["contract"]["id"], ctx["seat"]["id"]
    posting = create_posting(cid, seat_id, budget_cents=2000, daily_cap_cents=2000,
                             pacing_mode="EVEN")
    add_slot(cid, posting["id"], slot_date="2026-09-10", reserved_cents=2000)
    set_clock("2026-09-10T12:00:00Z")
    activate_posting(cid, posting["id"])
    return ctx, posting


def test_budget_exhausted_at_exact_budget():
    """PRD section 3.6: "On acceptance the posting's `spent_cents` increments
    by `amount_cents`. If the new `spent_cents` is greater than or equal to
    `budget_cents`, the posting transitions from `ACTIVE` to `EXHAUSTED` and
    every `RESERVED` slot moves to `RELEASED`."

    Design: Difficulty/boundary_precision_check/budget_exhausted_at_exact_budget
    """
    ctx, posting = _setup_exhaustion_posting("C-BND-1")
    cid = ctx["contract"]["id"]

    data = validate_success(record_spend(cid, posting["id"], 1999))
    assert data["spent_cents"] == 1999
    assert data["posting_status"] == "ACTIVE"

    data = validate_success(record_spend(cid, posting["id"], 1))
    assert data["spent_cents"] == 2000
    assert data["posting_status"] == "EXHAUSTED"

    resp = record_spend(cid, posting["id"], 1)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_budget_exhaustion_releases_reserved_slots():
    """PRD section 3.6: "On acceptance the posting's `spent_cents` increments
    by `amount_cents`. If the new `spent_cents` is greater than or equal to
    `budget_cents`, the posting transitions from `ACTIVE` to `EXHAUSTED` and
    every `RESERVED` slot moves to `RELEASED`."

    Design: Difficulty/boundary_precision_check/budget_exhausted_at_exact_budget
    """
    ctx, posting = _setup_exhaustion_posting("C-BND-1B")
    cid = ctx["contract"]["id"]

    # Add a second RESERVED slot on an earlier in-range day to watch it release.
    add_slot(cid, posting["id"], slot_date="2026-09-02", reserved_cents=100)

    data = validate_success(record_spend(cid, posting["id"], 2000))
    assert data["posting_status"] == "EXHAUSTED"

    resp = api_client.list_promoted_slots(cid, posting["id"], seat_admin_headers(),
                                          params={"slot_status": "RELEASED"})
    slots, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert all(s["slot_status"] == "RELEASED" for s in slots)


# ---------------------------------------------------------------------------
# Corner/state_machines/posting_activate_without_slot_rejected
# ---------------------------------------------------------------------------

def test_posting_activate_without_slot_rejected():
    """PRD section 3.6: "Activation requires that the parent contract be
    `ACTIVE`, that the posting have at least one `PromotedSlot` in `RESERVED`
    or `CONFIRMED`, and that the current time satisfy `start_at` on or before
    now, strictly before `end_at`."

    Design: Corner/state_machines/posting_activate_without_slot_rejected
    """
    ctx = setup_assigned_seat(contract_number="C-SM-3")
    cid, seat_id = ctx["contract"]["id"], ctx["seat"]["id"]
    posting = create_posting(cid, seat_id, title="NoSlot", budget_cents=5000,
                             daily_cap_cents=1000,
                             end_at="2026-09-05T00:00:00Z")
    resp = api_client.activate_job_posting(cid, posting["id"], seat_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_posting_activate_with_reserved_slot_succeeds():
    """PRD section 3.6: "Activation requires that the parent contract be
    `ACTIVE`, that the posting have at least one `PromotedSlot` in `RESERVED`
    or `CONFIRMED`, and that the current time satisfy `start_at` on or before
    now, strictly before `end_at`."

    Design: Corner/state_machines/posting_activate_without_slot_rejected
    """
    ctx = setup_assigned_seat(contract_number="C-SM-3B")
    cid, seat_id = ctx["contract"]["id"], ctx["seat"]["id"]
    posting = create_posting(cid, seat_id, title="WithSlot", budget_cents=5000,
                             daily_cap_cents=1000,
                             end_at="2026-09-05T00:00:00Z")
    add_slot(cid, posting["id"], slot_date="2026-09-01", reserved_cents=100)
    resp = api_client.activate_job_posting(cid, posting["id"], seat_admin_headers())
    data = validate_success(resp)
    assert data["posting_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner/validations/posting_invalid_date_range_rejected
# ---------------------------------------------------------------------------

def test_posting_invalid_date_range_under_one_day_rejected():
    """PRD section 3.6: "The temporal validation on creation is that
    `start_at` is strictly before `end_at`, and `end_at` minus `start_at` is
    at least one full day; a violation is rejected with
    `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/posting_invalid_date_range_rejected
    """
    ctx = setup_assigned_seat(contract_number="C-VAL-3")
    payload = create_job_posting_payload(
        ctx["seat"]["id"],
        title="BadDates", budget_cents=5000, daily_cap_cents=1000,
        pacing_mode="EVEN",
        start_at="2026-09-05T00:00:00Z", end_at="2026-09-05T12:00:00Z",
    )
    resp = api_client.create_job_posting(ctx["contract"]["id"], payload,
                                         seat_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_posting_exactly_one_day_range_accepted():
    """PRD section 3.6: "The temporal validation on creation is that
    `start_at` is strictly before `end_at`, and `end_at` minus `start_at` is
    at least one full day; a violation is rejected with
    `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/posting_invalid_date_range_rejected
    """
    ctx = setup_assigned_seat(contract_number="C-VAL-3B")
    payload = create_job_posting_payload(
        ctx["seat"]["id"],
        title="GoodDates", budget_cents=5000, daily_cap_cents=1000,
        pacing_mode="EVEN",
        start_at="2026-09-05T00:00:00Z", end_at="2026-09-06T00:00:00Z",
    )
    resp = api_client.create_job_posting(ctx["contract"]["id"], payload,
                                         seat_admin_headers())
    data = validate_success(resp, expected_status=201)
    assert data["posting_status"] == "DRAFT"
    assert data["spent_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/promoted_slot_half_open_posting_window
# ---------------------------------------------------------------------------

def test_promoted_slot_half_open_posting_window():
    """PRD section 3.6: "The slot's `slot_date` must fall within the
    posting's date range — on or after the `start_at` calendar date and
    strictly before the `end_at` calendar date; a slot outside the range is
    rejected with `ERR_INVALID_DATE_RANGE`."

    Design: Difficulty/resource_temporal_overlap/promoted_slot_half_open_posting_window
    """
    ctx = setup_assigned_seat(contract_number="C-OVL-1")
    cid, seat_id = ctx["contract"]["id"], ctx["seat"]["id"]
    posting = create_posting(cid, seat_id, title="SlotJob", budget_cents=5000,
                             daily_cap_cents=1000,
                             start_at="2026-09-01T00:00:00Z",
                             end_at="2026-09-05T00:00:00Z")

    resp = api_client.create_promoted_slot(
        cid, posting["id"], {"slot_date": "2026-09-01", "reserved_cents": 100},
        seat_admin_headers(),
    )
    validate_success(resp, expected_status=201)

    resp = api_client.create_promoted_slot(
        cid, posting["id"], {"slot_date": "2026-09-05", "reserved_cents": 100},
        seat_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_promoted_slot_before_start_date_rejected():
    """PRD section 3.6: "The slot's `slot_date` must fall within the
    posting's date range — on or after the `start_at` calendar date and
    strictly before the `end_at` calendar date; a slot outside the range is
    rejected with `ERR_INVALID_DATE_RANGE`."

    Design: Difficulty/resource_temporal_overlap/promoted_slot_half_open_posting_window
    """
    ctx = setup_assigned_seat(contract_number="C-OVL-1B")
    cid, seat_id = ctx["contract"]["id"], ctx["seat"]["id"]
    posting = create_posting(cid, seat_id, title="SlotJobB", budget_cents=5000,
                             daily_cap_cents=1000,
                             start_at="2026-09-01T00:00:00Z",
                             end_at="2026-09-05T00:00:00Z")

    resp = api_client.create_promoted_slot(
        cid, posting["id"], {"slot_date": "2026-08-31", "reserved_cents": 100},
        seat_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

    resp = api_client.create_promoted_slot(
        cid, posting["id"], {"slot_date": "2026-09-04", "reserved_cents": 100},
        seat_admin_headers(),
    )
    validate_success(resp, expected_status=201)
