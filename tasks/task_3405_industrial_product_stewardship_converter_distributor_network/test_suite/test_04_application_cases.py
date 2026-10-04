"""Application cases, bench capacity, and adhesion evaluation (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    book_lab,
    book_lab_payload,
    create_application_case,
    get_application_case,
    record_result,
    setup_active_formulation,
    TEST_USERS,
    validate_error,
    validate_success,
)

TE = TEST_USERS["technical_engineer_headers"]


def _case(formulation_id, ref, substrate="METAL"):
    return create_application_case(formulation_id, customer_ref=ref, substrate_class=substrate)


def test_adhesion_pass_at_exact_threshold_is_inclusive(api):
    """PRD §3.4: "The recorded peel passes when it is at least the threshold —
    the boundary is inclusive — and the threshold actually used is stored on the
    case as `pass_threshold_applied`."

    Design: Corner/calculations/adhesion_pass_at_exact_threshold_is_inclusive
    """
    ctx = setup_active_formulation()
    case = _case(ctx["formulation"]["id"], "K-X", "METAL")
    book_lab(case["id"], bench_id="B1", bench_date="2026-10-05T00:00:00Z", bench_hours=1.0)
    result = record_result(case["id"], peel_strength_n_per_25mm=15.0, test_temp_c=23,
                           test_standard="NOMINAL")
    assert result["status"] == "CLOSED_PASS"
    assert result["pass_threshold_applied"] == pytest.approx(15.0)


def test_adhesion_nominal_variant_passes_at_peel_15_5(api):
    """PRD §3.4: "Each substrate class has a nominal threshold in N/25mm: 15.0
    for `METAL`, 8.0 for `POLYMER`, 10.0 for `GLASS`, and 12.0 for `COMPOSITE`.
    Under the `NOMINAL` standard the threshold is that bare constant and
    temperature is ignored."

    Design: Difficulty/dual_variant_calc/adhesion_nominal_passes_where_application_derated_fails
    """
    ctx = setup_active_formulation()
    case = _case(ctx["formulation"]["id"], "K-1", "METAL")
    book_lab(case["id"], bench_id="B1", bench_date="2026-10-05T00:00:00Z", bench_hours=2.0)
    result = record_result(case["id"], peel_strength_n_per_25mm=15.5, test_temp_c=43,
                           test_standard="NOMINAL")
    assert result["status"] == "CLOSED_PASS"
    assert result["pass_threshold_applied"] == pytest.approx(15.0)
    assert result["failure_count"] == 0


def test_adhesion_application_derated_variant_fails_at_peel_15_5(api):
    """PRD §3.4: "Under `APPLICATION_DERATED`, the threshold scales up with
    temperature deviation from the 23-degree-Celsius reference: count the full
    10-degree steps in the absolute difference between `test_temp_c` and 23 (a
    difference of 9 degrees counts as zero steps; 10 degrees as one; 27 degrees
    as two), then multiply the nominal threshold by one plus 0.03 per full step
    — one step multiplies by 1.03, two steps by 1.06 — and round the result
    half-up to two decimal places." "Because derating only ever raises the bar,
    the same peel value can pass under `NOMINAL` yet fail under
    `APPLICATION_DERATED`."

    Design: Difficulty/dual_variant_calc/adhesion_nominal_passes_where_application_derated_fails
    """
    ctx = setup_active_formulation()
    case = _case(ctx["formulation"]["id"], "K-2", "METAL")
    book_lab(case["id"], bench_id="B1", bench_date="2026-10-05T00:00:00Z", bench_hours=2.0)
    result = record_result(case["id"], peel_strength_n_per_25mm=15.5, test_temp_c=43,
                           test_standard="APPLICATION_DERATED")
    assert result["status"] == "CLOSED_FAIL"
    assert result["pass_threshold_applied"] == pytest.approx(15.9), (
        "two full 10C steps: 15.0 x 1.06 rounded half-up to 2dp"
    )
    assert result["failure_count"] == 1


def test_bench_bookings_totaling_exactly_eight_hours_admitted(api):
    """PRD §3.4: "A booking that lands the bench at exactly 8.0 hours is
    admitted; anything over is rejected with `ERR_BENCH_CAPACITY_EXCEEDED`
    (409)."

    Design: Difficulty/boundary_precision_check/bench_capacity_admits_exactly_eight_hours
    """
    ctx = setup_active_formulation()
    fid = ctx["formulation"]["id"]
    a = _case(fid, "K-A")
    b = _case(fid, "K-B")
    ra = book_lab(a["id"], bench_id="B9", bench_date="2026-11-02T00:00:00Z", bench_hours=3.5)
    assert ra["status"] == "LAB_BOOKED"
    rb = book_lab(b["id"], bench_id="B9", bench_date="2026-11-02T00:00:00Z", bench_hours=4.5)
    assert rb["status"] == "LAB_BOOKED", "cumulative exactly 8.0 hours is admitted"


def test_bench_booking_beyond_eight_hours_rejected(api):
    """PRD §3.4: "the sum of `bench_hours` over all cases currently `LAB_BOOKED`
    on the same (`bench_id`, `bench_date`) plus the new booking's hours must not
    exceed 8.0 hours for the day. A booking that lands the bench at exactly 8.0
    hours is admitted; anything over is rejected with
    `ERR_BENCH_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/boundary_precision_check/bench_capacity_admits_exactly_eight_hours
    """
    ctx = setup_active_formulation()
    fid = ctx["formulation"]["id"]
    a = _case(fid, "K-A")
    b = _case(fid, "K-B")
    c = _case(fid, "K-C")
    book_lab(a["id"], bench_id="B9", bench_date="2026-11-02T00:00:00Z", bench_hours=3.5)
    book_lab(b["id"], bench_id="B9", bench_date="2026-11-02T00:00:00Z", bench_hours=4.5)
    resp = api.book_lab(c["id"], book_lab_payload("B9", "2026-11-02T00:00:00Z", 0.5), TE)
    validate_error(resp, ApiErrorId.ERR_BENCH_CAPACITY_EXCEEDED)
    assert get_application_case(c["id"])["status"] == "OPEN"


def test_bench_capacity_is_partitioned_by_bench_and_date(api):
    """PRD §3.4: "the sum of `bench_hours` over all cases currently `LAB_BOOKED`
    on the same (`bench_id`, `bench_date`) plus the new booking's hours must not
    exceed 8.0 hours for the day."

    Design: Difficulty/resource_temporal_overlap/bench_day_capacity_is_aggregate_not_interval
    """
    ctx = setup_active_formulation()
    fid = ctx["formulation"]["id"]
    a = _case(fid, "K-A")
    b = _case(fid, "K-B")
    c = _case(fid, "K-C")
    ra = book_lab(a["id"], bench_id="B3", bench_date="2026-12-01T00:00:00Z", bench_hours=4.0)
    assert ra["status"] == "LAB_BOOKED"
    rb = book_lab(b["id"], bench_id="B3", bench_date="2026-12-02T00:00:00Z", bench_hours=4.0)
    assert rb["status"] == "LAB_BOOKED", "a different bench_date never interacts"
    rc = book_lab(c["id"], bench_id="B3", bench_date="2026-12-01T00:00:00Z", bench_hours=4.0)
    assert rc["status"] == "LAB_BOOKED", "aggregate reaches exactly 8.0 on (B3, 2026-12-01)"


def test_bench_aggregate_overflow_rejected(api):
    """PRD §3.4: "A booking that lands the bench at exactly 8.0 hours is
    admitted; anything over is rejected with `ERR_BENCH_CAPACITY_EXCEEDED`
    (409)."

    Design: Difficulty/resource_temporal_overlap/bench_day_capacity_is_aggregate_not_interval
    """
    ctx = setup_active_formulation()
    fid = ctx["formulation"]["id"]
    a = _case(fid, "K-A")
    c = _case(fid, "K-C")
    d = _case(fid, "K-D")
    book_lab(a["id"], bench_id="B3", bench_date="2026-12-01T00:00:00Z", bench_hours=4.0)
    book_lab(c["id"], bench_id="B3", bench_date="2026-12-01T00:00:00Z", bench_hours=4.0)
    resp = api.book_lab(d["id"], book_lab_payload("B3", "2026-12-01T00:00:00Z", 0.5), TE)
    validate_error(resp, ApiErrorId.ERR_BENCH_CAPACITY_EXCEEDED)
    assert get_application_case(d["id"])["status"] == "OPEN"


def test_terminal_case_book_lab_reports_state_error_not_capacity(api):
    """PRD §2.9: "Every write request passes through a single ordered gauntlet
    of checks; when several checks would fail, the one with the lowest priority
    number wins and determines the error returned." — "**State legality**" (8)
    precedes "laboratory bench capacity (27, `ERR_BENCH_CAPACITY_EXCEEDED`)".
    PRD §3.4: "A passing result closes the case as `CLOSED_PASS`, which is
    terminal."

    Design: Difficulty/priority_pair_validation_conflict/terminal_case_retest_beats_bench_capacity
    """
    ctx = setup_active_formulation()
    fid = ctx["formulation"]["id"]
    case_a = _case(fid, "K-A")
    case_b = _case(fid, "K-B", substrate="GLASS")
    book_lab(case_b["id"], bench_id="B6", bench_date="2026-11-02T00:00:00Z", bench_hours=1.0)
    record_result(case_b["id"], peel_strength_n_per_25mm=11.0, test_temp_c=23,
                  test_standard="NOMINAL")
    assert get_application_case(case_b["id"])["status"] == "CLOSED_PASS"
    book_lab(case_a["id"], bench_id="B5", bench_date="2026-11-02T00:00:00Z", bench_hours=8.0)
    resp = api.book_lab(case_b["id"], book_lab_payload("B5", "2026-11-02T00:00:00Z", 1.0), TE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_application_case(case_b["id"])["status"] == "CLOSED_PASS"
    assert get_application_case(case_a["id"])["status"] == "LAB_BOOKED"


def test_open_case_on_full_bench_reports_capacity_error(api):
    """PRD §2.9: "when several checks would fail, the one with the lowest
    priority number wins and determines the error returned" — with a legal
    source state the state check passes and the capacity rule (27,
    `ERR_BENCH_CAPACITY_EXCEEDED`) fires on its own.

    Design: Difficulty/priority_pair_validation_conflict/terminal_case_retest_beats_bench_capacity
    """
    ctx = setup_active_formulation()
    fid = ctx["formulation"]["id"]
    case_a = _case(fid, "K-A")
    case_c = _case(fid, "K-C")
    book_lab(case_a["id"], bench_id="B5", bench_date="2026-11-02T00:00:00Z", bench_hours=8.0)
    resp = api.book_lab(case_c["id"], book_lab_payload("B5", "2026-11-02T00:00:00Z", 1.0), TE)
    validate_error(resp, ApiErrorId.ERR_BENCH_CAPACITY_EXCEEDED)
    assert get_application_case(case_c["id"])["status"] == "OPEN"


def test_book_then_result_pair_conserves_bench_hours(api):
    """PRD §3.4: "Either way the booking is released: the case leaves
    `LAB_BOOKED`, so its hours stop counting against the bench's daily total —
    a booking followed by its own result recording leaves the day's occupancy
    exactly as it was before the pair."

    Design: Difficulty/compensating_invariant/bench_book_result_pair_conserves_daily_hours
    """
    ctx = setup_active_formulation()
    fid = ctx["formulation"]["id"]
    a = _case(fid, "K-A")
    b = _case(fid, "K-B")
    c = _case(fid, "K-C")
    book_lab(a["id"], bench_id="B7", bench_date="2026-12-03T00:00:00Z", bench_hours=5.0)
    book_lab(b["id"], bench_id="B7", bench_date="2026-12-03T00:00:00Z", bench_hours=3.0)
    blocked = api.book_lab(c["id"], book_lab_payload("B7", "2026-12-03T00:00:00Z", 1.0), TE)
    validate_error(blocked, ApiErrorId.ERR_BENCH_CAPACITY_EXCEEDED)
    result = record_result(a["id"], peel_strength_n_per_25mm=16.0, test_temp_c=23,
                           test_standard="NOMINAL")
    assert result["status"] == "CLOSED_PASS"
    retry = book_lab(c["id"], bench_id="B7", bench_date="2026-12-03T00:00:00Z", bench_hours=1.0)
    assert retry["status"] == "LAB_BOOKED", "the released 5.0 hours make room again"


def test_bench_hours_released_permit_refill_to_exactly_eight(api):
    """PRD §3.4: "the sum of `bench_hours` over all cases currently `LAB_BOOKED`
    on the same (`bench_id`, `bench_date`) plus the new booking's hours must not
    exceed 8.0 hours for the day." and "a booking followed by its own result
    recording leaves the day's occupancy exactly as it was before the pair."

    Design: Difficulty/compensating_invariant/bench_book_result_pair_conserves_daily_hours
    """
    ctx = setup_active_formulation()
    fid = ctx["formulation"]["id"]
    a = _case(fid, "K-A")
    b = _case(fid, "K-B")
    c = _case(fid, "K-C")
    d = _case(fid, "K-D")
    e = _case(fid, "K-E")
    book_lab(a["id"], bench_id="B7", bench_date="2026-12-03T00:00:00Z", bench_hours=5.0)
    book_lab(b["id"], bench_id="B7", bench_date="2026-12-03T00:00:00Z", bench_hours=3.0)
    record_result(a["id"], peel_strength_n_per_25mm=16.0, test_temp_c=23,
                  test_standard="NOMINAL")
    book_lab(c["id"], bench_id="B7", bench_date="2026-12-03T00:00:00Z", bench_hours=1.0)
    rd = book_lab(d["id"], bench_id="B7", bench_date="2026-12-03T00:00:00Z", bench_hours=4.0)
    assert rd["status"] == "LAB_BOOKED", "3.0 + 1.0 + 4.0 == 8.0 exactly"
    resp = api.book_lab(e["id"], book_lab_payload("B7", "2026-12-03T00:00:00Z", 0.5), TE)
    validate_error(resp, ApiErrorId.ERR_BENCH_CAPACITY_EXCEEDED)
