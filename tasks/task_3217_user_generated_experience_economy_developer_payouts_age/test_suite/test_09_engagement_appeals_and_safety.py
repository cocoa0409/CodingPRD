"""Engagement payouts and monthly settlement, moderation appeals, and the
safety-report-to-termination cascade (PRD §3.5, §3.8, §3.10, §3.11)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_engagement_snapshot,
    create_engagement_snapshot_payload,
    create_experience,
    create_moderation_appeal_payload,
    create_published_experience,
    create_user,
    expected_engagement_payout,
    get_user,
    make_creator_headers,
    make_safety_agent_headers,
    report_message,
    send_chat,
    set_clock,
    setup_devex_eligible_user,
    submit_devex_request,
    submit_experience_queued,
    triage_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestEngagementSettlement:
    def test_engagement_payout_provisional_vs_settled(self, api):
        """PRD §3.8: "The monthly settlement — run by a `PlatformAdmin` through the
        settlement capability — walks every `PUBLISHED` experience, credits its
        `engagement_payout_pending_robux` into the creator's `earned_robux_lifetime`,
        resets the pending counter to zero, and reports how many experiences settled
        and the total Robux credited."
        PRD §3.8: "the minutes are converted to whole hours (any partial hour
        discarded) and multiplied by the per-hour rate for the rating — 2 Robux per
        hour for `ALL`, 3 for `NINE_PLUS`, 4 for `THIRTEEN_PLUS`, and 5 for
        `SEVENTEEN_PLUS`."

        Design: Difficulty/dual_variant_calc/engagement_payout_provisional_vs_settled
        """
        set_clock()
        creator = create_user(username="cr_a", email="cr_a@x.com", date_of_birth="1990-01-01")
        exp, _sub = create_published_experience(creator["id"], title="My World")
        rating = exp["age_rating"]
        expected_payout = expected_engagement_payout(3600, rating)

        snap = validate_success(
            api.post_engagement_snapshot(
                exp["id"],
                create_engagement_snapshot_payload("2026-09-15", 3600),
                ADMIN,
            ),
            201,
        )
        assert_engagement_snapshot(snap)
        # 3600 minutes = 60 whole hours; payout is 60 * the rating's per-hour rate.
        assert snap["payout_robux"] == expected_payout, (
            f"60 hours at the {rating} rate must pay {expected_payout}, got {snap['payout_robux']}"
        )

        exp_mid = validate_success(api.get_experience(exp["id"], ADMIN), 200)
        assert exp_mid["engagement_payout_pending_robux"] == expected_payout
        assert get_user(creator["id"])["earned_robux_lifetime"] == 0, (
            "the provisional daily accrual must not commit into lifetime earnings"
        )

        result = validate_success(api.settle_monthly_engagement(ADMIN), 200)
        assert result["total_robux_credited"] == expected_payout
        exp_after = validate_success(api.get_experience(exp["id"], ADMIN), 200)
        assert exp_after["engagement_payout_pending_robux"] == 0, (
            "settlement must reset the pending counter to zero"
        )
        assert get_user(creator["id"])["earned_robux_lifetime"] == expected_payout

    def test_engagement_pending_accumulates_until_settlement(self, api):
        """PRD §3.8: "A daily engagement sweep — driven by a `PlatformAdmin` posting an
        `EngagementSnapshot` with a `snapshot_date` and the day's `minutes_engaged` —
        computes that day's `payout_robux` for the experience and adds it to the
        experience's `engagement_payout_pending_robux`."
        PRD §3.8: "A mid-month creator-dashboard view may show a provisional estimate —
        whole hours of the minutes so far times the rating's rate — but that estimate
        commits nothing; only the settlement moves money."

        Design: Difficulty/dual_variant_calc/engagement_payout_provisional_vs_settled
        """
        set_clock()
        creator = create_user(username="cr_a2", email="cr_a2@x.com", date_of_birth="1990-01-01")
        exp, _sub = create_published_experience(creator["id"], title="My World Two")
        rating = exp["age_rating"]
        p1 = expected_engagement_payout(3600, rating)  # 60 hours
        p2 = expected_engagement_payout(1800, rating)  # 30 hours

        validate_success(
            api.post_engagement_snapshot(
                exp["id"], create_engagement_snapshot_payload("2026-09-10", 3600), ADMIN
            ),
            201,
        )
        validate_success(
            api.post_engagement_snapshot(
                exp["id"], create_engagement_snapshot_payload("2026-09-11", 1800), ADMIN
            ),
            201,
        )

        exp_mid = validate_success(api.get_experience(exp["id"], ADMIN), 200)
        assert exp_mid["engagement_payout_pending_robux"] == p1 + p2, (
            f"pending must accumulate {p1}+{p2}={p1 + p2}, got "
            f"{exp_mid['engagement_payout_pending_robux']}"
        )
        assert get_user(creator["id"])["earned_robux_lifetime"] == 0

        validate_success(api.settle_monthly_engagement(ADMIN), 200)
        exp_after = validate_success(api.get_experience(exp["id"], ADMIN), 200)
        assert exp_after["engagement_payout_pending_robux"] == 0
        assert get_user(creator["id"])["earned_robux_lifetime"] == p1 + p2


class TestAppealGate:
    def test_appeal_against_non_rejected_submission_returns_submission_not_rejected(self, api, platform_admin_headers):
        """PRD §3.5: "The appeal is only admissible while the target submission is
        `REJECTED`; filing against a submission in any other state is rejected with
        `ERR_SUBMISSION_NOT_REJECTED`."

        Design: Corner/errors/appeal_against_non_rejected_submission_returns_submission_not_rejected
        """
        set_clock()
        creator = create_user(username="cr_ap", email="cr_ap@x.com", date_of_birth="1990-01-01")
        exp = create_experience(creator["id"], title="Appeal Target")
        sub = submit_experience_queued(creator["id"], exp["id"])
        validate_success(api.inject_moderation_score(sub["id"], 0.05, platform_admin_headers), 200)
        approved = validate_success(
            api.get_moderation_submission(sub["id"], platform_admin_headers), 200
        )
        assert approved["status"] == "APPROVED"

        resp = api.create_moderation_appeal(
            create_moderation_appeal_payload(sub["id"]),
            make_creator_headers(creator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_NOT_REJECTED)
        assert resp.status_code == 409


class TestSafetyReportTerminationCascade:
    def test_safety_report_to_termination_to_devex_cancel_depth3(self, api, platform_admin_headers):
        """PRD §3.10: "`TERMINATE_SENDER` creates an `AccountTermination` row with
        `reason_code` of `SAFETY_VIOLATION`, feeding the termination pipeline of
        §3.11."
        PRD §3.11: "Once the disposition's side effects settle, the system moves the
        termination to `COMPLETE`, which cascades the `User` to `TERMINATED` per §3.1 —
        stamping `terminated_at` and pushing every child entity to its terminal state."

        Design: Difficulty/transitive_cascade/safety_report_to_termination_to_devex_cancel_depth3
        """
        offender = setup_devex_eligible_user(target_earned_robux=30000)
        exp, _sub = create_published_experience(offender["id"], title="Off World")
        devex = submit_devex_request(offender["id"], 30000)
        assert devex["status"] == "SUBMITTED"

        reporter = create_user(username="reporter", email="rep@x.com", date_of_birth="1990-01-01")
        msg = send_chat(offender["id"], exp["id"], body_raw="offensive content")
        report = report_message(reporter["id"], msg["id"], reason_code="HARASSMENT")
        triage_report(report["id"])

        actioned = validate_success(
            api.action_report(report["id"], {"action_taken": "TERMINATE_SENDER"},
                              make_safety_agent_headers("sa-1")),
            200,
        )
        assert actioned["status"] == "ACTIONED"

        # Link 2: an AccountTermination row for the offender in PENDING_DISPOSITION.
        terms, _meta = validate_paginated(
            api.list_account_terminations(ADMIN, params={"user_id": offender["id"]})
        )
        assert len(terms) == 1, f"expected exactly one termination row, got {len(terms)}"
        term = terms[0]
        assert term["reason_code"] == "SAFETY_VIOLATION"
        assert term["status"] == "PENDING_DISPOSITION"

        # The user is not yet terminated: disposition has not run.
        assert get_user(offender["id"])["status"] == "ACTIVE"

        # Link 3: disposition completes the pipeline; the DevEx request dies with it.
        disposed = validate_success(api.dispose_earnings(term["id"], ADMIN), 200)
        assert disposed["status"] in ("EARNINGS_DISPOSED", "COMPLETE")

        user_after = get_user(offender["id"])
        assert user_after["status"] == "TERMINATED", (
            f"completed termination must cascade the user to TERMINATED, got {user_after['status']}"
        )
        devex_after = validate_success(
            api.get_devex_request(devex["id"], ADMIN), 200
        )
        assert devex_after["status"] == "CANCELLED", (
            f"in-flight SUBMITTED DevEx request must be CANCELLED by termination, got "
            f"{devex_after['status']}"
        )

    def test_report_action_suspend_sender_cascades(self, api, platform_admin_headers):
        """PRD §3.10: "a `WARNING` leaves the sender untouched, `SUSPEND_SENDER`
        cascades the message's sender into `SUSPENDED` (with the full user-suspension
        cascade of §3.1), and `TERMINATE_SENDER` creates an `AccountTermination` row
        with `reason_code` of `SAFETY_VIOLATION`, feeding the termination pipeline of
        §3.11."
        PRD §3.1: "every `SUBMITTED` DevEx request for the user transitions to
        `CANCELLED` with its `locked_robux` released"

        Design: Difficulty/transitive_cascade/safety_report_to_termination_to_devex_cancel_depth3
        """
        offender = setup_devex_eligible_user(target_earned_robux=30000)
        exp, _sub = create_published_experience(offender["id"], title="Off World Two")
        devex = submit_devex_request(offender["id"], 30000)

        reporter = create_user(username="reporter2", email="rep2@x.com", date_of_birth="1990-01-01")
        msg = send_chat(offender["id"], exp["id"], body_raw="offensive content again")
        report = report_message(reporter["id"], msg["id"], reason_code="HARASSMENT")
        triage_report(report["id"])

        actioned = validate_success(
            api.action_report(report["id"], {"action_taken": "SUSPEND_SENDER"},
                              make_safety_agent_headers("sa-2")),
            200,
        )
        assert actioned["status"] == "ACTIONED"

        assert get_user(offender["id"])["status"] == "SUSPENDED"
        exp_now = validate_success(api.get_experience(exp["id"], ADMIN), 200)
        assert exp_now["status"] == "SUSPENDED", (
            "the suspension cascade must push the offender's published experience to SUSPENDED"
        )
        devex_after = validate_success(api.get_devex_request(devex["id"], ADMIN), 200)
        assert devex_after["status"] == "CANCELLED", (
            "the suspension cascade must cancel the in-flight SUBMITTED DevEx request"
        )
