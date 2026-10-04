"""Breadth tests for the scoring, waterfall, and deadline calculations."""

import test_helpers as th
from test_helpers import fixtures


def _setup_settled_then_returned(api):
    """Member with tenure 365d; three qualifying deposits settled and a fourth
    qualifying deposit settled then returned."""
    member = fixtures.create_member(
        api, external_ref="c13", full_name="C Thirteen", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    deposits = []
    for i, date in enumerate(
        [
            "2026-08-07T00:00:00Z",
            "2026-08-14T00:00:00Z",
            "2026-08-21T00:00:00Z",
            "2026-08-28T00:00:00Z",
        ],
        start=1,
    ):
        dep = fixtures.register_deposit(
            api,
            account["id"],
            originator_id="EMPC13",
            originator_type="PAYROLL",
            amount_cents=10000,
            settlement_date=date,
            trace_id=f"c13-t{i}",
        )
        fixtures.settle_deposit(api, dep["id"])
        deposits.append(dep)
    fixtures.return_deposit(api, deposits[3]["id"], return_code="R03_NO_ACCOUNT")
    return {"member": member, "account": account, "deposits": deposits}


def test_score_bucket_demotion_on_returned_deposit(api):
    """PRD §3.2: "If any qualifying deposit settled inside the window was
    subsequently returned — settled first, then `RETURNED` — the bucket is
    demoted one step: 400 becomes 300, 300 becomes 150, and 150 becomes zero."

    Design: Corner/calculations/score_bucket_demotion_on_returned_deposit
    """
    w = _setup_settled_then_returned(api)
    profile = fixtures.evaluate(api, w["member"]["id"], mode="BATCH")
    # n == 3 settled -> bucket 150, demoted one step to 0 by the return.
    assert profile["regularity_points"] == 0, f"profile: {profile}"
    assert profile["tenure_points"] == 250
    assert profile["score"] == 250


def test_returned_deposit_excluded_from_bucket_count(api):
    """PRD §3.5: "One further consequence matters for scoring: a deposit settled
    and then returned no longer counts as a qualifying settled deposit in
    future batch evaluations — it becomes the demotion input for the regularity
    bucket described in §3.2."

    Design: Corner/calculations/score_bucket_demotion_on_returned_deposit
    """
    w = _setup_settled_then_returned(api)
    deposit = th.get_success_data(
        api.get_deposit(w["deposits"][3]["id"], th.TEST_USERS["program_ops"])
    )
    assert deposit["status"] == "RETURNED"

    profile = fixtures.evaluate(api, w["member"]["id"], mode="BATCH")
    # Without the exclusion the four deposits would earn bucket 300 (then
    # demoted to 150); with it, n == 3 earns 150 demoted to 0.
    assert profile["regularity_points"] == 0
    assert profile["score"] == 250


def _setup_c14(api):
    """Member with six settled qualifying deposits, one on-time repayment cycle
    pushing the limit to 5000, then four of the seed deposits returned."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="c14",
        num_deposits=6,
        settlement_dates=[
            "2026-08-05T00:00:00Z",
            "2026-08-12T00:00:00Z",
            "2026-08-19T00:00:00Z",
            "2026-08-26T00:00:00Z",
            "2026-08-29T00:00:00Z",
            "2026-08-31T00:00:00Z",
        ],
    )
    account_id = w["account"]["id"]
    member_id = w["member"]["id"]
    fixtures.draw_advance(api, account_id, member_id, 2000, idempotency_key="c14-seed")
    fixtures.repay_with_qualifying_deposit(
        api, account_id, "EMPC14", settlement_date="2026-09-01T00:00:00Z", trace_suffix="t7"
    )
    profile2 = fixtures.evaluate(api, member_id, mode="BATCH")
    for i in (2, 3, 4, 5):
        fixtures.return_deposit(api, w["deposits"][i]["id"])
    return w, profile2


def test_ladder_decrease_notice_period_then_effective(api):
    """PRD §3.3: "A `DECREASE` row is created in `PENDING_NOTICE` with
    `effective_at` set to seven days after creation — a one-week member-notice
    period during which the old, higher limit continues to govern spending
    power."

    Design: Corner/calculations/ladder_decrease_notice_period_then_effective
    """
    w, profile2 = _setup_c14(api)
    member_id = w["member"]["id"]
    assert profile2["computed_limit_cents"] == 5000, f"second profile: {profile2}"

    profile3 = fixtures.evaluate(api, member_id, mode="BATCH")
    assert profile3["computed_limit_cents"] == 2000, f"third profile: {profile3}"

    member = fixtures.get_member(api, member_id)
    assert member["current_limit_cents"] == 5000


def _seven_days_later(instant: str) -> str:
    from datetime import datetime, timedelta, timezone

    dt = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    shifted = dt + timedelta(days=7)
    return shifted.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_ladder_decrease_created_pending_notice(api):
    """PRD §3.3: "Increases and decreases are deliberately asymmetric. An
    `INCREASE` row is created directly in `EFFECTIVE` status: the member's
    `current_limit_cents` rises to `new_limit_cents` at the moment of creation,
    and `effective_at` is the creation instant."
    PRD §3.3: "A `DECREASE` row is created in `PENDING_NOTICE` with
    `effective_at` set to seven days after creation — a one-week member-notice
    period during which the old, higher limit continues to govern spending
    power."

    Design: Corner/calculations/ladder_decrease_notice_period_then_effective
    """
    w, _profile2 = _setup_c14(api)
    member_id = w["member"]["id"]
    fixtures.evaluate(api, member_id, mode="BATCH")

    adjustments = fixtures.list_limit_adjustments(api, member_id)
    decreases = [a for a in adjustments if a["direction"] == "DECREASE"]
    assert len(decreases) == 1
    decrease = decreases[0]
    assert decrease["old_limit_cents"] == 5000
    assert decrease["new_limit_cents"] == 2000
    assert decrease["status"] == "PENDING_NOTICE"

    # effective_at is exactly seven days after the adjustment was created.
    assert _seven_days_later(decrease["created_at"]).startswith(
        decrease["effective_at"].split(".")[0].rstrip("Z")
    ), f"effective_at {decrease['effective_at']} != created_at + 7d {decrease['created_at']}"


def test_abuse_penalty_capped_at_three_events(api):
    """PRD §3.2: "The **abuse penalty**, stored as `abuse_penalty`, subtracts
    150 points for each abuse event recorded against the member within the
    trailing ninety days, counting at most three events."
    PRD §3.2: "The final `score` is the sum of the three positive components
    minus the abuse penalty, clamped to the range 0 to 1000."
    PRD §3.2: "A batch evaluation scoring below 200 leaves the member
    `ENROLLED` with a zero limit; no adjustment row is created when the limit
    delta is flat."

    Design: Corner/calculations/abuse_penalty_capped_at_three_events
    """
    member = fixtures.create_member(
        api, external_ref="c16", full_name="C Sixteen", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    dep = fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMPC16",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-08-14T00:00:00Z",
        trace_id="c16-t1",
    )
    fixtures.settle_deposit(api, dep["id"])
    fixtures.record_abuse_event(api, member["id"], "CUSHION_CYCLING")
    fixtures.record_abuse_event(api, member["id"], "CUSHION_CYCLING")
    fixtures.record_abuse_event(api, member["id"], "FIRST_PARTY_FRAUD")

    profile = fixtures.evaluate(api, member["id"], mode="BATCH")
    assert profile["abuse_penalty"] == 450, f"profile: {profile}"
    assert profile["score"] == 0

    current = fixtures.get_member(api, member["id"])
    assert current["status"] == "ENROLLED"


def test_dispute_deadline_business_day_math(api):
    """PRD §3.9: "Filing creates the dispute with `case_status` `FILED` and
    `provisional_status` `NONE`, and computes two deadlines from the filing
    instant: `provisional_due_at`, ten business days out (calendar days are
    advanced one at a time, skipping Saturdays and Sundays; no holiday calendar
    is observed), and `resolution_due_at`, forty-five calendar days out."

    Design: Corner/calculations/dispute_deadline_business_day_math
    """
    fixtures.set_clock(api, "2026-08-28T12:00:00Z")  # a Friday
    w = fixtures.setup_eligible_member(
        api,
        external_ref="c17",
        num_deposits=2,
        settlement_dates=["2026-08-20T00:00:00Z", "2026-08-26T00:00:00Z"],
    )
    d3 = fixtures.register_deposit(
        api,
        w["account"]["id"],
        originator_id="EMPC17",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-09-02T00:00:00Z",
        trace_id="c17-t3",
    )
    fixtures.post_early(api, d3["id"])
    dispute = th.get_success_data(
        api.create_dispute(
            th.factories.dispute_payload(
                d3["id"],
                dispute_type="EARLY_POSTING_REVERSAL",
                amount_cents=1000,
                statement="deadline check",
            ),
            th.make_member_headers(w["member"]["id"]),
        )
    )
    th.assert_dispute(dispute)
    # Ten business days from Friday 2026-08-28 12:00 (weekend Sep 5-6 skipped).
    assert dispute["provisional_due_at"].startswith("2026-09-11T12:00:00"), (
        f"provisional_due_at: {dispute['provisional_due_at']}"
    )
    # Forty-five calendar days out.
    assert dispute["resolution_due_at"].startswith("2026-10-12T12:00:00"), (
        f"resolution_due_at: {dispute['resolution_due_at']}"
    )
