"""Depth tests for validation precedence between colliding rule categories."""

import test_helpers as th
from test_helpers import fixtures


def _setup_suspended_with_limit(api):
    """ELIGIBLE member (limit 2000) escalated to SUSPENDED; no evaluation has
    run since, so the stored limit still reads 2000 and a 5000 advance would
    also break the fiscal headroom rule."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m9",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    fixtures.record_abuse_event(api, w["member"]["id"], "CUSHION_CYCLING")
    fixtures.record_abuse_event(api, w["member"]["id"], "FIRST_PARTY_FRAUD")
    return w


def test_posture_gate_fires_before_fiscal_limit(api):
    """PRD §2.11: "When a request violates more than one rule, the error
    returned is the one from the highest-priority check. The evaluation order is
    fixed: authentication of headers first; then role authorization (including
    Member ownership); then path resolution left-to-right; then request-body
    well-formedness; then the idempotency conflict check on advance creation;
    then the stale-version check; then state-machine from-state legality; then
    the terminal-lockdown check; then member posture gating; then the abuse
    lock; then the qualifying-deposit requirement; then temporal-window rules;
    then overlap-window rules; then uniqueness constraints; then cross-entity
    referential blocks; and finally the fiscal limit checks (cushion headroom,
    dispute amount, sufficient funds)."

    Design: Difficulty/priority_pair_validation_conflict/posture_state_vs_fiscal_limit_conflict
    """
    w = _setup_suspended_with_limit(api)
    member = fixtures.get_member(api, w["member"]["id"])
    assert member["status"] == "SUSPENDED"
    assert member["current_limit_cents"] == 2000

    account = fixtures.get_account(api, w["account"]["id"])
    resp = api.create_advance(
        w["account"]["id"],
        th.factories.advance_payload(account["version"], amount_cents=5000, idempotency_key="m9-adv"),
        th.make_member_headers(w["member"]["id"]),
    )
    # Posture gating (member posture) outranks the fiscal limit check.
    th.validate_error(resp, th.ApiErrorId.ERR_MEMBER_POSTURE)
    assert resp.status_code == 409


def test_posture_rejection_writes_no_advance(api):
    """PRD §2.11: "A request that fails an earlier check never surfaces a later
    check's error."
    PRD §3.6: "A successful draw creates an `OverdraftAdvance` with `origin`
    `MEMBER_INITIATED`, `principal_cents` equal to the amount, and status
    `OPEN`; the account's `outstanding_cushion_cents` rises by the amount, the
    `posted_balance_cents` is credited with the amount (cushion funds land as
    spendable money), and an `ADVANCE_CREDIT` ledger entry records the
    movement."

    Design: Difficulty/priority_pair_validation_conflict/posture_state_vs_fiscal_limit_conflict
    """
    w = _setup_suspended_with_limit(api)
    account = fixtures.get_account(api, w["account"]["id"])
    resp = api.create_advance(
        w["account"]["id"],
        th.factories.advance_payload(account["version"], amount_cents=5000, idempotency_key="m9-adv"),
        th.make_member_headers(w["member"]["id"]),
    )
    th.validate_error(resp, th.ApiErrorId.ERR_MEMBER_POSTURE)

    advances = fixtures.list_advances(api, w["account"]["id"])
    assert advances == []
    after = fixtures.get_account(api, w["account"]["id"])
    assert after["outstanding_cushion_cents"] == 0
    assert after["posted_balance_cents"] == 20000


def _setup_restricted_with_flag_and_stale_deposit(api):
    """RESTRICTED member with deposit_reroute_flag set; a qualifying payroll
    deposit whose settlement date (2026-08-31) has already passed."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m10",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    fixtures.record_abuse_event(api, w["member"]["id"], "DEPOSIT_REROUTE")
    d3 = fixtures.register_deposit(
        api,
        w["account"]["id"],
        originator_id="EMP10",
        originator_type="PAYROLL",
        amount_cents=15000,
        settlement_date="2026-08-31T00:00:00Z",
        trace_id="m10-t3",
    )
    return w, d3


def test_abuse_lock_fires_before_temporal_rule(api):
    """PRD §2.11: "When a request violates more than one rule, the error
    returned is the one from the highest-priority check. The evaluation order is
    fixed: authentication of headers first; then role authorization (including
    Member ownership); then path resolution left-to-right; then request-body
    well-formedness; then the idempotency conflict check on advance creation;
    then the stale-version check; then state-machine from-state legality; then
    the terminal-lockdown check; then member posture gating; then the abuse
    lock; then the qualifying-deposit requirement; then temporal-window rules;
    then overlap-window rules; then uniqueness constraints; then cross-entity
    referential blocks; and finally the fiscal limit checks (cushion headroom,
    dispute amount, sufficient funds)."
    PRD §3.8: "While that flag is set, advances and early posting are refused
    with `ERR_ABUSE_LOCK` regardless of posture."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_conflict_on_post_early
    """
    w, d3 = _setup_restricted_with_flag_and_stale_deposit(api)
    member = fixtures.get_member(api, w["member"]["id"])
    assert member["status"] == "RESTRICTED"
    assert member["deposit_reroute_flag"] is True

    resp = api.post_early(d3["id"], {}, th.TEST_USERS["program_ops"])
    # Abuse lock outranks the temporal rule that the past settlement date trips.
    th.validate_error(resp, th.ApiErrorId.ERR_ABUSE_LOCK)
    assert resp.status_code == 422


def test_abuse_lock_rejection_leaves_deposit_untouched(api):
    """PRD §3.4: "Registration always creates the deposit in `RECEIVED_FILE`
    status; an overlapping registration is refused outright with
    `ERR_WINDOW_OVERLAP` rather than persisted in any rejected state."
    PRD §3.4: "When early posting succeeds, an `EarlyPosting` record is created
    for the deposit in `PROVISIONAL` status — at most one early posting ever
    exists per deposit — with `posted_amount_cents` equal to the deposit's full
    `amount_cents` and a `reversal_window_end` computed as the settlement date
    plus two calendar days; a return arriving before that instant is treated as
    a reversal-risk return of funds already spent."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_conflict_on_post_early
    """
    _w, d3 = _setup_restricted_with_flag_and_stale_deposit(api)
    resp = api.post_early(d3["id"], {}, th.TEST_USERS["program_ops"])
    th.validate_error(resp, th.ApiErrorId.ERR_ABUSE_LOCK)

    deposit = th.get_success_data(api.get_deposit(d3["id"], th.TEST_USERS["program_ops"]))
    assert deposit["status"] == "RECEIVED_FILE"
    assert fixtures.list_early_postings(api, d3["id"]) == []
