"""Outcome confirmation and notes: units consistency, the singleton outcome
record, and reverse reachability.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_outcome_record,
    setup_routed_referral, accept_referral, start_service, confirm_outcome,
    get_referral,
    make_org_admin_headers,
)


def test_error_outcome_units_mismatch_on_confirm():
    """PRD §3.6: "Units must agree with the outcome: at least 1 unit for
    `DELIVERED` or `PARTIALLY_DELIVERED`, exactly 0 for `NOT_REACHED` or
    `CLIENT_DECLINED`, with any mismatch rejected as
    `ERR_OUTCOME_UNITS_MISMATCH`."

    Design: Corner/errors/error_outcome_units_mismatch_on_confirm
    """
    ctx, referral = setup_routed_referral()
    accept_referral(ctx, referral["id"])
    start_service(ctx, referral["id"])

    validate_error(api_client.confirm_outcome(
        referral["id"], {"outcome_code": "NOT_REACHED", "delivered_units": 1},
        make_org_admin_headers(ctx["receiver_id"])),
        ApiErrorId.ERR_OUTCOME_UNITS_MISMATCH, expected_status=422)

    assert get_referral(referral["id"])["status"] == "IN_SERVICE"
    # No OutcomeRecord was created by the rejected confirmation.
    outcomes, _ = validate_paginated(api_client.get_referral_outcome(
        referral["id"], make_org_admin_headers(ctx["receiver_id"])))
    assert len(outcomes) == 0


def test_outcome_record_reverse_reachable_and_singleton():
    """PRD §3.6: "Confirmation creates the referral's single `OutcomeRecord` —
    exactly one per referral; a second is a duplicate — capturing the
    `outcome_code`, `delivered_units`, the reporting organization as
    `reported_by_org_id`, and the server timestamp as `reported_at`. The
    record's `billable` flag is true precisely when the outcome is `DELIVERED`
    or `PARTIALLY_DELIVERED` with at least 1 delivered unit."
    PRD §3.6: "An outcome record is retrievable through its referral (an array
    of zero or one) or listed per reporting organization."

    Design: Corner/endpoints/outcome_record_reverse_reachable_and_singleton
    """
    ctx, referral = setup_routed_referral()
    reader = make_org_admin_headers(ctx["receiver_id"])

    # Before confirmation the reverse lookup returns an empty array.
    outcomes, _ = validate_paginated(api_client.get_referral_outcome(
        referral["id"], reader))
    assert len(outcomes) == 0

    accept_referral(ctx, referral["id"])
    start_service(ctx, referral["id"])
    confirm_outcome(ctx, referral["id"], "DELIVERED", 3)

    outcomes, _ = validate_paginated(api_client.get_referral_outcome(
        referral["id"], reader))
    assert len(outcomes) == 1
    record = outcomes[0]
    assert_outcome_record(record)
    assert record["referral_id"] == referral["id"]
    assert record["outcome_code"] == "DELIVERED"
    assert record["delivered_units"] == 3
    assert record["billable"] is True
    assert record["reported_by_org_id"] == ctx["receiver_id"]
