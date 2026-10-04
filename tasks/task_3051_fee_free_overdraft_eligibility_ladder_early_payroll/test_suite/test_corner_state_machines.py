"""Breadth tests for state-machine preconditions, invalid transitions, and
terminal lockdown."""

import test_helpers as th
from test_helpers import fixtures


def test_settle_before_settlement_date_rejected(api):
    """PRD §3.4: "Settlement is performed by `SponsorBankOps` on or after the
    settlement date; settling before the date is `ERR_TEMPORAL_VIOLATION`, and
    settling a deposit that is not in `RECEIVED_FILE` or `POSTED_EARLY` is
    `ERR_INVALID_STATE` (or `ERR_ALREADY_TERMINAL` once `RETURNED`)."

    Design: Corner/state_machines/settle_before_settlement_date_rejected
    """
    member = fixtures.create_member(
        api, external_ref="c6", full_name="C Six", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    dep = fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMPC6",
        amount_cents=10000,
        settlement_date="2026-09-10T00:00:00Z",
        trace_id="c6-t1",
    )
    resp = api.settle_deposit(dep["id"], {}, th.TEST_USERS["sponsor_bank_ops"])
    th.validate_error(resp, th.ApiErrorId.ERR_TEMPORAL_VIOLATION)
    assert resp.status_code == 422

    deposit = th.get_success_data(api.get_deposit(dep["id"], th.TEST_USERS["program_ops"]))
    assert deposit["status"] == "RECEIVED_FILE"


def test_double_settle_returns_invalid_state(api):
    """PRD §3.4: "Settlement is performed by `SponsorBankOps` on or after the
    settlement date; settling before the date is `ERR_TEMPORAL_VIOLATION`, and
    settling a deposit that is not in `RECEIVED_FILE` or `POSTED_EARLY` is
    `ERR_INVALID_STATE` (or `ERR_ALREADY_TERMINAL` once `RETURNED`)."

    Design: Corner/state_machines/double_settle_returns_invalid_state
    """
    member = fixtures.create_member(
        api, external_ref="c7", full_name="C Seven", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    dep = fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMPC7",
        amount_cents=10000,
        settlement_date="2026-08-14T00:00:00Z",
        trace_id="c7-t1",
    )
    fixtures.settle_deposit(api, dep["id"])

    resp = api.settle_deposit(dep["id"], {}, th.TEST_USERS["sponsor_bank_ops"])
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    account_after = fixtures.get_account(api, account["id"])
    assert account_after["posted_balance_cents"] == 10000


def test_return_received_file_rejected(api):
    """PRD §3.5: "A return processed by `SponsorBankOps` — naming a
    `return_code` of `R01_INSUFFICIENT`, `R02_CLOSED`, `R03_NO_ACCOUNT`,
    `R07_REVOKED`, or `R08_STOPPED` — moves a deposit to the terminal
    `RETURNED` state, and a `DepositReturn` record is persisted with the
    deposit's full amount as its `amount_cents` (returns are full-amount
    only)."
    PRD §3.5: "A return against a `POSTED_EARLY` deposit is the reversal-risk
    path: the early posting cascades `PROVISIONAL → REVERSED`,
    `provisional_early_cents` falls by the amount, and the
    `EARLY_POSTING_CREDIT` ledger entry is `VOIDED`."

    Design: Corner/state_machines/return_received_file_rejected
    """
    member = fixtures.create_member(
        api, external_ref="c8", full_name="C Eight", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    dep = fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMPC8",
        amount_cents=10000,
        settlement_date="2026-08-14T00:00:00Z",
        trace_id="c8-t1",
    )
    # The deposit is still RECEIVED_FILE: return is only legal from
    # POSTED_EARLY or SETTLED.
    resp = api.return_deposit(
        dep["id"], th.factories.deposit_return_payload(), th.TEST_USERS["sponsor_bank_ops"]
    )
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    assert fixtures.list_returns(api, dep["id"]) == []


def _setup_open_advance(api, ref, idem_key):
    w = fixtures.setup_eligible_member(
        api,
        external_ref=ref,
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    adv = fixtures.draw_advance(
        api, w["account"]["id"], w["member"]["id"], 1000, idempotency_key=idem_key
    )
    return w, adv


def test_write_off_before_aging_rejected(api):
    """PRD §3.6: "An advance aged sixty days or more may be written off by
    `ProgramOps`, who supply a `reason`; writing off before the advance is
    sixty days old is `ERR_TEMPORAL_VIOLATION`, and writing off an advance
    already `REPAID` or `WRITTEN_OFF` is `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/write_off_before_aging_rejected
    """
    _w, adv = _setup_open_advance(api, "c9", "c9-a1")
    resp = api.write_off_advance(
        adv["id"], th.factories.write_off_payload(reason="too early"), th.TEST_USERS["program_ops"]
    )
    th.validate_error(resp, th.ApiErrorId.ERR_TEMPORAL_VIOLATION)
    assert resp.status_code == 422

    current = th.get_success_data(api.get_advance(adv["id"], th.TEST_USERS["program_ops"]))
    assert current["status"] == "OPEN"


def test_write_off_after_aging_resets_repayment_streak(api):
    """PRD §3.6: "An advance aged sixty days or more may be written off by
    `ProgramOps`, who supply a `reason`; writing off before the advance is
    sixty days old is `ERR_TEMPORAL_VIOLATION`, and writing off an advance
    already `REPAID` or `WRITTEN_OFF` is `ERR_ALREADY_TERMINAL`."
    PRD §3.6: "Write-off moves the advance to `WRITTEN_OFF`, recognizes the
    outstanding as program loss by removing it from `outstanding_cushion_cents`,
    and resets the member's `consecutive_on_time_repayments` to zero."

    Design: Corner/state_machines/write_off_after_aging_resets_repayment_streak
    """
    w, adv = _setup_open_advance(api, "c10", "c10-a1")
    fixtures.set_clock(api, "2026-11-15T00:00:00Z")

    resp = api.write_off_advance(
        adv["id"], th.factories.write_off_payload(reason="aged 75 days"), th.TEST_USERS["program_ops"]
    )
    updated = th.validate_success(resp, expected_status=200)
    assert updated["status"] == "WRITTEN_OFF"

    member = fixtures.get_member(api, w["member"]["id"])
    assert member["consecutive_on_time_repayments"] == 0
    account = fixtures.get_account(api, w["account"]["id"])
    assert account["outstanding_cushion_cents"] == 0


def test_notify_on_effective_adjustment_rejected(api):
    """PRD §3.3: "A `ProgramOps` operator records that the member has been
    notified by issuing the notify action, moving the row `PENDING_NOTICE →
    NOTIFIED` and stamping `notified_at`; notifying a row not in
    `PENDING_NOTICE` is refused with `ERR_INVALID_STATE`."
    PRD §3.3: "An `INCREASE` row is created directly in `EFFECTIVE` status: the
    member's `current_limit_cents` rises to `new_limit_cents` at the moment of
    creation, and `effective_at` is the creation instant."

    Design: Corner/state_machines/notify_on_effective_adjustment_rejected
    """
    w = fixtures.setup_eligible_member(
        api,
        external_ref="c11",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    adjustments = fixtures.list_limit_adjustments(api, w["member"]["id"])
    assert len(adjustments) == 1
    adjustment = adjustments[0]
    assert adjustment["status"] == "EFFECTIVE"
    assert adjustment["direction"] == "INCREASE"

    resp = api.notify_limit_adjustment(adjustment["id"], {}, th.TEST_USERS["program_ops"])
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409


def test_resolve_balanced_run_rejected(api):
    """PRD §3.7: "A discrepancy of exactly zero moves the run `OPEN → BALANCED`
    immediately and automatically; anything non-zero moves it `OPEN →
    DISCREPANCY`, which freezes early posting for every account of that sponsor
    bank whose window contains the current clock until resolution."
    PRD §3.7: "Resolution is a `ProgramOps` action carrying
    `expected_run_version` for concurrency and a `resolution_note`, permitted
    only while the run is in `DISCREPANCY` — resolving a `BALANCED` or
    already-`RESOLVED` run is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/resolve_balanced_run_rejected
    """
    run = th.get_success_data(
        api.create_reconciliation_run(
            th.factories.reconciliation_run_payload(
                sponsor_bank_code="SB-9",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-08T00:00:00Z",
                bank_reported_net_cents=0,
            ),
            th.TEST_USERS["sponsor_bank_ops"],
        )
    )
    assert run["status"] == "BALANCED"

    resp = api.resolve_reconciliation_run(
        run["id"],
        th.factories.run_resolve_payload(run["version"], resolution_note="nothing to resolve"),
        th.TEST_USERS["program_ops"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409


def _setup_dispute_under_review(api, ref="c12"):
    w = fixtures.setup_eligible_member(
        api,
        external_ref=ref,
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]
    d3 = fixtures.register_deposit(
        api,
        account_id,
        originator_id=f"EMP{ref.upper()}",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-09-04T00:00:00Z",
        trace_id=f"{ref}-t3",
    )
    fixtures.post_early(api, d3["id"])
    fixtures.return_deposit(api, d3["id"])
    dispute = th.get_success_data(
        api.create_dispute(
            th.factories.dispute_payload(
                d3["id"],
                dispute_type="DEPOSIT_RETURN_CLAIM",
                amount_cents=3000,
                statement="dispute",
            ),
            th.make_member_headers(member_id),
        )
    )
    th.get_success_data(
        api.issue_provisional_credit(dispute["id"], {}, th.TEST_USERS["disputes_agent"])
    )
    return w, dispute


def test_dispute_resolve_beyond_deadline_rejected(api):
    """PRD §3.9: "Resolution, also by a `DisputesAgent` and carrying an
    `outcome` of `MEMBER` or `BANK` plus a `resolution_note`, must occur no
    later than `resolution_due_at`; acting on a dispute already in
    `RESOLVED_MEMBER` or `RESOLVED_BANK` is `ERR_ALREADY_TERMINAL`."
    PRD §3.9: "Filing creates the dispute with `case_status` `FILED` and
    `provisional_status` `NONE`, and computes two deadlines from the filing
    instant: `provisional_due_at`, ten business days out (calendar days are
    advanced one at a time, skipping Saturdays and Sundays; no holiday calendar
    is observed), and `resolution_due_at`, forty-five calendar days out."

    Design: Corner/state_machines/dispute_resolve_beyond_deadline_rejected
    """
    _w, dispute = _setup_dispute_under_review(api)
    fixtures.set_clock(api, "2026-10-20T00:00:00Z")  # 49 days after filing

    resp = api.resolve_dispute(
        dispute["id"],
        th.factories.dispute_resolve_payload(outcome="MEMBER", resolution_note="late resolution"),
        th.TEST_USERS["disputes_agent"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_TEMPORAL_VIOLATION)
    assert resp.status_code == 422

    current = th.get_success_data(api.get_dispute(dispute["id"], th.TEST_USERS["disputes_agent"]))
    assert current["case_status"] == "UNDER_REVIEW"
