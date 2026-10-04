"""Growth programs: LTO attainment with per-run floor, sampling redemption,
the 14-day partner gap, conditional payloads, window gating, and pagination
(PRD sections 2.3, 3.6)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success, validate_paginated,
    create_lto_program_payload, create_sampling_program_payload,
    program_lifecycle_payload,
    create_bare_product, transition_product,
    create_lto_program, create_sampling_program,
    activate_program, open_program_window, evaluate_program,
    program_transition, setup_lto_program,
    setup_lto_program_with_deliveries, set_clock,
    fetch_program,
)

_CH = TEST_USERS["channel_manager_headers"]


def test_delivered_cases_floor_per_run_before_summing(api):
    """PRD section 3.6: "`delivered_cases` — the summed `quantity_cases` of
    every batch produced by runs dedicated to the program ... with each run's
    cases floored to whole cases before any summing". Two 105 kg runs deliver
    floor(105/10) = 10 cases twice = 20 (not floor(210/10) = 21), and
    attainment is round_half_up(20 x 100 / 24, 2) = 83.33.

    Design: Difficulty/combinatorial_formula/cf_delivered_cases_per_run_floor
    """
    ctx = setup_lto_program_with_deliveries(
        24, [105, 105], partner_code="CHAIN-CF", program_code="PROG-CF-2")
    evaluate_program(ctx["program"]["id"])
    program = fetch_program(ctx["program"]["id"])
    assert program["delivered_cases"] == 20
    assert program["attainment_pct"] == pytest.approx(83.33, abs=1e-9)
    assert program["status"] == "EVALUATING"


def test_attainment_83_33_blocks_conversion(api):
    """PRD section 3.6: "Conversion (`EVALUATING` → `CONVERTED`) demands that
    the scorecard clear its bar: at least 85.00 percent attainment for an LTO
    ... with shortfalls rejected as `ERR_PROGRAM_TARGET_NOT_MET`." The
    per-run-floor 20 of 24 (83.33) is a shortfall, and the program stays
    EVALUATING.

    Design: Difficulty/combinatorial_formula/cf_delivered_cases_per_run_floor
    """
    ctx = setup_lto_program_with_deliveries(
        24, [105, 105], partner_code="CHAIN-CF", program_code="PROG-CF-2")
    evaluate_program(ctx["program"]["id"])
    resp = api.program_lifecycle(
        ctx["program"]["id"], program_lifecycle_payload("CONVERTED"), _CH)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_TARGET_NOT_MET)
    assert fetch_program(ctx["program"]["id"])["status"] == "EVALUATING"


def test_attainment_exactly_85_scorecard(api):
    """PRD section 3.6: attainment is "`delivered_cases` ... expressed as a
    percentage of `committed_cases`, rounded half-up to two decimal places".
    Runs of 100 kg (10 cases) and 75 kg (floor(75/10) = 7 cases) deliver 17
    of 20 committed — exactly 85.00.

    Design: Difficulty/boundary_precision_check/bpc_attainment_85_exact_converts
    """
    ctx = setup_lto_program_with_deliveries(
        20, [100, 75], partner_code="CHAIN-BP", program_code="PROG-BP-1")
    evaluate_program(ctx["program"]["id"])
    program = fetch_program(ctx["program"]["id"])
    assert program["delivered_cases"] == 17
    assert program["attainment_pct"] == pytest.approx(85.00, abs=1e-9)


def test_attainment_exactly_85_converts(api):
    """PRD section 3.6: "at least 85.00 percent attainment for an LTO" — the
    boundary is inclusive, so a program delivering exactly 85.00 percent
    converts successfully.

    Design: Difficulty/boundary_precision_check/bpc_attainment_85_exact_converts
    """
    ctx = setup_lto_program_with_deliveries(
        20, [100, 75], partner_code="CHAIN-BP", program_code="PROG-BP-1")
    evaluate_program(ctx["program"]["id"])
    program = program_transition(ctx["program"]["id"], "CONVERTED")
    assert program["status"] == "CONVERTED"


def test_attainment_80_blocks_conversion(api):
    """PRD section 3.6: "at least 85.00 percent attainment for an LTO ...
    with shortfalls rejected as `ERR_PROGRAM_TARGET_NOT_MET`" — 16 of 20
    computes 80.00 and the conversion is refused.

    Design: Corner/calculations/cn_calc_attainment_below_boundary_converted_fails
    """
    ctx = setup_lto_program_with_deliveries(
        20, [100, 65], partner_code="CHAIN-K14", program_code="PROG-K-14")
    evaluate_program(ctx["program"]["id"])
    program = fetch_program(ctx["program"]["id"])
    assert program["delivered_cases"] == 16
    assert program["attainment_pct"] == pytest.approx(80.00, abs=1e-9)
    resp = api.program_lifecycle(
        ctx["program"]["id"], program_lifecycle_payload("CONVERTED"), _CH)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_TARGET_NOT_MET)
    assert fetch_program(ctx["program"]["id"])["status"] == "EVALUATING"


def test_redemption_exactly_12_converts(api):
    """PRD section 3.6: "the `redemption_rate_pct` is recomputed as redeemed
    coupons expressed as a percentage of `coupons_issued`, rounded half-up to
    two decimal places" and "at least 12.00 percent redemption for a sampling
    program". 120 redeemed of 1000 issued is exactly 12.00 and converts.

    Design: Corner/calculations/cn_calc_redemption_boundary_12_exact_converts
    """
    set_clock()
    product = create_bare_product(product_code="PROD-K-15")
    program = create_sampling_program(product["id"], program_code="PROG-K-15",
                                      budget_cents=50000, coupons_issued=1000)
    transition_product(product["id"], "PILOT")
    activate_program(program["id"])
    open_program_window(program["id"])
    program = evaluate_program(program["id"], final_coupons_redeemed=120)
    assert program["coupons_redeemed"] == 120
    assert program["redemption_rate_pct"] == pytest.approx(12.00, abs=1e-9)
    program = program_transition(program["id"], "CONVERTED")
    assert program["status"] == "CONVERTED"


def _partner_gap_setup():
    """Product in PILOT plus program P1 (CHAIN-G, 2026-09-01..2026-09-15)
    already ACTIVE; returns (product, p1)."""
    set_clock()
    product = create_bare_product(product_code="PROD-OV-2")
    transition_product(product["id"], "PILOT")
    p1 = create_lto_program(product["id"], program_code="PROG-GAP-1",
                            partner_code="CHAIN-G", committed_cases=10,
                            window_start="2026-09-01T00:00:00Z",
                            window_end="2026-09-15T00:00:00Z")
    activate_program(p1["id"])
    return product, p1


def test_partner_gap_of_exactly_14_days_accepted(api):
    """PRD section 3.6: "activation survives only when the existing program's
    window end plus 14 days falls on or before the new window's start, or
    when the new window's end plus 14 days falls on or before the existing
    window's start". P1 ends 2026-09-15; P2 starting 2026-09-29 sits exactly
    14 days later and activates.

    Design: Difficulty/resource_temporal_overlap/rto_partner_program_windows_min_gap
    """
    product, _p1 = _partner_gap_setup()
    p2 = create_lto_program(product["id"], program_code="PROG-GAP-2",
                            partner_code="CHAIN-G", committed_cases=10,
                            window_start="2026-09-29T00:00:00Z",
                            window_end="2026-10-15T00:00:00Z")
    p2 = activate_program(p2["id"])
    assert p2["status"] == "ACTIVE"


def test_partner_gap_of_13_days_rejected(api):
    """PRD section 3.6: "no other `FOODSERVICE_LTO` program with the same
    `partner_code` in `ACTIVE`, `IN_WINDOW`, or `EVALUATING` may sit closer
    than 14 days away ... any tighter spacing, including outright overlap, is
    rejected with `ERR_PROGRAM_WINDOW_OVERLAP`." P3 starting 2026-09-28 is 13
    days after P1's end and stays PROPOSED.

    Design: Difficulty/resource_temporal_overlap/rto_partner_program_windows_min_gap
    """
    product, _p1 = _partner_gap_setup()
    p3 = create_lto_program(product["id"], program_code="PROG-GAP-3",
                            partner_code="CHAIN-G", committed_cases=10,
                            window_start="2026-09-28T00:00:00Z",
                            window_end="2026-10-10T00:00:00Z")
    resp = api.program_lifecycle(
        p3["id"], program_lifecycle_payload("ACTIVE"), _CH)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_WINDOW_OVERLAP)
    assert fetch_program(p3["id"])["status"] == "PROPOSED"


def test_lto_program_missing_committed_cases_rejected(api):
    """PRD section 3.6: "A foodservice limited-time offer requires the
    `partner_code` and a `committed_cases` volume commitment greater than
    zero ... Violating either pairing is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/cn_ent_program_lto_missing_required_returns_invalid_request
    """
    product = create_bare_product(product_code="PROD-K-9")
    payload = create_lto_program_payload(
        product["id"], program_code="PROG-BAD-1", partner_code="CHAIN-Z",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z")
    del payload["committed_cases"]
    resp = api.create_program(payload, _CH)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    _rows, meta = validate_paginated(api.list_programs(_CH))
    assert meta["total_count"] == 0


def test_sampling_program_with_partner_code_rejected(api):
    """PRD section 3.6: "A sampling and demonstration program requires
    `budget_cents` and accepts `coupons_issued` (zero or more, defaulting to
    0), while `partner_code` and `committed_cases` must be null. Violating
    either pairing is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/cn_ent_program_sampling_with_partner_code_returns_invalid_request
    """
    product = create_bare_product(product_code="PROD-K-9B")
    payload = create_sampling_program_payload(
        product["id"], program_code="PROG-BAD-2", budget_cents=50000,
        coupons_issued=1000, window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z")
    payload["partner_code"] = "CHAIN-Z"
    resp = api.create_program(payload, _CH)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_program_list_pagination_envelope(api):
    """PRD section 2.3: "Paginated list responses carry the fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    response envelope." With three programs, limit=2 pages 2 + 1 rows and
    total_count spans the full filtered set.

    Design: Corner/entities/cn_ent_list_pagination_envelope
    """
    product = create_bare_product(product_code="PROD-K-PG")
    for code in ("PG-1", "PG-2", "PG-3"):
        create_sampling_program(product["id"], program_code=code,
                                budget_cents=10000, coupons_issued=100)
    data1, meta1 = validate_paginated(api.list_programs(
        _CH, params={"limit": 2, "offset": 0}))
    assert len(data1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    data2, meta2 = validate_paginated(api.list_programs(
        _CH, params={"limit": 2, "offset": 2}))
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_opening_window_outside_test_window_rejected(api):
    """PRD section 3.6: "Opening the test window (`ACTIVE` → `IN_WINDOW`) is
    clock-gated: the current logical clock must fall inside the window, both
    bounds inclusive, otherwise `ERR_OUTSIDE_TEST_WINDOW`." At the default
    clock 2026-09-01 a window starting 2026-10-01 cannot open.

    Design: Corner/validations/cn_val_outside_test_window
    """
    product = create_bare_product(product_code="PROD-K-28")
    transition_product(product["id"], "PILOT")
    program = create_lto_program(product["id"], program_code="PROG-K-28",
                                 partner_code="CHAIN-K28", committed_cases=10,
                                 window_start="2026-10-01T00:00:00Z",
                                 window_end="2026-10-31T23:59:59Z")
    activate_program(program["id"])
    resp = api.program_lifecycle(
        program["id"], program_lifecycle_payload("IN_WINDOW"), _CH)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_TEST_WINDOW)
    assert fetch_program(program["id"])["status"] == "ACTIVE"


def test_redemption_cannot_exceed_issued(api):
    """PRD section 3.6: "A sampling program must report
    `final_coupons_redeemed` (`ERR_INVALID_REQUEST` when it is missing),
    which may not exceed `coupons_issued` (`ERR_REDEMPTION_EXCEEDS_ISSUED`)"
    — 1001 redeemed against 1000 issued fails with no partial write.

    Design: Corner/validations/cn_val_redemption_exceeds_issued
    """
    product = create_bare_product(product_code="PROD-K-29")
    transition_product(product["id"], "PILOT")
    program = create_sampling_program(product["id"], program_code="PROG-K-29",
                                      budget_cents=50000, coupons_issued=1000)
    activate_program(program["id"])
    open_program_window(program["id"])
    resp = api.program_lifecycle(
        program["id"],
        program_lifecycle_payload("EVALUATING", final_coupons_redeemed=1001),
        _CH)
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_EXCEEDS_ISSUED)
    program = fetch_program(program["id"])
    assert program["status"] == "IN_WINDOW"
    assert program["coupons_redeemed"] == 0
