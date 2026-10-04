"""Moderation pipeline: automated score routing, human decisions, cascades to
experiences and items, and invalid transitions (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_experience,
    create_user,
    make_moderator_headers,
    set_clock,
    submit_experience_queued,
    validate_error,
    validate_success,
)


class TestAutomatedScoreRouting:
    def test_moderation_submission_fork_join_on_experience(self, api, platform_admin_headers):
        """PRD §3.4: "The classifier computes an `automated_score` between 0.0 and 1.0
        and routes on asymmetric thresholds: a score of 0.85 or higher is auto-rejected
        to `REJECTED` with no human involvement; a score of 0.10 or lower is
        auto-approved to `APPROVED`; anything strictly between goes to `HUMAN_REVIEW`."
        PRD §3.4: "Approval cascades by subject type: an experience subject transitions
        from `PENDING_REVIEW` to `PUBLISHED` and receives its assigned rating"
        PRD §3.4: "an experience subject returns from `PENDING_REVIEW` to `DRAFT` so
        the creator can edit and resubmit"

        Design: Difficulty/non_linear_state_machine/moderation_submission_fork_join_on_experience
        """
        set_clock()
        creator = create_user(username="cr_b", email="cr_b@x.com", date_of_birth="1990-01-01")
        exp1 = create_experience(creator["id"], title="Exp One")
        exp2 = create_experience(creator["id"], title="Exp Two")
        sub1 = submit_experience_queued(creator["id"], exp1["id"])
        sub2 = submit_experience_queued(creator["id"], exp2["id"])

        r1 = validate_success(
            api.inject_moderation_score(sub1["id"], 0.05, platform_admin_headers), 200
        )
        r2 = validate_success(
            api.inject_moderation_score(sub2["id"], 0.90, platform_admin_headers), 200
        )
        assert r1["status"] == "APPROVED", f"score 0.05 must auto-approve, got {r1['status']}"
        assert r2["status"] == "REJECTED", f"score 0.90 must auto-reject, got {r2['status']}"

        e1 = validate_success(api.get_experience(exp1["id"], platform_admin_headers), 200)
        e2 = validate_success(api.get_experience(exp2["id"], platform_admin_headers), 200)
        assert e1["status"] == "PUBLISHED", (
            f"approved experience must be PUBLISHED, got {e1['status']}"
        )
        assert e2["status"] == "DRAFT", (
            f"rejected experience must return to DRAFT, got {e2['status']}"
        )

    def test_moderation_human_review_branch_approve_and_reject(self, api, platform_admin_headers):
        """PRD §3.4: "A human decision is rendered by a `Moderator` supplying a
        `decision` of `APPROVE`, `REJECT`, or `ESCALATE` against a submission in
        `HUMAN_REVIEW`."
        PRD §3.4: "an experience subject transitions from `PENDING_REVIEW` to
        `PUBLISHED` and receives its assigned rating"
        PRD §3.4: "an experience subject returns from `PENDING_REVIEW` to `DRAFT` so
        the creator can edit and resubmit"

        Design: Difficulty/non_linear_state_machine/moderation_submission_fork_join_on_experience
        """
        set_clock()
        creator = create_user(username="cr_hr", email="cr_hr@x.com", date_of_birth="1990-01-01")
        mod = make_moderator_headers("mod-hr-1")
        exp_a = create_experience(creator["id"], title="Human One")
        exp_b = create_experience(creator["id"], title="Human Two")
        sub_a = submit_experience_queued(creator["id"], exp_a["id"])
        sub_b = submit_experience_queued(creator["id"], exp_b["id"])
        api.inject_moderation_score(sub_a["id"], 0.50, platform_admin_headers)
        api.inject_moderation_score(sub_b["id"], 0.50, platform_admin_headers)

        for sub in (sub_a, sub_b):
            cur = validate_success(api.get_moderation_submission(sub["id"], mod), 200)
            assert cur["status"] == "HUMAN_REVIEW", (
                f"score 0.50 must route to HUMAN_REVIEW, got {cur['status']}"
            )

        decided_a = validate_success(
            api.decide_moderation_submission(sub_a["id"], {"decision": "APPROVE"}, mod), 200
        )
        decided_b = validate_success(
            api.decide_moderation_submission(sub_b["id"], {"decision": "REJECT"}, mod), 200
        )
        assert decided_a["status"] == "APPROVED"
        assert decided_b["status"] == "REJECTED"
        ea = validate_success(api.get_experience(exp_a["id"], platform_admin_headers), 200)
        eb = validate_success(api.get_experience(exp_b["id"], platform_admin_headers), 200)
        assert ea["status"] == "PUBLISHED"
        assert eb["status"] == "DRAFT"

    def test_automated_moderation_score_at_boundaries(self, api, platform_admin_headers):
        """PRD §3.4: "The classifier computes an `automated_score` between 0.0 and 1.0
        and routes on asymmetric thresholds: a score of 0.85 or higher is auto-rejected
        to `REJECTED` with no human involvement; a score of 0.10 or lower is
        auto-approved to `APPROVED`; anything strictly between goes to `HUMAN_REVIEW`.
        The boundaries are pinned deliberately — exactly 0.85 rejects, exactly 0.10
        approves."

        Design: Corner/calculations/automated_moderation_score_at_boundaries
        """
        set_clock()
        subs = []
        for i in range(3):
            creator = create_user(
                username=f"cr_{i + 1}", email=f"c{i + 1}@x.com", date_of_birth="1990-01-01"
            )
            exp = create_experience(creator["id"], title=f"Boundary E{i + 1}")
            subs.append(submit_experience_queued(creator["id"], exp["id"]))

        s1 = validate_success(
            api.inject_moderation_score(subs[0]["id"], 0.10, platform_admin_headers), 200
        )
        s2 = validate_success(
            api.inject_moderation_score(subs[1]["id"], 0.50, platform_admin_headers), 200
        )
        s3 = validate_success(
            api.inject_moderation_score(subs[2]["id"], 0.85, platform_admin_headers), 200
        )
        assert s1["status"] == "APPROVED", f"score 0.10 is <= 0.10, must APPROVE, got {s1['status']}"
        assert s2["status"] == "HUMAN_REVIEW", f"score 0.50 must go to HUMAN_REVIEW, got {s2['status']}"
        assert s3["status"] == "REJECTED", f"score 0.85 is >= 0.85, must REJECT, got {s3['status']}"


class TestInvalidModerationTransitions:
    def test_moderation_submission_decide_from_queued_rejected(self, api):
        """PRD §3.4: "A human decision is rendered by a `Moderator` supplying a
        `decision` of `APPROVE`, `REJECT`, or `ESCALATE` against a submission in
        `HUMAN_REVIEW`."
        PRD §2.5: "Fourth, the target entity's current state is checked against the
        requested transition, yielding `ERR_INVALID_STATE`."

        Design: Corner/state_machines/moderation_submission_decide_from_queued_rejected
        """
        set_clock()
        creator = create_user(username="cr_q", email="cr_q@x.com", date_of_birth="1990-01-01")
        exp = create_experience(creator["id"], title="Queued Exp")
        sub = submit_experience_queued(creator["id"], exp["id"])

        mod = make_moderator_headers("mod-q-1")
        resp = api.decide_moderation_submission(sub["id"], {"decision": "APPROVE"}, mod)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        cur = validate_success(api.get_moderation_submission(sub["id"], mod), 200)
        assert cur["status"] == "QUEUED", (
            f"submission must remain QUEUED after a rejected decide, got {cur['status']}"
        )
