"""Breadth tests for entity creation, required fields, uniqueness and reads."""

import test_helpers as th
from test_helpers import fixtures


def test_member_creation_persists_fields(api):
    """PRD §3.1: "The new member is created in the `ENROLLED` posture with a
    `current_limit_cents` of zero, meaning no cushion until the first
    evaluation."
    PRD §2.4: "Each has an `id`, a server-minted UUID with no type prefix. Each
    carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits
    recording creation, and `updated_at`, the same format, refreshed on every
    mutation. Each also carries `version`, an integer starting at 1 that
    increments by exactly 1 on every mutation of that resource; `version` is
    the basis of the optimistic concurrency control described in §2.8."

    Design: Corner/entities/member_creation_persists_fields
    """
    resp = api.create_member(
        th.factories.member_payload(
            external_ref="c1", full_name="C One", enrolled_at="2026-01-01T00:00:00Z"
        ),
        th.TEST_USERS["program_ops"],
    )
    member = th.validate_success(resp, expected_status=201)
    th.assert_member(member)
    assert member["status"] == "ENROLLED"
    assert member["current_limit_cents"] == 0
    assert member["consecutive_on_time_repayments"] == 0
    assert member["version"] == 1


def test_member_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: "A member's life in the program begins when a `ProgramOps`
    operator enrolls them by supplying an `external_ref` — a client-side unique
    reference, one to 128 characters, unique across all members — together with
    the member's `full_name` and an `enrolled_at` timestamp that anchors
    tenure; the enrollment timestamp must not lie in the future relative to the
    logical clock."

    Design: Corner/entities/member_missing_required_field_returns_invalid_request
    """
    resp = api.create_member(
        {"external_ref": "c2", "enrolled_at": "2026-01-01T00:00:00Z"},
        th.TEST_USERS["program_ops"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400

    _data, meta = th.validate_paginated(api.list_members(th.TEST_USERS["program_ops"]))
    assert meta["total_count"] == 0


def test_member_duplicate_external_ref_returns_duplicate(api):
    """PRD §3.1: "A second enrollment reusing an existing `external_ref` is
    refused with `ERR_DUPLICATE`."

    Design: Corner/entities/member_duplicate_external_ref_returns_duplicate
    """
    resp = api.create_member(
        th.factories.member_payload(
            external_ref="dup-1", full_name="C Three", enrolled_at="2026-01-01T00:00:00Z"
        ),
        th.TEST_USERS["program_ops"],
    )
    th.validate_success(resp, expected_status=201)

    resp = api.create_member(
        th.factories.member_payload(
            external_ref="dup-1", full_name="C Three Clone", enrolled_at="2026-02-01T00:00:00Z"
        ),
        th.TEST_USERS["program_ops"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_DUPLICATE)
    assert resp.status_code == 409


def test_deposit_account_savings_excluded_from_cushion(api):
    """PRD §3.1: "Only `SPENDING` accounts participate in the cushion program:
    an advance requested against a `SAVINGS` account is rejected with
    `ERR_LIMIT_EXCEEDED`, regardless of the member's limit."

    Design: Corner/entities/deposit_account_savings_excluded_from_cushion
    """
    w = fixtures.setup_eligible_member(
        api,
        external_ref="c4",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    savings = fixtures.open_account(api, w["member"]["id"], account_type="SAVINGS")
    member = fixtures.get_member(api, w["member"]["id"])
    assert member["status"] == "ELIGIBLE"
    resp = api.create_advance(
        savings["id"],
        th.factories.advance_payload(savings["version"], amount_cents=500, idempotency_key="c4-sav-adv"),
        th.make_member_headers(w["member"]["id"]),
    )
    th.validate_error(resp, th.ApiErrorId.ERR_LIMIT_EXCEEDED)
    assert resp.status_code == 422


def test_ledger_entry_reverse_reachability_by_account(api):
    """PRD §3.4: "Settlement from `RECEIVED_FILE` credits the full
    `amount_cents` to `posted_balance_cents`, stamps `settled_at` with the
    current clock — `settled_at` is null until this moment and drives the batch
    scoring window thereafter — runs the repayment waterfall against the
    just-credited funds, reduces the balance by the total allocated to
    repayment, and writes a `DEPOSIT_SETTLEMENT` ledger entry in `SETTLED`
    status."
    PRD §2.7: "Each entry carries an `entry_type` drawn from exactly nine values
    — `ADVANCE_CREDIT`, `ADVANCE_REPAYMENT_DEBIT`, `EARLY_POSTING_CREDIT`,
    `EARLY_POSTING_REVERSAL`, `DEPOSIT_SETTLEMENT`, `DEPOSIT_RETURN_DEBIT`,
    `PROVISIONAL_CREDIT`, `PROVISIONAL_REVERSAL`, and `ADJUSTMENT` — together
    with two signed legs: `program_leg_cents` (credit positive from the
    program's perspective) and `bank_leg_cents` (the bank-side mirror)."

    Design: Corner/entities/ledger_entry_reverse_reachability_by_account
    """
    member = fixtures.create_member(
        api, external_ref="c5", full_name="C Five", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    dep = fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMPC5",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-08-14T00:00:00Z",
        trace_id="c5-t1",
    )
    fixtures.settle_deposit(api, dep["id"])

    entries = fixtures.list_ledger_entries(api, account["id"])
    assert len(entries) == 1
    entry = entries[0]
    th.assert_ledger_entry(entry)
    assert entry["entry_type"] == "DEPOSIT_SETTLEMENT"
    assert entry["program_leg_cents"] == 10000
    assert entry["bank_leg_cents"] == -10000


def test_entity_not_found_returns_404(api):
    """PRD §2.5: "A request that references a child under the wrong parent — for
    example, an account id that exists but belongs to a different member — is
    reported as the child being not found: the response is `ERR_NOT_FOUND`
    (404) naming the deepest unresolved resource, never a permission error and
    never the parent's error."

    Design: Corner/entities/entity_not_found_returns_404
    """
    resp = api.get_member(th.constants.MISSING_UUID, th.TEST_USERS["program_ops"])
    th.validate_error(resp, th.ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
