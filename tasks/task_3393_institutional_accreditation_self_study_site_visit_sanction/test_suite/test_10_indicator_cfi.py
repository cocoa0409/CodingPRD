"""Indicator monitoring: dual-variant CFI, band boundaries, EMI flag, tiling."""
import pytest

from test_helpers import (
    EXPECTED_CFI_BOUNDARY,
    EXPECTED_CFI_PRIVATE_VARIANT,
    EXPECTED_CFI_PUBLIC_VARIANT,
    EXPECTED_EMI_BOUNDARY,
    EXPECTED_EMI_HEALTHY,
    EXPECTED_CFI_HEALTHY,
    INDICATOR_METRICS_CFI_BOUNDARY,
    INDICATOR_METRICS_EMI_BOUNDARY,
    INDICATOR_METRICS_VARIANT_PRIVATE,
    INDICATOR_METRICS_VARIANT_PUBLIC,
    PERIOD_2026,
    ApiErrorId,
    create_indicator_report,
    create_institution,
    evaluate_indicator_report,
    get_institution,
    indicator_report_payload,
    list_institution_outcomes,
    list_indicator_reports,
    set_logical_clock,
    submit_indicator_report,
    validate_error,
    validate_success,
)


def test_cfi_public_and_private_variants_diverge(api):
    """PRD section 3.9: "First, the Composite Financial Index lands on `cfi_value`: each ratio is scaled by multiplying by twenty, rounding half-up to two decimal places, and clamping the result to a floor of -4.00 and a ceiling of 10.00; for a private institution (`PRIVATE_NONPROFIT` or `PRIVATE_FORPROFIT`) the index is the scaled primary reserve ratio weighted at 0.40, plus the scaled viability ratio weighted at 0.35, plus the scaled net operating ratio weighted at 0.25, summed and rounded half-up to two decimal places, with no appropriation bonus; for a `PUBLIC` institution the net operating ratio plays no part — the index is the scaled primary reserve ratio weighted at 0.50, plus the scaled viability ratio weighted at 0.50, plus an appropriation bonus of 0.50 when the `state_appropriation_ratio` is at least 0.20 and 0.00 otherwise, again rounded half-up to two decimal places, so identical ratios yield different indices under the two variants."
    PRD section 3.9: "The variant in force, `PUBLIC` or `PRIVATE`, is chosen from the institution's `legal_status` at submit time and frozen onto `cfi_variant_used`."

    Design: Difficulty/dual_variant_calc/cfi_public_private_variant_divergence
    """
    set_logical_clock()
    private = create_institution()
    public = create_institution(
        legal_name="Northern Public University", legal_status="PUBLIC",
        state_code="MN", fte_enrollment=500, degree_levels_offered=["ASSOCIATE"],
    )

    report_p = create_indicator_report(private["id"], *PERIOD_2026)
    submitted_p = submit_indicator_report(
        report_p["id"], private["id"], INDICATOR_METRICS_VARIANT_PRIVATE
    )
    report_q = create_indicator_report(public["id"], *PERIOD_2026)
    submitted_q = submit_indicator_report(
        report_q["id"], public["id"], INDICATOR_METRICS_VARIANT_PUBLIC
    )

    assert submitted_p["cfi_variant_used"] == "PRIVATE"
    assert submitted_p["cfi_value"] == pytest.approx(EXPECTED_CFI_PRIVATE_VARIANT, abs=0.001)
    assert submitted_q["cfi_variant_used"] == "PUBLIC"
    assert submitted_q["cfi_value"] == pytest.approx(EXPECTED_CFI_PUBLIC_VARIANT, abs=0.001)
    # Identical ratios diverge by exactly the reweighted 0.50 appropriation bonus.
    assert submitted_q["cfi_value"] - submitted_p["cfi_value"] == pytest.approx(0.75, abs=0.001)


def test_cfi_exactly_at_clear_boundary_flags_review(api):
    """PRD section 3.9: "The band boundaries are pinned: a CFI strictly above 1.10 is the `CLEAR` band; a CFI at or below 1.10 but strictly above -0.90 is the `REVIEW` band; and a CFI at or below -0.90 is the `PANEL` band."
    PRD section 3.9: "A report whose CFI falls in the `REVIEW` band — or whose EMI is below -5.00 while its CFI stands in the `CLEAR` band — is marked `FLAGGED_REVIEW`."

    Design: Difficulty/boundary_precision_check/cfi_exactly_at_clear_boundary_flags_review
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]
    report = create_indicator_report(institution_id, *PERIOD_2026)
    submitted = submit_indicator_report(
        report["id"], institution_id, INDICATOR_METRICS_CFI_BOUNDARY
    )
    assert submitted["cfi_value"] == pytest.approx(EXPECTED_CFI_BOUNDARY, abs=0.001)
    assert submitted["emi_value"] == pytest.approx(EXPECTED_EMI_HEALTHY, abs=0.001)

    evaluated = evaluate_indicator_report(report["id"])
    assert evaluated["status"] == "FLAGGED_REVIEW"

    assert list_institution_outcomes(institution_id) == []
    institution = get_institution(institution_id)
    assert institution["sanction_status"] == "NONE"
    assert institution["latest_cfi_value"] == pytest.approx(EXPECTED_CFI_BOUNDARY, abs=0.001)
    assert institution["latest_cfi_band"] == "REVIEW"


def test_emi_exactly_at_flag_boundary_not_flagged(api):
    """PRD section 3.9: "Second, the Enrollment Momentum Index lands on `emi_value`: half of `enrollment_change_pct`, plus three tenths of the amount by which `completion_rate` exceeds its neutral value of 50.0, plus one fifth of the amount by which `retention_rate` exceeds its neutral value of 70.0, rounded half-up to two decimal places; an index strictly below -5.00 flags the report, while exactly -5.00 does not flag."
    PRD section 3.9: "A report whose CFI falls in the `CLEAR` band and whose EMI is at least -5.00 is marked `CLEARED`."

    Design: Corner/calculations/emi_exactly_at_flag_boundary_not_flagged
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]
    report = create_indicator_report(institution_id, *PERIOD_2026)
    submitted = submit_indicator_report(
        report["id"], institution_id, INDICATOR_METRICS_EMI_BOUNDARY
    )
    assert submitted["emi_value"] == pytest.approx(EXPECTED_EMI_BOUNDARY, abs=0.001)
    assert submitted["cfi_value"] == pytest.approx(EXPECTED_CFI_HEALTHY, abs=0.001)

    evaluated = evaluate_indicator_report(report["id"])
    assert evaluated["status"] == "CLEARED"
    assert list_institution_outcomes(institution_id) == []


def test_indicator_periods_must_tile_contiguously(api, staff_headers):
    """PRD section 3.9: "Periods must tile the institution's reporting history contiguously: the closed interval from `period_start` through `period_end` may not intersect any existing report period of the institution — an overlap is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409) — and unless it is the institution's first report, the new `period_start` must be exactly one day after the latest existing `period_end`, any gap being rejected with `ERR_REPORT_PERIOD_GAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/indicator_periods_must_tile_without_gap_or_overlap
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]
    create_indicator_report(institution_id, *PERIOD_2026)

    overlap = api.create_indicator_report(
        institution_id, indicator_report_payload("2026-07-01", "2027-06-30"), staff_headers
    )
    validate_error(overlap, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    gap = api.create_indicator_report(
        institution_id, indicator_report_payload("2027-02-01", "2028-01-31"), staff_headers
    )
    validate_error(gap, ApiErrorId.ERR_REPORT_PERIOD_GAP)

    adjacent = api.create_indicator_report(
        institution_id, indicator_report_payload("2027-01-01", "2027-12-31"), staff_headers
    )
    assert validate_success(adjacent, 201)["status"] == "DUE"


def test_admin_cannot_evaluate_indicator_report(api, admin_headers):
    """PRD section 2.1: "A request whose role is not among the roles authorized for the target endpoint, or that fails the entity-backed ownership binding described below, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 4: "| POST   | `/accreditation/indicator-reports/{id}/evaluate` | Evaluate a submitted report into its band verdict | CommissionStaff |"

    Design: Corner/rbac/admin_cannot_evaluate_indicator_report
    """
    set_logical_clock()
    institution = create_institution()
    institution_id = institution["id"]
    report = create_indicator_report(institution_id, *PERIOD_2026)
    submit_indicator_report(report["id"], institution_id)

    response = api.evaluate_indicator_report(report["id"], {}, admin_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    reports = list_indicator_reports(institution_id)
    assert reports[0]["status"] == "SUBMITTED"
