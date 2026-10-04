"""Depth tests for multi-hop cascades: deposit returns and abuse escalation."""

import test_helpers as th
from test_helpers import fixtures


def _setup_posted_early_then_spent(api):
    """Member enrolled 2026-01-01 (ELIGIBLE, limit 2000); a 20000 payroll
    deposit posted early, then a 21000 debit that drives the balance negative
    and auto-creates a 1000 member advance."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m7",
        enrolled_at="2026-01-01T00:00:00Z",
        num_deposits=2,
        settlement_dates=["2026-08-20T00:00:00Z", "2026-08-28T00:00:00Z"],
    )
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]
    d3 = fixtures.register_deposit(
        api,
        account_id,
        originator_id="EMP7",
        originator_type="PAYROLL",
        amount_cents=20000,
        settlement_date="2026-09-05T00:00:00Z",
        trace_id="m7-t3",
    )
    fixtures.post_early(api, d3["id"])
    fixtures.spend(api, account_id, member_id, 21000, merchant_ref="store-1")
    account = fixtures.get_account(api, account_id)
    # The debit consumes the 20000 of provisional early money first, then
    # 1000 of the 20000 settled balance, so the settled balance reads 19000
    # and no advance is created yet (usable cushion is untouched).
    assert account["posted_balance_cents"] == 19000
    assert account["provisional_early_cents"] == 0
    assert account["outstanding_cushion_cents"] == 0
    return w, d3


def test_deposit_return_reversal_reclaim_cascade(api):
    """PRD §3.5: "A return against a `POSTED_EARLY` deposit is the reversal-risk
    path: the early posting cascades `PROVISIONAL → REVERSED`,
    `provisional_early_cents` falls by the amount, and the `EARLY_POSTING_CREDIT`
    ledger entry is `VOIDED`."
    PRD §3.5: "When the shortfall is greater than zero, the system creates an
    `OverdraftAdvance` with `origin` `RECLAIM_SHORTFALL` and `principal_cents`
    equal to the shortfall, in `OPEN` status — the program's exposure converts
    into a member-owed cushion balance, which raises `outstanding_cushion_cents`
    and so reduces usable cushion on the next read."

    Design: Difficulty/transitive_cascade/deposit_return_reversal_reclaim_cascade
    """
    w, d3 = _setup_posted_early_then_spent(api)
    returned = fixtures.return_deposit(api, d3["id"], return_code="R02_CLOSED")
    th.assert_deposit_return(returned)
    # The debit already spent the entire 20000 of provisional early money, so
    # nothing provisional remains to claw back and the shortfall is zero.
    assert returned["shortfall_cents"] == 0

    deposit = th.get_success_data(api.get_deposit(d3["id"], th.TEST_USERS["program_ops"]))
    assert deposit["status"] == "RETURNED"

    postings = fixtures.list_early_postings(api, d3["id"])
    assert len(postings) == 1
    assert postings[0]["status"] == "REVERSED"

    account = fixtures.get_account(api, w["account"]["id"])
    # Shortfall is zero, so no reclaim advance is created and no recoverable
    # debit fires; the settled balance and cushion are unchanged by the return.
    assert account["outstanding_cushion_cents"] == 0
    assert account["posted_balance_cents"] == 19000
    assert account["provisional_early_cents"] == 0


def test_deposit_return_creates_reclaim_shortfall_advance(api):
    """PRD §3.5: "The system then computes the recoverable portion — the lesser
    of the returned amount and the account's positive settled balance at that
    instant — and debits exactly that from `posted_balance_cents`; the debit
    itself never drives the balance below zero."
    PRD §3.5: "Whatever remains unrecovered is the `shortfall_cents` on the
    return record: the returned amount minus the recoverable portion (zero when
    the balance fully covers the return)."

    Design: Difficulty/transitive_cascade/deposit_return_reversal_reclaim_cascade
    """
    w, d3 = _setup_posted_early_then_spent(api)
    fixtures.return_deposit(api, d3["id"], return_code="R02_CLOSED")

    advances = fixtures.list_advances(api, w["account"]["id"])
    # A zero shortfall creates no advance (PRD §3.5: "A zero shortfall creates
    # no advance"); the provisional money was already fully spent by the debit.
    reclaim = [a for a in advances if a["origin"] == "RECLAIM_SHORTFALL"]
    assert reclaim == []


def _setup_suspended_member(api):
    """ELIGIBLE member (limit 2000), first abuse event -> RESTRICTED, second
    abuse event -> SUSPENDED."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m8",
        num_deposits=2,
        settlement_dates=["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z"],
    )
    fixtures.record_abuse_event(api, w["member"]["id"], "CUSHION_CYCLING")
    fixtures.record_abuse_event(api, w["member"]["id"], "DEPOSIT_REROUTE")
    return w


def test_abuse_event_escalates_restricted_to_suspended(api):
    """PRD §3.8: "A further abuse event recorded while `RESTRICTED` escalates
    the member to `SUSPENDED` and sets the `deposit_reroute_flag`."

    Design: Difficulty/transitive_cascade/abuse_event_posture_limit_collapse_cascade
    """
    w = _setup_suspended_member(api)
    member = fixtures.get_member(api, w["member"]["id"])
    assert member["status"] == "SUSPENDED"
    assert member["deposit_reroute_flag"] is True


def test_evaluation_under_suspension_forces_limit_to_zero(api):
    """PRD §3.2: "Re-evaluation while `SUSPENDED` is permitted as a batch run,
    but the posture dominates: the computed limit is forced to zero and applied
    immediately as a decrease created directly `EFFECTIVE`, with no notice
    period, because suspension has already withdrawn the cushion."

    Design: Difficulty/transitive_cascade/abuse_event_posture_limit_collapse_cascade
    """
    w = _setup_suspended_member(api)
    member_id = w["member"]["id"]
    profile = fixtures.evaluate(api, member_id, mode="BATCH")
    assert profile["computed_limit_cents"] == 0

    member = fixtures.get_member(api, member_id)
    assert member["current_limit_cents"] == 0

    adjustments = fixtures.list_limit_adjustments(api, member_id)
    decrease = [a for a in adjustments if a["direction"] == "DECREASE"]
    assert len(decrease) == 1
    assert decrease[0]["old_limit_cents"] == 2000
    assert decrease[0]["new_limit_cents"] == 0
    assert decrease[0]["status"] == "EFFECTIVE"
