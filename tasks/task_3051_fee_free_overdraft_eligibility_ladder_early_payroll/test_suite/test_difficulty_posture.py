"""Depth tests for the member posture cycle and cross-entity gates."""

import test_helpers as th
from test_helpers import fixtures


def _setup_three_advances_then_restricted(api):
    """ELIGIBLE member (limit 2000) with three open 600 advances, then a
    DEPOSIT_REROUTE abuse event that moves the member to RESTRICTED."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m5",
        num_deposits=2,
        settlement_dates=["2026-08-07T00:00:00Z", "2026-08-14T00:00:00Z"],
    )
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]
    advances = [
        fixtures.draw_advance(api, account_id, member_id, 600, idempotency_key=f"m5-adv{i}")
        for i in range(1, 4)
    ]
    fixtures.record_abuse_event(api, member_id, "DEPOSIT_REROUTE")
    return w, advances


def test_posture_cycle_rehabilitation_at_three_on_time_repayments(api):
    """PRD §3.8: "While `RESTRICTED`, each on-time advance repayment increments
    `restricted_consecutive_repayments`; when that counter reaches three, the
    member is automatically restored `RESTRICTED → ELIGIBLE` and the
    `deposit_reroute_flag` clears — the only way that flag ever clears."

    Design: Difficulty/non_linear_state_machine/member_posture_cycle_restricted_to_eligible
    """
    w, _advances = _setup_three_advances_then_restricted(api)
    member = fixtures.get_member(api, w["member"]["id"])
    assert member["status"] == "RESTRICTED"
    assert member["deposit_reroute_flag"] is True

    fixtures.repay_with_qualifying_deposit(
        api,
        w["account"]["id"],
        "EMP5",
        amount_cents=1800,
        settlement_date="2026-09-01T00:00:00Z",
        trace_suffix="r1",
    )

    member = fixtures.get_member(api, w["member"]["id"])
    assert member["status"] == "ELIGIBLE"
    assert member["deposit_reroute_flag"] is False
    assert member["consecutive_on_time_repayments"] == 3


def test_posture_cycle_waterfall_repays_all_three_advances(api):
    """PRD §3.6: "When the deposit is qualifying, the waterfall walks the
    account's `OPEN` and `PARTIALLY_REPAID` advances oldest first by
    `created_at`, allocating to each the lesser of its `outstanding_cents` and
    the remaining deposit funds, recording each allocation as a
    `RepaymentAllocation` with `allocation_mode` `WATERFALL` — every allocation
    row carries the `advance_id` it repays and the `deposit_id` that funded it —
    until the deposit is exhausted."
    PRD §3.8: "The first abuse event recorded while the member is `ELIGIBLE` —
    bringing the ninety-day count to exactly one — moves the member
    `ELIGIBLE → RESTRICTED`, resets `restricted_consecutive_repayments` to zero,
    and, when the event type is `DEPOSIT_REROUTE`, sets the
    `deposit_reroute_flag`."

    Design: Difficulty/non_linear_state_machine/member_posture_cycle_restricted_to_eligible
    """
    w, advances = _setup_three_advances_then_restricted(api)
    repay_dep = fixtures.repay_with_qualifying_deposit(
        api,
        w["account"]["id"],
        "EMP5",
        amount_cents=10000,
        settlement_date="2026-09-01T00:00:00Z",
        trace_suffix="r1",
    )

    allocs = fixtures.list_allocations_for_deposit(api, repay_dep["id"])
    assert len(allocs) == 3
    assert sum(a["amount_cents"] for a in allocs) == 1800
    for alloc in allocs:
        assert alloc["allocation_mode"] == "WATERFALL"

    for adv in advances:
        current = th.get_success_data(api.get_advance(adv["id"], th.TEST_USERS["program_ops"]))
        assert current["status"] == "REPAID"
        assert current["outstanding_cents"] == 0
        assert current["on_time"] is True


def _setup_dispute_parallel(api):
    """ELIGIBLE member; a 10000 payroll deposit posted early then returned; a
    4000 dispute filed on the returned deposit."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m6",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]
    d3 = fixtures.register_deposit(
        api,
        account_id,
        originator_id="EMP6",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-09-04T00:00:00Z",
        trace_id="m6-t3",
    )
    fixtures.post_early(api, d3["id"])
    fixtures.return_deposit(api, d3["id"], return_code="R01_INSUFFICIENT")
    dispute = th.get_success_data(
        api.create_dispute(
            th.factories.dispute_payload(
                d3["id"],
                dispute_type="DEPOSIT_RETURN_CLAIM",
                amount_cents=4000,
                statement="returned funds were already made available",
            ),
            th.make_member_headers(member_id),
        )
    )
    account_before = fixtures.get_account(api, account_id)
    return w, d3, dispute, account_before


def test_dispute_parallel_dimensions(api):
    """PRD §3.9: "Issuance moves `provisional_status` to `PROVISIONAL_ISSUED`,
    moves a `FILED` case to `UNDER_REVIEW`, adds the disputed amount to the
    account's `holds_cents`, and writes a `PROVISIONAL_CREDIT` ledger entry."
    PRD §3.9: "Resolving for the bank moves `case_status` to `RESOLVED_BANK`
    and, when provisional credit was issued, reclaims it: `provisional_status`
    becomes `PROVISIONAL_RECLAIMED`, the hold is released from `holds_cents`,
    and a `PROVISIONAL_REVERSAL` ledger entry records the clawback."

    Design: Difficulty/non_linear_state_machine/dispute_parallel_dimensions
    """
    w, _d3, dispute, account_before = _setup_dispute_parallel(api)
    issued = th.get_success_data(
        api.issue_provisional_credit(dispute["id"], {}, th.TEST_USERS["disputes_agent"])
    )
    assert issued["case_status"] == "UNDER_REVIEW"
    assert issued["provisional_status"] == "PROVISIONAL_ISSUED"

    account_held = fixtures.get_account(api, w["account"]["id"])
    assert account_held["holds_cents"] == account_before["holds_cents"] + 4000

    resolved = th.get_success_data(
        api.resolve_dispute(
            dispute["id"],
            th.factories.dispute_resolve_payload(outcome="BANK", resolution_note="return was valid"),
            th.TEST_USERS["disputes_agent"],
        )
    )
    assert resolved["case_status"] == "RESOLVED_BANK"
    assert resolved["provisional_status"] == "PROVISIONAL_RECLAIMED"

    account_final = fixtures.get_account(api, w["account"]["id"])
    assert account_final["holds_cents"] == account_before["holds_cents"]


def test_dispute_dimensions_move_independently(api):
    """PRD §3.9: "A `DisputesAgent` issues provisional credit while the case is
    `FILED` or `UNDER_REVIEW` and `provisional_status` is `NONE`, provided the
    linked deposit is in `POSTED_EARLY` or `RETURNED` status — provisional
    credit exists only against early-posted or returned funds — and provided
    the clock has not passed `provisional_due_at`; issuance after the deadline
    is rejected outright with `ERR_TEMPORAL_VIOLATION` rather than issued late,
    while issuance exactly at the deadline is allowed."
    PRD §3.9: "Resolving for the bank moves `case_status` to `RESOLVED_BANK`
    and, when provisional credit was issued, reclaims it: `provisional_status`
    becomes `PROVISIONAL_RECLAIMED`, the hold is released from `holds_cents`,
    and a `PROVISIONAL_REVERSAL` ledger entry records the clawback."

    Design: Difficulty/non_linear_state_machine/dispute_parallel_dimensions
    """
    _w, _d3, dispute, _before = _setup_dispute_parallel(api)
    assert dispute["case_status"] == "FILED"
    assert dispute["provisional_status"] == "NONE"

    issued = th.get_success_data(
        api.issue_provisional_credit(dispute["id"], {}, th.TEST_USERS["disputes_agent"])
    )
    # One trigger advanced both dimensions exactly one step.
    assert issued["case_status"] == "UNDER_REVIEW"
    assert issued["provisional_status"] == "PROVISIONAL_ISSUED"

    entries = fixtures.list_ledger_entries(
        api, _w["account"]["id"], params={"entry_type": "PROVISIONAL_CREDIT"}
    )
    assert len(entries) == 1
    th.assert_ledger_entry(entries[0])


def _setup_two_members_for_posture_gate(api):
    """Two identical members, m14 left ELIGIBLE and m15 moved to RESTRICTED."""
    w14 = fixtures.setup_eligible_member(
        api,
        external_ref="m14",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    w15 = fixtures.setup_eligible_member(
        api,
        external_ref="m15",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    fixtures.record_abuse_event(api, w15["member"]["id"], "CUSHION_CYCLING")
    return w14, w15


def test_advance_allowed_while_eligible(api):
    """PRD §3.1: "Posture gates everything the cushion offers: advances may be
    drawn only while `ELIGIBLE`; early posting is available while `ELIGIBLE` or
    `RESTRICTED`; `ENROLLED` and `SUSPENDED` members are refused with
    `ERR_MEMBER_POSTURE` for both operations."

    Design: Difficulty/cross_entity_state_dependency/advance_gated_by_member_posture
    """
    w14, w15 = _setup_two_members_for_posture_gate(api)
    adv = fixtures.draw_advance(api, w14["account"]["id"], w14["member"]["id"], 1000)
    th.assert_overdraft_advance(adv)
    assert adv["status"] == "OPEN"
    assert adv["origin"] == "MEMBER_INITIATED"

    member15 = fixtures.get_member(api, w15["member"]["id"])
    assert member15["status"] == "RESTRICTED"


def test_advance_rejected_while_restricted(api):
    """PRD §3.1: "Posture gates everything the cushion offers: advances may be
    drawn only while `ELIGIBLE`; early posting is available while `ELIGIBLE` or
    `RESTRICTED`; `ENROLLED` and `SUSPENDED` members are refused with
    `ERR_MEMBER_POSTURE` for both operations."
    PRD §3.8: "The first abuse event recorded while the member is `ELIGIBLE` —
    bringing the ninety-day count to exactly one — moves the member
    `ELIGIBLE → RESTRICTED`, resets `restricted_consecutive_repayments` to zero,
    and, when the event type is `DEPOSIT_REROUTE`, sets the
    `deposit_reroute_flag`."

    Design: Difficulty/cross_entity_state_dependency/advance_gated_by_member_posture
    """
    _w14, w15 = _setup_two_members_for_posture_gate(api)
    account15 = fixtures.get_account(api, w15["account"]["id"])
    resp = api.create_advance(
        w15["account"]["id"],
        th.factories.advance_payload(account15["version"], amount_cents=1000, idempotency_key="m15-a1"),
        th.make_member_headers(w15["member"]["id"]),
    )
    th.validate_error(resp, th.ApiErrorId.ERR_MEMBER_POSTURE)
    after = fixtures.get_account(api, w15["account"]["id"])
    assert after["outstanding_cushion_cents"] == 0
