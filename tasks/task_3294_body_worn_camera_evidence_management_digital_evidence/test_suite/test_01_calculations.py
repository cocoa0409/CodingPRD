"""Calculation tests: redaction effort variants, budget projection variants,
multi-year growth, retention constants, supervisor sampling, case rollup."""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    make_officer_headers,
    make_records_officer_headers,
    make_supervisor_headers,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.fixtures import (
    close_case,
    create_case,
    link_evidence,
    refresh_recording,
    set_clock,
    setup_agency_with_policy,
    setup_agency_with_policy_and_officer,
    setup_officer_with_device,
    upload_recording,
)
from test_helpers.factories import create_recording_payload

ADMIN = TEST_USERS["agency_admin_headers"]
RO = TEST_USERS["records_officer_headers"]


# ===========================================================================
# dual_variant_calc / redaction_single_pass_vs_multi_pass_effort_diverges
# ===========================================================================

def test_redaction_single_pass_effort_against_long_recording(api):
    """PRD §3.6: "Under `SINGLE_PASS`, the base effort is 2 minutes of labor per
    media-minute; when both scopes are engaged the base is multiplied by one and a
    half; the estimate is that product rounded up to a whole minute, with no
    further surcharge."

    Design: Difficulty/dual_variant_calc/redaction_single_pass_vs_multi_pass_effort_diverges
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer,
                           duration_seconds=7260, size_bytes=2147483648,
                           category="INCIDENT")
    resp = api.create_redaction_job(
        agency["id"], rec["id"],
        {"request_reference": "PRR-1", "scope_face": True, "scope_audio": True,
         "passes": "SINGLE_PASS"},
        RO,
    )
    job = validate_success(resp, expected_status=201)
    # ceil(121 * 2 * 1.5) == 363
    assert job["estimated_minutes"] == 363, (
        f"SINGLE_PASS face+audio on 121 media-minutes must estimate 363, "
        f"got {job['estimated_minutes']}"
    )


def test_redaction_multi_pass_effort_diverges_with_long_form_surcharge(api):
    """PRD §3.6: "Under `MULTI_PASS`, the base effort is 5 minutes per
    media-minute; the two-scope multiplier is doubled (two rather than one and a
    half); the product is rounded up to a whole minute; and a long-form surcharge
    of 30 additional minutes applies whenever the recording runs longer than 120
    media-minutes."

    Design: Difficulty/dual_variant_calc/redaction_single_pass_vs_multi_pass_effort_diverges
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer,
                           duration_seconds=7260, size_bytes=2147483648,
                           category="INCIDENT")
    single = validate_success(api.create_redaction_job(
        agency["id"], rec["id"],
        {"request_reference": "PRR-1", "scope_face": True, "scope_audio": True,
         "passes": "SINGLE_PASS"}, RO), expected_status=201)
    multi = validate_success(api.create_redaction_job(
        agency["id"], rec["id"],
        {"request_reference": "PRR-2", "scope_face": True, "scope_audio": True,
         "passes": "MULTI_PASS"}, RO), expected_status=201)
    # ceil(121 * 5 * 2.0) + 30 == 1240
    assert multi["estimated_minutes"] == 1240, (
        f"MULTI_PASS face+audio on 121 media-minutes must estimate 1240, "
        f"got {multi['estimated_minutes']}"
    )
    assert single["estimated_minutes"] != multi["estimated_minutes"]


# ===========================================================================
# dual_variant_calc / budget_projection_full_month_vs_prorated_accrual_diverges
# ===========================================================================

def _setup_three_gib_agency(api, monthly_budget_cents=10000):
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    from test_helpers.fixtures import create_budget_plan
    create_budget_plan(agency["id"], monthly_budget_cents=monthly_budget_cents,
                       cost_per_gb_month_cents=1000, alert_threshold_pct=80,
                       effective_from_month="2026-01")
    officer, device = setup_officer_with_device(agency["id"])
    # Pin the clock past the latest recorded_at used below so no upload is
    # future-dated relative to the logical clock (PRD section 3.4).
    set_clock("2026-09-01T00:02:00Z")
    one_gib = 1073741824
    for i in range(3):
        upload_recording(agency["id"], device, officer,
                         recorded_at=f"2026-09-01T00:0{i}:00Z",
                         size_bytes=one_gib, category="INCIDENT")
    return agency, officer, device


def test_budget_projection_reports_full_month_cost(api):
    """PRD §3.7: "The agency's projected monthly storage cost is the full-month
    figure: `storage_used_bytes` converted to gigabytes (dividing by 1073741824,
    keeping the exact fractional value), multiplied by the plan's
    `cost_per_gb_month_cents`, and rounded up to whole cents."

    Design: Difficulty/dual_variant_calc/budget_projection_full_month_vs_prorated_accrual_diverges
    """
    agency, officer, device = _setup_three_gib_agency(api)
    set_clock("2026-09-16T00:00:00Z")
    resp = api.get_budget_projection(agency["id"], RO)
    data = validate_success(resp)
    assert data["projection_month_cost_cents"] == 3000, (
        f"3 GiB at 1000 cents/GiB-month must project 3000 full-month cents, "
        f"got {data['projection_month_cost_cents']}"
    )
    assert data["posture"] == "OK"


def test_budget_accrual_is_prorated_by_elapsed_days(api):
    """PRD §3.7: "The accrued current-month figure, `current_month_accrued_cost_cents`,
    is the full-month cost pro-rated by elapsed days: the full-month cost is
    multiplied by the current day-of-month (1-based, per the logical clock),
    divided by the number of calendar days in the month, and rounded down."

    Design: Difficulty/dual_variant_calc/budget_projection_full_month_vs_prorated_accrual_diverges
    """
    agency, officer, device = _setup_three_gib_agency(api)
    set_clock("2026-09-16T00:00:00Z")
    resp = api.get_budget_projection(agency["id"], RO)
    data = validate_success(resp)
    # floor(3000 * 16 / 30) == 1600
    assert data["current_month_accrued_cost_cents"] == 1600, (
        f"day 16 of a 30-day month must accrue floor(3000*16/30)==1600, "
        f"got {data['current_month_accrued_cost_cents']}"
    )
    assert data["current_month_accrued_cost_cents"] != data["projection_month_cost_cents"]


# ===========================================================================
# combinatorial_formula / multi_year_projection_growth_crossing_boundary
# ===========================================================================

def test_multi_year_projection_compounds_on_byte_count(api):
    """PRD §3.7: "For each month index m from 0 up to the horizon minus one, the
    projected byte volume is the agency's current `storage_used_bytes` scaled by
    the growth factor raised to the m-th power; that volume is converted to
    gigabytes, multiplied by `cost_per_gb_month_cents`, and rounded up to whole
    cents — per month, before any summation."

    Design: Difficulty/combinatorial_formula/multi_year_projection_growth_crossing_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    from test_helpers.fixtures import create_budget_plan
    create_budget_plan(agency["id"], monthly_budget_cents=1500,
                       cost_per_gb_month_cents=1000, alert_threshold_pct=80,
                       effective_from_month="2026-01")
    officer, device = setup_officer_with_device(agency["id"])
    upload_recording(agency["id"], device, officer, size_bytes=1073741824,
                     category="INCIDENT")
    resp = api.get_budget_projection(
        agency["id"], ADMIN, params={"months": 5, "plan_growth_bps": 1000})
    data = validate_success(resp)
    # growth compounds on bytes: ceil(1 GiB * 1.1^m * 1000) for m = 0..4
    expected = [1000, 1100, 1211, 1332, 1465]
    actual = [m["projected_cost_cents"] for m in data["months"]]
    assert len(data["months"]) == 5
    assert actual == expected, (
        f"per-month ceiled projections must be {expected}, got {actual}"
    )
    for m in data["months"]:
        assert m["over_budget"] is False, (
            f"month {m['month_index']} at {m['projected_cost_cents']} is strictly "
            f"below the 1500 budget and must not be flagged over_budget"
        )


def test_multi_year_projection_first_over_budget_index_and_total(api):
    """PRD §3.7: "The response aggregates `total_projected_cost_cents` as the sum
    of those per-month ceiled figures — round per month, then sum, never the
    reverse — and `first_over_budget_month_index` as the smallest m whose
    projection exceeds the budget, or null when no month breaches it."

    Design: Difficulty/combinatorial_formula/multi_year_projection_growth_crossing_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    from test_helpers.fixtures import create_budget_plan
    create_budget_plan(agency["id"], monthly_budget_cents=1500,
                       cost_per_gb_month_cents=1000, alert_threshold_pct=80,
                       effective_from_month="2026-01")
    officer, device = setup_officer_with_device(agency["id"])
    upload_recording(agency["id"], device, officer, size_bytes=1073741824,
                     category="INCIDENT")
    resp = api.get_budget_projection(
        agency["id"], ADMIN, params={"months": 5, "plan_growth_bps": 1000})
    data = validate_success(resp)
    assert data["first_over_budget_month_index"] is None, (
        "every month is strictly below the 1500-cent budget, so "
        "first_over_budget_month_index must be null"
    )
    assert data["total_projected_cost_cents"] == 6108, (
        f"sum of per-month ceiled figures 1000+1100+1211+1332+1465 == 6108, "
        f"got {data['total_projected_cost_cents']}"
    )


# ===========================================================================
# combinatorial_formula / per_month_ceil_then_sum_beats_sum_then_ceil
# ===========================================================================

def test_per_month_ceil_literals_over_four_months(api):
    """PRD §2.10: "projected storage cost rounds up to whole cents per month
    before any summation (round-per-month-then-sum — never sum-then-round)".

    Design: Difficulty/combinatorial_formula/per_month_ceil_then_sum_beats_sum_then_ceil
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    from test_helpers.fixtures import create_budget_plan
    create_budget_plan(agency["id"], monthly_budget_cents=100000,
                       cost_per_gb_month_cents=1000, alert_threshold_pct=80,
                       effective_from_month="2026-01")
    officer, device = setup_officer_with_device(agency["id"])
    upload_recording(agency["id"], device, officer, size_bytes=1073741824,
                     category="INCIDENT")
    resp = api.get_budget_projection(
        agency["id"], ADMIN, params={"months": 4, "plan_growth_bps": 1000})
    data = validate_success(resp)
    actual = [m["projected_cost_cents"] for m in data["months"]]
    # Growth compounds on the byte count (1 GiB * 1.1^m) before GiB conversion
    # and per-month ceil: the fractional parts at these inputs are non-integral
    # (1.331 GiB ceils to 1332), which pins compounding on bytes, not on
    # already-rounded cent figures.
    assert actual == [1000, 1100, 1211, 1332], (
        f"per-month projections must be [1000, 1100, 1211, 1332], got {actual}"
    )


def test_per_month_ceil_total_is_sum_of_ceiled_months(api):
    """PRD §3.7: "The response aggregates `total_projected_cost_cents` as the sum
    of those per-month ceiled figures — round per month, then sum, never the
    reverse".

    Design: Difficulty/combinatorial_formula/per_month_ceil_then_sum_beats_sum_then_ceil
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    from test_helpers.fixtures import create_budget_plan
    create_budget_plan(agency["id"], monthly_budget_cents=100000,
                       cost_per_gb_month_cents=1000, alert_threshold_pct=80,
                       effective_from_month="2026-01")
    officer, device = setup_officer_with_device(agency["id"])
    upload_recording(agency["id"], device, officer, size_bytes=1073741824,
                     category="INCIDENT")
    resp = api.get_budget_projection(
        agency["id"], ADMIN, params={"months": 4, "plan_growth_bps": 1000})
    data = validate_success(resp)
    assert data["total_projected_cost_cents"] == 1000 + 1100 + 1211 + 1332, (
        f"total must equal the sum of per-month ceiled figures (4643), "
        f"got {data['total_projected_cost_cents']}"
    )
    assert data["total_projected_cost_cents"] == sum(
        m["projected_cost_cents"] for m in data["months"])


# ===========================================================================
# calculations / retention_due_per_category_constants_applied
# ===========================================================================

def test_retention_due_incident_180_days(api):
    """PRD §3.5: "The base retention period is category-driven: `TEST` footage is
    retained for 7 days, `TRAINING` for 30 days, `TRAFFIC_STOP` for 90 days,
    `INCIDENT` for 180 days, and `ARREST` for 1095 days. The recording's
    `retention_due_at` is its upload completion time plus that many days."

    Design: Corner/calculations/retention_due_per_category_constants_applied
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, category="INCIDENT")
    rec = refresh_recording(agency["id"], rec["id"])
    assert rec["retention_due_at"] == "2027-02-28T00:00:00Z", (
        f"2026-09-01 + 180 days must be 2027-02-28T00:00:00Z, "
        f"got {rec['retention_due_at']}"
    )


def test_retention_due_training_30_days(api):
    """PRD §3.5: "The base retention period is category-driven: `TEST` footage is
    retained for 7 days, `TRAINING` for 30 days, `TRAFFIC_STOP` for 90 days,
    `INCIDENT` for 180 days, and `ARREST` for 1095 days. The recording's
    `retention_due_at` is its upload completion time plus that many days."

    Design: Corner/calculations/retention_due_per_category_constants_applied
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, category="TRAINING")
    rec = refresh_recording(agency["id"], rec["id"])
    assert rec["retention_due_at"] == "2026-10-01T00:00:00Z", (
        f"2026-09-01 + 30 days must be 2026-10-01T00:00:00Z, "
        f"got {rec['retention_due_at']}"
    )


# ===========================================================================
# calculations / supervisor_sampling_modulo_flags_every_fourth_at_rate_25
# ===========================================================================

def test_supervisor_sampling_first_upload_not_flagged_at_rate_25(api):
    """PRD §3.4: "Otherwise the sampling modulus is the whole-number floor of 100
    divided by the rate — a rate of 25 yields a modulus of 4; a rate of 30 yields
    a modulus of 3. The officer's `recordings_uploaded_count`, taken after the
    increment for this very upload, is divided by that modulus; when the
    remainder is zero, the recording's `review_status` becomes `PENDING_REVIEW`
    (and the officer's `pending_review_count` rises by one)."

    Design: Corner/calculations/supervisor_sampling_modulo_flags_every_fourth_at_rate_25
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer(
        policy_overrides={"supervisor_review_rate_pct": 25})
    r1 = upload_recording(agency["id"], device, officer,
                          recorded_at="2026-09-01T00:00:00Z", category="INCIDENT")
    r1 = refresh_recording(agency["id"], r1["id"])
    assert r1["review_status"] == "NOT_FLAGGED", (
        f"upload ordinal 1 mod 4 != 0 must stay NOT_FLAGGED, got {r1['review_status']}"
    )


def test_supervisor_sampling_fourth_upload_flagged_at_rate_25(api):
    """PRD §3.4: "The officer's `recordings_uploaded_count`, taken after the
    increment for this very upload, is divided by that modulus; when the
    remainder is zero, the recording's `review_status` becomes `PENDING_REVIEW`
    (and the officer's `pending_review_count` rises by one)."

    Design: Corner/calculations/supervisor_sampling_modulo_flags_every_fourth_at_rate_25
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer(
        policy_overrides={"supervisor_review_rate_pct": 25})
    # Pin the clock past the latest recorded_at used below so no upload is
    # future-dated relative to the logical clock (PRD section 3.4).
    set_clock("2026-09-01T00:03:00Z")
    recs = []
    for i in range(4):
        recs.append(upload_recording(
            agency["id"], device, officer,
            recorded_at=f"2026-09-01T00:0{i}:00Z", category="INCIDENT"))
    r4 = refresh_recording(agency["id"], recs[3]["id"])
    assert r4["review_status"] == "PENDING_REVIEW", (
        f"upload ordinal 4 mod 4 == 0 must be PENDING_REVIEW, got {r4['review_status']}"
    )
    from test_helpers.fixtures import refresh_officer
    officer_now = refresh_officer(agency["id"], officer["id"])
    assert officer_now["pending_review_count"] == 1, (
        f"exactly one of the four uploads is sampled, got "
        f"{officer_now['pending_review_count']}"
    )


# ===========================================================================
# calculations / case_retention_rollup_takes_max_of_linked_recordings
# ===========================================================================

def test_case_retention_rollup_is_max_of_linked_recordings(api):
    """PRD §2.6: "its `retention_due_at` is the maximum `retention_due_at` over
    those same recordings, or null when none are linked."

    Design: Corner/calculations/case_retention_rollup_takes_max_of_linked_recordings
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rt = upload_recording(agency["id"], device, officer,
                          recorded_at="2026-09-01T00:00:00Z", category="TRAFFIC_STOP")
    # Advance the clock so the second upload is not future-dated and its
    # upload completion time (logical now) matches the asserted due instant.
    set_clock("2026-09-01T00:01:00Z")
    ra = upload_recording(agency["id"], device, officer,
                          recorded_at="2026-09-01T00:01:00Z", category="ARREST")
    case = create_case(agency["id"], officer)
    link_evidence(agency["id"], case["id"], rt["id"], officer)
    link_evidence(agency["id"], case["id"], ra["id"], officer)
    from test_helpers.fixtures import get_case
    case_now = get_case(agency["id"], case["id"], headers=make_supervisor_headers(officer["id"]))
    # Per PRD section 3.5 the case-linked extension applies at link creation:
    # ARREST due = max(upload 00:01 + 1095d, link 00:01 + 2555d)
    #            = 2026-09-01T00:01:00Z + 2555d = 2033-08-30T00:01:00Z;
    # TRAFFIC_STOP due = max(00:00 + 90d, link 00:01 + 365d)
    #                  = 2027-09-01T00:01:00Z. The rollup takes the max.
    assert case_now["retention_due_at"] == "2033-08-30T00:01:00Z", (
        f"case rollup must take the ARREST recording's due date, "
        f"got {case_now['retention_due_at']}"
    )


def test_case_retention_rollup_rederives_after_unlink(api):
    """PRD §2.6: "its `retention_due_at` is the maximum `retention_due_at` over
    those same recordings, or null when none are linked."
    PRD §3.8: "A successful unlink moves the link to `UNLINKED` with
    `unlinked_at` stamped at the logical now, decrements `evidence_count` by one,
    recomputes `total_evidence_bytes` and the case `retention_due_at` rollup".

    Design: Corner/calculations/case_retention_rollup_takes_max_of_linked_recordings
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rt = upload_recording(agency["id"], device, officer,
                          recorded_at="2026-09-01T00:00:00Z", category="TRAFFIC_STOP")
    # Advance the clock so the second upload is not future-dated relative to
    # the logical clock (PRD section 3.4).
    set_clock("2026-09-01T00:01:00Z")
    ra = upload_recording(agency["id"], device, officer,
                          recorded_at="2026-09-01T00:01:00Z", category="ARREST")
    case = create_case(agency["id"], officer)
    link_evidence(agency["id"], case["id"], rt["id"], officer)
    link_arrest = link_evidence(agency["id"], case["id"], ra["id"], officer)
    resp = api.unlink_evidence(agency["id"], case["id"], link_arrest["id"],
                               make_officer_headers(officer["id"]))
    validate_success(resp)
    from test_helpers.fixtures import get_case
    case_now = get_case(agency["id"], case["id"], headers=make_supervisor_headers(officer["id"]))
    # only TRAFFIC_STOP remains linked. Per PRD section 3.5 the link (created
    # at logical now 00:01) extends its due date to max(upload 00:00 + 90d,
    # link 00:01 + 365d) = 2027-09-01T00:01:00Z.
    assert case_now["retention_due_at"] == "2027-09-01T00:01:00Z", (
        f"after unlinking the ARREST recording the rollup must drop to the "
        f"TRAFFIC_STOP due date, got {case_now['retention_due_at']}"
    )
