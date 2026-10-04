"""Boundary precision on the accrual claiming-period deadline (strict >)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, make_member_headers,
    create_active_schedule, setup_active_dsp, create_member,
    setup_work_with_share, create_report_with_lines, submit_report,
    accept_report, get_line_accrual, pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_two_accruals_and_claims():
    """Two unmatched lines -> two HELD accruals expiring 2029-07-01T00:00:00Z;
    member A holds a 100% share on work 'Petrel'; one PENDING claim per
    accrual. The report is padded with a matched line so the acceptance
    circuit breaker passes with 26200 unmatched cents."""
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    member = create_member()
    work, _share = setup_work_with_share("Petrel", member)
    report, lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Stormy", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900031"},
        {"track_title": "Gale", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900032"},
    ])
    pad_report_for_match_floor(dsp, dsp_headers, report, 26200)
    submit_report(dsp, dsp_headers, ack, report)
    accept_report(dsp, ack, report)
    accruals = [get_line_accrual(l["id"]) for l in lines]
    mh = make_member_headers(member["id"])
    claims = [validate_success(api_client.create_claim({
        "accrual_id": acc["id"], "claimant_member_id": member["id"],
        "claimed_work_id": work["id"], "share_percent_claimed": 100,
    }, mh), expected_status=201) for acc in accruals]
    return accruals, claims


def test_claim_one_second_before_expiry_validates(api):
    """PRD §2.5: "a claim validation attempted when `hold_expires_at` is at or
    before the current logical time is rejected with `ERR_HOLD_EXPIRED`
    (HTTP 422) — the boundary is strict, so a claim at exactly the expiry
    instant fails."
    PRD §3.6: "The accrual's `hold_expires_at` must be strictly after the
    current logical time (`ERR_HOLD_EXPIRED`)."

    Design: Difficulty/boundary_precision_check/claim_validation_hold_expiry_boundary
    """
    _accruals, claims = _setup_two_accruals_and_claims()
    set_clock("2029-06-30T23:59:59Z")
    validated = validate_success(api_client.validate_claim(claims[0]["id"], ADMIN))
    assert validated["status"] == "VALIDATED", (
        f"one second before expiry the strict > holds; got {validated['status']}")


def test_claim_at_exact_expiry_rejected_and_accrual_unchanged(api):
    """PRD §2.5: "a claim validation attempted when `hold_expires_at` is at or
    before the current logical time is rejected with `ERR_HOLD_EXPIRED`
    (HTTP 422) — the boundary is strict, so a claim at exactly the expiry
    instant fails."

    Design: Difficulty/boundary_precision_check/claim_validation_hold_expiry_boundary
    """
    accruals, claims = _setup_two_accruals_and_claims()
    set_clock("2029-07-01T00:00:00Z")
    validate_error(api_client.validate_claim(claims[1]["id"], ADMIN),
                   ApiErrorId.ERR_HOLD_EXPIRED)
    accrual = validate_success(api_client.get_accrual(accruals[1]["id"], ADMIN))
    assert accrual["status"] == "HELD", (
        f"the rejected validation leaves the accrual HELD; got {accrual['status']}")
