"""Depth tests for eligibility scoring variants and the limit ladder."""

import test_helpers as th
from test_helpers import fixtures


def _setup_m2(api):
    """Member with tenure 365d, three settled qualifying deposits, and one
    in-flight qualifying deposit with a future settlement date."""
    member = fixtures.create_member(
        api, external_ref="m2", full_name="M Two", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    for i, date in enumerate(
        ["2026-08-14T00:00:00Z", "2026-08-21T00:00:00Z", "2026-08-28T00:00:00Z"], start=1
    ):
        dep = fixtures.register_deposit(
            api,
            account["id"],
            originator_id="EMP2",
            originator_type="PAYROLL",
            amount_cents=10000,
            settlement_date=date,
            trace_id=f"m2-t{i}",
        )
        fixtures.settle_deposit(api, dep["id"])
    # One in-flight qualifying deposit the batch run must ignore.
    fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMP2",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-09-04T00:00:00Z",
        trace_id="m2-t4",
    )
    return {"member": member, "account": account}


def test_eligibility_score_batch_vs_realtime(api):
    """PRD §3.2: "Batch mode counts only deposits whose status is `SETTLED` with
    `settled_at` inside the window; realtime mode additionally counts in-flight
    deposits in `RECEIVED_FILE` or `POSTED_EARLY` status by their `created_at`,
    so a member with payroll on the wire scores higher in preview than in the
    authoritative batch run."
    PRD §3.2: "Six or more qualifying deposits earn 400 points, four or five earn
    300, two or three earn 150, and fewer than two earn zero."
    PRD §3.2: "The **tenure component**, stored as `tenure_points`, grants up to
    250 points for a full year of tenure: the member's `tenure_days` capped at
    365, divided by 365, multiplied by 250, and rounded half-up to a whole point."

    Design: Difficulty/dual_variant_calc/eligibility_score_batch_vs_realtime
    """
    w = _setup_m2(api)
    member_id = w["member"]["id"]
    batch = fixtures.evaluate(api, member_id, mode="BATCH")
    realtime = fixtures.evaluate(api, member_id, mode="REALTIME")
    th.assert_eligibility_profile(batch)
    th.assert_eligibility_profile(realtime)
    assert batch["score"] == 400, f"BATCH score: {batch}"
    assert realtime["score"] == 550, f"REALTIME score: {realtime}"
    assert realtime["score"] - batch["score"] == 150


def test_realtime_profile_does_not_supersede_batch_or_move_limit(api):
    """PRD §3.2: "Realtime runs are previews: a realtime profile never supersedes
    the batch profile, never creates a limit adjustment, and never moves posture
    — it exists so the member can see what in-flight payroll will do to their
    standing once it settles."

    Design: Difficulty/dual_variant_calc/eligibility_score_batch_vs_realtime
    """
    w = _setup_m2(api)
    member_id = w["member"]["id"]
    batch = fixtures.evaluate(api, member_id, mode="BATCH")
    fixtures.evaluate(api, member_id, mode="REALTIME")

    batch_profiles = fixtures.list_profiles(api, member_id, params={"evaluation_mode": "BATCH"})
    current_batch = [p for p in batch_profiles if p["status"] == "CURRENT"]
    assert len(current_batch) == 1
    assert current_batch[0]["id"] == batch["id"]

    # No limit adjustment beyond the single INCREASE from the batch run.
    adjustments = fixtures.list_limit_adjustments(api, member_id)
    assert len(adjustments) == 1
    assert adjustments[0]["direction"] == "INCREASE"
    member = fixtures.get_member(api, member_id)
    assert member["current_limit_cents"] == batch["computed_limit_cents"] == 2000


def test_ladder_min_of_three_caps(api):
    """PRD §3.2: "Six or more qualifying deposits earn 400 points, four or five
    earn 300, two or three earn 150, and fewer than two earn zero."
    PRD §3.2: "The repayment cap is 20000 cents at five or more consecutive
    on-time repayments, 10000 at three or four, 5000 at one or two, and 2000 at
    zero."
    PRD §3.2: "The computed limit is the minimum of the three caps — a member
    strong on deposits but brand-new to the program is held back by tenure, and
    a tenured member who has never repaid on time is held back by the repayment
    cap."

    Design: Difficulty/combinatorial_formula/ladder_min_of_three_caps
    """
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m3",
        enrolled_at="2026-07-20T00:00:00Z",
        num_deposits=4,
        settlement_dates=[
            "2026-08-05T00:00:00Z",
            "2026-08-12T00:00:00Z",
            "2026-08-19T00:00:00Z",
            "2026-08-26T00:00:00Z",
        ],
    )
    profile = w["profile"]
    # tenure 43d -> tenure_points round_half_up(43/365*250) == 29; bucket 300.
    assert profile["score"] == 329, f"score: {profile}"
    # score_cap 5000, tenure_cap 5000, repay_cap (zero repayments) 2000 binds.
    assert profile["computed_limit_cents"] == 2000, f"limit: {profile}"


def test_ladder_min_of_three_caps_promotes_member_to_eligible(api):
    """PRD §3.2: "The first batch evaluation is what moves a member out of
    `ENROLLED`: when the computed `score` reaches at least 200, the member's
    posture transitions `ENROLLED → ELIGIBLE`, their `current_limit_cents` is
    set to the profile's `computed_limit_cents`, and a `CushionLimitAdjustment`
    recording the change is created."
    PRD §3.3: "An `INCREASE` row is created directly in `EFFECTIVE` status: the
    member's `current_limit_cents` rises to `new_limit_cents` at the moment of
    creation, and `effective_at` is the creation instant."

    Design: Difficulty/combinatorial_formula/ladder_min_of_three_caps
    """
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m3b",
        enrolled_at="2026-07-20T00:00:00Z",
        num_deposits=4,
        settlement_dates=[
            "2026-08-05T00:00:00Z",
            "2026-08-12T00:00:00Z",
            "2026-08-19T00:00:00Z",
            "2026-08-26T00:00:00Z",
        ],
    )
    member = fixtures.get_member(api, w["member"]["id"])
    assert member["status"] == "ELIGIBLE"
    assert member["current_limit_cents"] == 2000
    adjustments = fixtures.list_limit_adjustments(api, member["id"])
    assert len(adjustments) == 1
    adjustment = adjustments[0]
    th.assert_cushion_limit_adjustment(adjustment)
    assert adjustment["direction"] == "INCREASE"
    assert adjustment["status"] == "EFFECTIVE"
    assert adjustment["old_limit_cents"] == 0
    assert adjustment["new_limit_cents"] == 2000
