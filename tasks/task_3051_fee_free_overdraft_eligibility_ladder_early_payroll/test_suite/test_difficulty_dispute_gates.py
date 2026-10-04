"""Depth tests for cross-entity gates on dispute provisional credit."""

import test_helpers as th
from test_helpers import fixtures


def _setup_two_disputes(api):
    """ELIGIBLE member with one POSTED_EARLY deposit and one SETTLED deposit,
    and one dispute filed against each."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m16",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]
    d_early = fixtures.register_deposit(
        api,
        account_id,
        originator_id="EMP16",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-09-04T00:00:00Z",
        trace_id="m16-t3",
    )
    fixtures.post_early(api, d_early["id"])
    d_settled = fixtures.register_deposit(
        api,
        account_id,
        originator_id="EMP16B",
        originator_type="PAYROLL",
        amount_cents=8000,
        settlement_date="2026-09-01T00:00:00Z",
        trace_id="m16-t4",
    )
    fixtures.settle_deposit(api, d_settled["id"])

    dispute_a = th.get_success_data(
        api.create_dispute(
            th.factories.dispute_payload(
                d_early["id"],
                dispute_type="EARLY_POSTING_REVERSAL",
                amount_cents=2000,
                statement="early posted funds dispute",
            ),
            th.make_member_headers(member_id),
        )
    )
    dispute_b = th.get_success_data(
        api.create_dispute(
            th.factories.dispute_payload(
                d_settled["id"],
                dispute_type="DEPOSIT_RETURN_CLAIM",
                amount_cents=2000,
                statement="settled deposit dispute",
            ),
            th.make_member_headers(member_id),
        )
    )
    return w, d_early, d_settled, dispute_a, dispute_b


def test_provisional_credit_allowed_against_posted_early_deposit(api):
    """PRD §3.9: "A `DisputesAgent` issues provisional credit while the case is
    `FILED` or `UNDER_REVIEW` and `provisional_status` is `NONE`, provided the
    linked deposit is in `POSTED_EARLY` or `RETURNED` status — provisional
    credit exists only against early-posted or returned funds — and provided
    the clock has not passed `provisional_due_at`; issuance after the deadline
    is rejected outright with `ERR_TEMPORAL_VIOLATION` rather than issued late,
    while issuance exactly at the deadline is allowed."

    Design: Difficulty/cross_entity_state_dependency/provisional_credit_gated_by_deposit_state
    """
    _w, _d_early, _d_settled, dispute_a, _dispute_b = _setup_two_disputes(api)
    issued = th.get_success_data(
        api.issue_provisional_credit(dispute_a["id"], {}, th.TEST_USERS["disputes_agent"])
    )
    assert issued["provisional_status"] == "PROVISIONAL_ISSUED"
    assert issued["case_status"] == "UNDER_REVIEW"


def test_provisional_credit_rejected_against_settled_deposit(api):
    """PRD §3.9: "A `DisputesAgent` issues provisional credit while the case is
    `FILED` or `UNDER_REVIEW` and `provisional_status` is `NONE`, provided the
    linked deposit is in `POSTED_EARLY` or `RETURNED` status — provisional
    credit exists only against early-posted or returned funds — and provided
    the clock has not passed `provisional_due_at`; issuance after the deadline
    is rejected outright with `ERR_TEMPORAL_VIOLATION` rather than issued late,
    while issuance exactly at the deadline is allowed."

    Design: Difficulty/cross_entity_state_dependency/provisional_credit_gated_by_deposit_state
    """
    _w, _d_early, d_settled, _dispute_a, dispute_b = _setup_two_disputes(api)
    deposit = th.get_success_data(api.get_deposit(d_settled["id"], th.TEST_USERS["program_ops"]))
    assert deposit["status"] == "SETTLED"

    resp = api.issue_provisional_credit(dispute_b["id"], {}, th.TEST_USERS["disputes_agent"])
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_STATE)

    current = th.get_success_data(api.get_dispute(dispute_b["id"], th.TEST_USERS["disputes_agent"]))
    assert current["provisional_status"] == "NONE"
