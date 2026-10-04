"""Breadth tests for authentication, request well-formedness, uniqueness, and
the business-rule validation errors."""

import test_helpers as th
from test_helpers import fixtures


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    outside this set, is rejected with `ERR_UNAUTHENTICATED` (401)."
    PRD §2.11: "When a request violates more than one rule, the error returned
    is the one from the highest-priority check. The evaluation order is fixed:
    authentication of headers first; then role authorization (including Member
    ownership); then path resolution left-to-right; then request-body
    well-formedness; then the idempotency conflict check on advance creation;
    then the stale-version check; then state-machine from-state legality; then
    the terminal-lockdown check; then member posture gating; then the abuse
    lock; then the qualifying-deposit requirement; then temporal-window rules;
    then overlap-window rules; then uniqueness constraints; then cross-entity
    referential blocks; and finally the fiscal limit checks (cushion headroom,
    dispute amount, sufficient funds)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    # No headers at all — authentication outranks path resolution, so even a
    # non-existent id yields 401, not 404.
    resp = api.get_member(th.constants.MISSING_UUID, headers={})
    th.validate_error(resp, th.ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_post_early_non_qualifying_rejected(api):
    """PRD §3.4: "A `ProgramOps` operator may make a deposit spendable ahead of
    settlement — transitioning the deposit `RECEIVED_FILE → POSTED_EARLY` —
    only when all of the following hold: the deposit qualifies (payroll, at
    least 10000 cents; otherwise `ERR_NOT_QUALIFYING`); the logical clock is
    still before the deposit's `settlement_date` (posting early on or after the
    settlement date is a temporal violation, `ERR_TEMPORAL_VIOLATION`); the
    member's posture is `ELIGIBLE` or `RESTRICTED` (otherwise
    `ERR_MEMBER_POSTURE`); the member's `deposit_reroute_flag` is not set
    (otherwise `ERR_ABUSE_LOCK`); and no reconciliation run in `DISCREPANCY`
    status for the account's sponsor bank has a window containing the current
    clock (otherwise `ERR_REFERENTIAL_BLOCK` — early posting freezes bank-wide
    while a ledger discrepancy stands)."

    Design: Corner/validations/post_early_non_qualifying_rejected
    """
    w = fixtures.setup_eligible_member(
        api,
        external_ref="c18",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    dep = fixtures.register_deposit(
        api,
        w["account"]["id"],
        originator_id="EMPC18",
        originator_type="PAYROLL",
        amount_cents=9999,
        settlement_date="2026-09-05T00:00:00Z",
        trace_id="c18-t3",
    )
    resp = api.post_early(dep["id"], {}, th.TEST_USERS["program_ops"])
    th.validate_error(resp, th.ApiErrorId.ERR_NOT_QUALIFYING)
    assert resp.status_code == 422

    deposit = th.get_success_data(api.get_deposit(dep["id"], th.TEST_USERS["program_ops"]))
    assert deposit["status"] == "RECEIVED_FILE"
    assert fixtures.list_early_postings(api, dep["id"]) == []


def test_duplicate_trace_id_rejected(api):
    """PRD §3.4: "Inbound ACH credit files are registered by `SponsorBankOps`
    against a spending account — the deposit, and later any advance or ledger
    entry touching the account, records its destination as `account_id` —
    supplying the `originator_id` (the employer payroll identifier), the
    `originator_type` (`PAYROLL` or `OTHER`), the gross `amount_cents`
    (strictly positive), the `settlement_date` from the file, and the ACH
    `trace_id`, which must be unique across all deposits — a duplicate trace is
    refused with `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_trace_id_rejected
    """
    member_a = fixtures.create_member(
        api, external_ref="c19", full_name="C Nineteen", enrolled_at="2025-09-01T00:00:00Z"
    )
    account_a = fixtures.open_account(api, member_a["id"])
    member_b = fixtures.create_member(
        api, external_ref="c20", full_name="C Twenty", enrolled_at="2025-09-01T00:00:00Z"
    )
    account_b = fixtures.open_account(api, member_b["id"])

    fixtures.register_deposit(
        api,
        account_a["id"],
        originator_id="EMPX",
        amount_cents=10000,
        settlement_date="2026-09-10T00:00:00Z",
        trace_id="shared-1",
    )
    # Same trace on a different account is still a duplicate.
    resp = api.create_deposit(
        account_b["id"],
        th.factories.deposit_payload(
            originator_id="EMPY",
            amount_cents=5000,
            settlement_date="2026-09-20T00:00:00Z",
            trace_id="shared-1",
        ),
        th.TEST_USERS["sponsor_bank_ops"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_DUPLICATE)
    assert resp.status_code == 409


def _setup_discrepancy_block(api):
    """ELIGIBLE member; one settled 15000 deposit; a DISCREPANCY run whose
    window covers the current clock; a fresh qualifying deposit awaiting
    early posting."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="c21",
        num_deposits=2,
        settlement_dates=["2026-08-20T00:00:00Z", "2026-08-28T00:00:00Z"],
        deposit_amount_cents=10000,
    )
    run = th.get_success_data(
        api.create_reconciliation_run(
            th.factories.reconciliation_run_payload(
                sponsor_bank_code="SB-1",
                period_start="2026-08-15T00:00:00Z",
                period_end="2026-09-15T00:00:00Z",
                bank_reported_net_cents=0,
            ),
            th.TEST_USERS["sponsor_bank_ops"],
        )
    )
    d3 = fixtures.register_deposit(
        api,
        w["account"]["id"],
        originator_id="EMPC21",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-09-10T00:00:00Z",
        trace_id="c21-t3",
    )
    return w, run, d3


def test_post_early_blocked_by_discrepancy_run(api):
    """PRD §3.4: "A `ProgramOps` operator may make a deposit spendable ahead of
    settlement — transitioning the deposit `RECEIVED_FILE → POSTED_EARLY` —
    only when all of the following hold: the deposit qualifies (payroll, at
    least 10000 cents; otherwise `ERR_NOT_QUALIFYING`); the logical clock is
    still before the deposit's `settlement_date` (posting early on or after the
    settlement date is a temporal violation, `ERR_TEMPORAL_VIOLATION`); the
    member's posture is `ELIGIBLE` or `RESTRICTED` (otherwise
    `ERR_MEMBER_POSTURE`); the member's `deposit_reroute_flag` is not set
    (otherwise `ERR_ABUSE_LOCK`); and no reconciliation run in `DISCREPANCY`
    status for the account's sponsor bank has a window containing the current
    clock (otherwise `ERR_REFERENTIAL_BLOCK` — early posting freezes bank-wide
    while a ledger discrepancy stands)."

    Design: Corner/validations/post_early_blocked_by_discrepancy_run
    """
    _w, run, d3 = _setup_discrepancy_block(api)
    assert run["status"] == "DISCREPANCY"

    resp = api.post_early(d3["id"], {}, th.TEST_USERS["program_ops"])
    th.validate_error(resp, th.ApiErrorId.ERR_REFERENTIAL_BLOCK)
    assert resp.status_code == 422
    assert fixtures.list_early_postings(api, d3["id"]) == []


def test_dispute_amount_exceeds_deposit_rejected(api):
    """PRD §3.9: "The amount must be positive and must not exceed the disputed
    deposit's `amount_cents`, or the filing is refused with
    `ERR_DISPUTE_AMOUNT_EXCEEDS`."

    Design: Corner/validations/dispute_amount_exceeds_deposit_rejected
    """
    w = fixtures.setup_eligible_member(
        api,
        external_ref="c22",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    d3 = fixtures.register_deposit(
        api,
        w["account"]["id"],
        originator_id="EMPC22",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-09-05T00:00:00Z",
        trace_id="c22-t3",
    )
    fixtures.post_early(api, d3["id"])
    headers = th.make_member_headers(w["member"]["id"])

    resp = api.create_dispute(
        th.factories.dispute_payload(
            d3["id"],
            dispute_type="EARLY_POSTING_REVERSAL",
            amount_cents=10001,
            statement="too much",
        ),
        headers,
    )
    th.validate_error(resp, th.ApiErrorId.ERR_DISPUTE_AMOUNT_EXCEEDS)
    assert resp.status_code == 422

    # Exactly the deposit amount is allowed (inclusive boundary).
    resp = api.create_dispute(
        th.factories.dispute_payload(
            d3["id"],
            dispute_type="EARLY_POSTING_REVERSAL",
            amount_cents=10000,
            statement="exact amount ok",
        ),
        headers,
    )
    dispute = th.validate_success(resp, expected_status=201)
    assert dispute["case_status"] == "FILED"


def test_invalid_enum_value_rejected(api):
    """PRD §3.4: "Inbound ACH credit files are registered by `SponsorBankOps`
    against a spending account — the deposit, and later any advance or ledger
    entry touching the account, records its destination as `account_id` —
    supplying the `originator_id` (the employer payroll identifier), the
    `originator_type` (`PAYROLL` or `OTHER`), the gross `amount_cents`
    (strictly positive), the `settlement_date` from the file, and the ACH
    `trace_id`, which must be unique across all deposits — a duplicate trace is
    refused with `ERR_DUPLICATE`."

    Design: Corner/validations/invalid_enum_value_rejected
    """
    member = fixtures.create_member(
        api, external_ref="c23", full_name="C TwentyThree", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    resp = api.create_deposit(
        account["id"],
        th.factories.deposit_payload(
            originator_id="EMPZ",
            originator_type="WIRE",
            amount_cents=10000,
            settlement_date="2026-09-10T00:00:00Z",
            trace_id="c23-t1",
        ),
        th.TEST_USERS["sponsor_bank_ops"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400


def _setup_advance_with_key(api, ref, key):
    w = fixtures.setup_eligible_member(
        api,
        external_ref=ref,
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    adv = fixtures.draw_advance(
        api, w["account"]["id"], w["member"]["id"], 1000, idempotency_key=key
    )
    return w, adv


def test_idempotency_conflict_on_advance(api):
    """PRD §2.9: "Advance creation accepts a client-supplied
    `idempotency_key`. A repeated request that reuses a key with an identical
    payload returns the originally created advance rather than creating a
    second one. Reusing the same key with a different payload is rejected with
    `ERR_IDEMPOTENCY_CONFLICT` (409)."

    Design: Corner/validations/idempotency_conflict_on_advance
    """
    w, adv = _setup_advance_with_key(api, "c24", "c24-k1")
    assert adv["principal_cents"] == 1000

    account = fixtures.get_account(api, w["account"]["id"])
    resp = api.create_advance(
        w["account"]["id"],
        th.factories.advance_payload(
            account["version"], amount_cents=2000, idempotency_key="c24-k1"
        ),
        th.make_member_headers(w["member"]["id"]),
    )
    th.validate_error(resp, th.ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)
    assert resp.status_code == 409

    advances = fixtures.list_advances(api, w["account"]["id"])
    assert len(advances) == 1
    after = fixtures.get_account(api, w["account"]["id"])
    assert after["outstanding_cushion_cents"] == 1000
