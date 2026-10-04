"""Claim validation: state gate precedes the hold-expiry temporal gate."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    set_clock, make_member_headers, get_line_accrual,
    setup_accepted_report_with_unmatched_line, create_member,
    setup_work_with_share,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]


def _setup_rejected_claim_on_expired_accrual():
    """Claim created and REJECTED while the hold is open; the clock is then
    advanced past the accrual's hold_expires_at."""
    dsp, dsp_headers, ack, report, line, accrual = \
        setup_accepted_report_with_unmatched_line(
            title="Storm Petrel", plays=1000)
    member = create_member()
    work, _share = setup_work_with_share("Petrel", member)
    claim = validate_success(api_client.create_claim({
        "accrual_id": accrual["id"], "claimant_member_id": member["id"],
        "claimed_work_id": work["id"], "share_percent_claimed": 100,
    }, make_member_headers(member["id"])), expected_status=201)
    validate_success(api_client.reject_claim(claim["id"], ADMIN))
    set_clock("2029-08-01T00:00:00Z")
    return claim


def test_validating_rejected_claim_returns_invalid_state(api):
    """PRD §3.6: "Validation is the administrative act that turns a claim into
    money, and its checks are evaluated in this order. The claim must be
    `PENDING` (`ERR_INVALID_STATE`). The target accrual must be `HELD`
    (`ERR_ACCRUAL_NOT_HELD`, HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_before_temporal_claim_window
    """
    claim = _setup_rejected_claim_on_expired_accrual()
    validate_error(api_client.validate_claim(claim["id"], ADMIN),
                   ApiErrorId.ERR_INVALID_STATE)


def test_hold_expiry_alone_returns_hold_expired(api):
    """PRD §2.5: "a claim validation attempted when `hold_expires_at` is at or
    before the current logical time is rejected with `ERR_HOLD_EXPIRED`
    (HTTP 422) — the boundary is strict, so a claim at exactly the expiry
    instant fails."

    Design: Difficulty/priority_pair_validation_conflict/state_before_temporal_claim_window
    """
    dsp, dsp_headers, ack, report, line, accrual = \
        setup_accepted_report_with_unmatched_line(
            title="Storm Petrel", plays=1000)
    member = create_member()
    work, _share = setup_work_with_share("Petrel", member)
    claim = validate_success(api_client.create_claim({
        "accrual_id": accrual["id"], "claimant_member_id": member["id"],
        "claimed_work_id": work["id"], "share_percent_claimed": 100,
    }, make_member_headers(member["id"])), expected_status=201)
    set_clock("2029-08-01T00:00:00Z")
    validate_error(api_client.validate_claim(claim["id"], ADMIN),
                   ApiErrorId.ERR_HOLD_EXPIRED)
