"""Breadth tests for optimistic concurrency, idempotent replay, and immediate
read-after-write consistency."""

import test_helpers as th
from test_helpers import fixtures


def _setup_eligible(api, ref):
    return fixtures.setup_eligible_member(
        api,
        external_ref=ref,
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )


def test_stale_account_version_on_advance_rejected(api):
    """PRD §2.8: "Creating an advance on an account requires
    `expected_account_version`, matched against the owning DepositAccount's
    current `version`. A prior advance draw or repayment legitimately changed
    the account's headroom, so a client holding a stale view of the account
    must not create an advance against it."
    PRD §2.8: "if that value does not match the parent entity's current
    `version` at the time the request is processed, the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross_cutting_layers/stale_account_version_on_advance_rejected
    """
    w = _setup_eligible(api, "c29")
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]

    stale_version = fixtures.get_account(api, account_id)["version"]
    fixtures.draw_advance(api, account_id, member_id, 1000, idempotency_key="c29-a1")

    resp = api.create_advance(
        account_id,
        th.factories.advance_payload(stale_version, amount_cents=500, idempotency_key="c29-a2"),
        th.make_member_headers(member_id),
    )
    th.validate_error(resp, th.ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412

    advances = fixtures.list_advances(api, account_id)
    assert len(advances) == 1
    account = fixtures.get_account(api, account_id)
    assert account["outstanding_cushion_cents"] == 1000


def test_stale_member_version_on_evaluation_rejected(api):
    """PRD §2.8: "Running an eligibility evaluation for a member requires
    `expected_member_version`, matched against the Member's current `version`,
    because a batch evaluation supersedes the member's current profile and a
    stale view would act on a limit the server has already moved."
    PRD §2.8: "if that value does not match the parent entity's current
    `version` at the time the request is processed, the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
    PRD §3.2: "At most one profile per evaluation mode per member holds the
    status `CURRENT`; creating a batch profile supersedes the prior `CURRENT`
    batch profile to `SUPERSEDED`."

    Design: Corner/cross_cutting_layers/stale_member_version_on_evaluation_rejected
    """
    w = _setup_eligible(api, "c30")
    member_id = w["member"]["id"]
    stale_version = w["member"]["version"]

    resp = api.create_eligibility_evaluation(
        member_id,
        th.factories.evaluation_payload(stale_version, evaluation_mode="BATCH"),
        th.TEST_USERS["program_ops"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412

    batch_profiles = fixtures.list_profiles(api, member_id, params={"evaluation_mode": "BATCH"})
    current = [p for p in batch_profiles if p["status"] == "CURRENT"]
    assert len(current) == 1


def test_stale_run_version_on_resolve_rejected(api):
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
    PRD §2.8: "Resolving a reconciliation run requires `expected_run_version`,
    matched against the ReconciliationRun's current `version`; a stale version
    would post duplicate adjusting entries for a discrepancy already resolved."

    Design: Corner/cross_cutting_layers/stale_run_version_on_resolve_rejected
    """
    member = fixtures.create_member(
        api, external_ref="c31", full_name="C ThirtyOne", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    dep = fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMPC31",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-08-14T00:00:00Z",
        trace_id="c31-t1",
    )
    fixtures.settle_deposit(api, dep["id"])
    run = th.get_success_data(
        api.create_reconciliation_run(
            th.factories.reconciliation_run_payload(
                sponsor_bank_code="SB-1",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
                bank_reported_net_cents=-9000,
            ),
            th.TEST_USERS["sponsor_bank_ops"],
        )
    )
    assert run["status"] == "DISCREPANCY"

    th.get_success_data(
        api.resolve_reconciliation_run(
            run["id"],
            th.factories.run_resolve_payload(run["version"], resolution_note="first resolution"),
            th.TEST_USERS["program_ops"],
        )
    )

    # Replaying the pre-resolution version hits the stale-version check, which
    # outranks the from-state check the already-resolved run would trip.
    resp = api.resolve_reconciliation_run(
        run["id"],
        th.factories.run_resolve_payload(run["version"], resolution_note="duplicate resolution"),
        th.TEST_USERS["program_ops"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412

    adjustments = [
        e
        for e in fixtures.list_ledger_entries(api, account["id"], params={"entry_type": "ADJUSTMENT"})
        if e["reconciliation_run_id"] == run["id"]
    ]
    assert len(adjustments) == 1


def test_idempotent_replay_returns_same_advance(api):
    """PRD §2.9: "Advance creation accepts a client-supplied
    `idempotency_key`. A repeated request that reuses a key with an identical
    payload returns the originally created advance rather than creating a
    second one. Reusing the same key with a different payload is rejected with
    `ERR_IDEMPOTENCY_CONFLICT` (409)."

    Design: Corner/cross_cutting_layers/idempotent_replay_returns_same_advance
    """
    w = _setup_eligible(api, "c32")
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]

    first = fixtures.draw_advance(api, account_id, member_id, 700, idempotency_key="c32-k1")
    account = fixtures.get_account(api, account_id)

    resp = api.create_advance(
        account_id,
        th.factories.advance_payload(account["version"], amount_cents=700, idempotency_key="c32-k1"),
        th.make_member_headers(member_id),
    )
    replay = th.validate_success(resp)
    assert replay["id"] == first["id"]

    advances = fixtures.list_advances(api, account_id)
    assert len(advances) == 1
    after = fixtures.get_account(api, account_id)
    assert after["outstanding_cushion_cents"] == 700


def test_mutation_visible_in_same_response(api):
    """PRD §3.4: "When early posting succeeds, an `EarlyPosting` record is
    created for the deposit in `PROVISIONAL` status — at most one early posting
    ever exists per deposit — with `posted_amount_cents` equal to the deposit's
    full `amount_cents` and a `reversal_window_end` computed as the settlement
    date plus two calendar days; a return arriving before that instant is
    treated as a reversal-risk return of funds already spent."
    PRD §3.1: "The `provisional_early_cents` is the sum of `posted_amount_cents`
    across that account's early postings still in `PROVISIONAL` status — money
    made spendable ahead of settlement."

    Design: Corner/consistency_model/mutation_visible_in_same_response
    """
    w = fixtures.setup_eligible_member(
        api,
        external_ref="c33",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    d3 = fixtures.register_deposit(
        api,
        w["account"]["id"],
        originator_id="EMPC33",
        originator_type="PAYROLL",
        amount_cents=12000,
        settlement_date="2026-09-05T00:00:00Z",
        trace_id="c33-t3",
    )
    resp = api.post_early(d3["id"], {}, th.TEST_USERS["program_ops"])
    posting = th.validate_success(resp, expected_status=200)
    th.assert_early_posting(posting)
    assert posting["status"] == "PROVISIONAL"
    assert posting["posted_amount_cents"] == 12000

    account = fixtures.get_account(api, w["account"]["id"])
    assert account["provisional_early_cents"] == 12000
    assert account["available_optimistic_cents"] == 34000
