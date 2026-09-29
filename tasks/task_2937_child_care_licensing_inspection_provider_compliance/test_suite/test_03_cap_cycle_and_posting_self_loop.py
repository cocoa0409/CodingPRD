"""The two bounded cycles of the service (PRD §3.6, §3.9).

A corrective action plan walks SUBMITTED -> REJECTED -> SUBMITTED at most twice,
and a public posting re-enters CORRECTED from CORRECTED at most twice.  Both
loops are bounded by a counter, and both refuse the over-run without moving the
row.
"""

from test_helpers import (
    CODE_RATIO,
    CODE_SUPERVISION_PLAN,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_instant,
    assert_score,
    factories as f,
    fixtures as fx,
    make_applicant_headers,
    supervisor_headers,
    validate_error,
    validate_success,
)


def _finalized_visit_with_one_serious_finding(api, catalog):
    """A FINALIZED COMPLAINT visit carrying a single SERIOUS RA-201 citation.

    The ten-day plan window therefore closes at 2026-08-11T00:00:00Z and the
    plan's own allowance is the same ten days.
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    inspector = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Cedar Lane Center",
        site_address="4 Cedar Ln",
        program_type="CENTER",
        requested_capacity=60,
    )
    complaint = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="PHONE",
        allegation_category="RATIO",
        affected_age_group="PRESCHOOL",
        narrative="Caller reports the preschool room is routinely over ratio.",
        anonymous=True,
    )
    visit = fx.run_visit(
        api,
        provider["id"],
        inspector["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
        complaint_id=complaint["id"],
        catalog=catalog,
        citations=[
            {
                "code": CODE_RATIO,
                "narrative": "Preschool room at 13 children to one staff member.",
            }
        ],
        outcome="CONDITIONAL_PASS",
    )
    return {
        "provider_id": provider["id"],
        "inspection": visit["inspection"],
        "violation_id": visit["violations"][0]["id"],
        "inspector": inspector,
    }


def _submit_plan(api, ctx, proposed_completion_date="2026-08-09"):
    return fx.submit_cap(
        api,
        ctx["provider_id"],
        ctx["inspection"]["id"],
        [ctx["violation_id"]],
        ctx["inspection"]["version"],
        narrative="Hire two additional preschool aides.",
        proposed_completion_date=proposed_completion_date,
    )


def _resubmit(api, ctx, cap_id, narrative, proposed_completion_date):
    return api.resubmit_cap(
        cap_id,
        f.cap_resubmit_payload(
            [ctx["violation_id"]],
            narrative=narrative,
            proposed_completion_date=proposed_completion_date,
        ),
        headers=make_applicant_headers(ctx["provider_id"]),
    )


class TestCapReviewCycleBoundedAtThree:
    """§3.6: "`review_cycle_count` must be strictly below 3, or the call is
    `ERR_CAP_REVIEW_CYCLE_EXHAUSTED`"."""

    def test_a_new_plan_opens_the_cycle_at_one_with_the_tightest_allowance(
        self, api, catalog
    ):
        """The plan is created in SUBMITTED with the cycle counter already at 1
        and a due_at ten days out, the allowance implied by its one SERIOUS
        violation.

        PRD §3.6: "The plan is created in `SUBMITTED` with `review_cycle_count` at
        1, `submitted_at` stamped, and `reviewed_at`, `approved_at`,
        `completed_at`, `reviewed_by_user_id` and `review_note` null."

        Design: Difficulty/non_linear_state_machine/non_linear_cap_review_cycle_bounded_at_three
        """
        ctx = _finalized_visit_with_one_serious_finding(api, catalog)
        plan = _submit_plan(api, ctx)

        assert plan["status"] == "SUBMITTED"
        assert plan["review_cycle_count"] == 1
        assert_instant(plan["due_at"], "2026-08-11T00:00:00Z", "due_at")
        assert_instant(plan["submitted_at"], DEFAULT_LOGICAL_CLOCK, "submitted_at")
        assert plan["reviewed_at"] is None
        assert plan["approved_at"] is None
        assert plan["completed_at"] is None
        assert plan["reviewed_by_user_id"] is None
        assert plan["review_note"] is None
        assert plan["provider_id"] == ctx["provider_id"]

    def test_exactly_two_resubmissions_are_permitted(self, api, catalog):
        """Rejection returns the plan to the provider; the first resubmit takes the
        counter to 2 and the second to 3, each recomputing due_at from the clock
        of that resubmission.

        PRD §3.6: "Resubmission returns `status` to `SUBMITTED` — closing the
        submitted-rejected-submitted cycle — increments `review_cycle_count`,
        re-stamps `submitted_at`, replaces `narrative`, `proposed_completion_date`
        and `violation_ids` with the new values, recomputes `due_at` from the new
        violation set, and re-checks both the ten-day submission window and the
        violation-to-inspection agreement."

        Design: Difficulty/non_linear_state_machine/non_linear_cap_review_cycle_bounded_at_three
        """
        ctx = _finalized_visit_with_one_serious_finding(api, catalog)
        plan = _submit_plan(api, ctx)

        rejected = fx.review_cap(
            api, plan["id"], "REJECT", review_note="Staffing plan lacks named hires."
        )
        assert rejected["status"] == "REJECTED"
        assert_instant(rejected["reviewed_at"], DEFAULT_LOGICAL_CLOCK, "reviewed_at")
        assert rejected["review_cycle_count"] == 1

        fx.set_clock(api, "2026-08-03T00:00:00Z")
        second = validate_success(
            _resubmit(
                api,
                ctx,
                plan["id"],
                "Two named aides start 2026-08-10.",
                "2026-08-11",
            )
        )
        assert second["status"] == "SUBMITTED"
        assert second["review_cycle_count"] == 2
        assert_instant(second["submitted_at"], "2026-08-03T00:00:00Z", "submitted_at")
        assert_instant(second["due_at"], "2026-08-13T00:00:00Z", "due_at")
        assert second["proposed_completion_date"] == "2026-08-11"

        fx.review_cap(
            api, plan["id"], "REJECT", review_note="No supervision schedule attached."
        )
        fx.set_clock(api, "2026-08-05T00:00:00Z")
        third = validate_success(
            _resubmit(
                api,
                ctx,
                plan["id"],
                "Aides plus a posted supervision schedule.",
                "2026-08-13",
            )
        )
        assert third["status"] == "SUBMITTED"
        assert third["review_cycle_count"] == 3
        assert_instant(third["due_at"], "2026-08-15T00:00:00Z", "due_at")

    def test_the_third_resubmission_exhausts_the_cycle_and_moves_nothing(
        self, api, catalog
    ):
        """With the counter at 3 the loop is closed: the refusal is
        ERR_CAP_REVIEW_CYCLE_EXHAUSTED and the row stays REJECTED at cycle 3 with
        its version untouched.

        PRD §3.6: "with the count starting at 1, this permits two resubmissions,
        taking the count to 2 and then 3, and refuses the third."

        Design: Difficulty/non_linear_state_machine/non_linear_cap_review_cycle_bounded_at_three
        """
        ctx = _finalized_visit_with_one_serious_finding(api, catalog)
        plan = _submit_plan(api, ctx)

        fx.review_cap(api, plan["id"], "REJECT", review_note="Lacks named hires.")
        fx.set_clock(api, "2026-08-03T00:00:00Z")
        validate_success(_resubmit(api, ctx, plan["id"], "Named aides.", "2026-08-11"))
        fx.review_cap(api, plan["id"], "REJECT", review_note="No schedule attached.")
        fx.set_clock(api, "2026-08-05T00:00:00Z")
        validate_success(
            _resubmit(api, ctx, plan["id"], "Aides plus schedule.", "2026-08-13")
        )
        after_third_reject = fx.review_cap(
            api, plan["id"], "REJECT", review_note="The 15:00 hour is still uncovered."
        )
        assert after_third_reject["status"] == "REJECTED"
        assert after_third_reject["review_cycle_count"] == 3

        validate_error(
            _resubmit(
                api, ctx, plan["id"], "Third attempt with full-day coverage.", "2026-08-14"
            ),
            "ERR_CAP_REVIEW_CYCLE_EXHAUSTED",
            409,
        )

        unchanged = validate_success(
            api.get_cap(plan["id"], headers=supervisor_headers())
        )
        assert unchanged["status"] == "REJECTED"
        assert unchanged["review_cycle_count"] == 3
        assert unchanged["version"] == after_third_reject["version"], (
            "a refused resubmission is not a write and must not advance the version"
        )

    def test_reviewing_an_already_rejected_plan_is_a_state_error(self, api, catalog):
        """Review demands a SUBMITTED plan, so a second REJECT on a REJECTED row is
        ERR_INVALID_CAP_STATE rather than a further cycle.

        PRD §3.6: "A supervisor reviews a `SUBMITTED` plan with a `decision` of
        `APPROVE` or `REJECT` and an optional `review_note`"

        Design: Difficulty/non_linear_state_machine/non_linear_cap_review_cycle_bounded_at_three
        """
        ctx = _finalized_visit_with_one_serious_finding(api, catalog)
        plan = _submit_plan(api, ctx)
        rejected = fx.review_cap(
            api, plan["id"], "REJECT", review_note="Staffing plan lacks named hires."
        )

        validate_error(
            api.review_cap(
                plan["id"],
                "REJECT",
                review_note="Second rejection attempted on a rejected plan.",
                headers=supervisor_headers(),
            ),
            "ERR_INVALID_CAP_STATE",
            409,
        )

        unchanged = validate_success(
            api.get_cap(plan["id"], headers=supervisor_headers())
        )
        assert unchanged["status"] == "REJECTED"
        assert unchanged["version"] == rejected["version"]

    def test_the_version_advances_once_per_accepted_write(self, api, catalog):
        """Three rejections and two resubmissions are five accepted writes, so the
        version advances five times and the refused sixth call not at all.

        PRD §2.5: "`version`, an integer that starts at 1 on creation and
        increments by exactly 1 on each mutation of the row."

        Design: Difficulty/non_linear_state_machine/non_linear_cap_review_cycle_bounded_at_three
        """
        ctx = _finalized_visit_with_one_serious_finding(api, catalog)
        plan = _submit_plan(api, ctx)
        created_version = plan["version"]
        versions = []

        versions.append(
            fx.review_cap(api, plan["id"], "REJECT", review_note="Lacks named hires.")[
                "version"
            ]
        )
        fx.set_clock(api, "2026-08-03T00:00:00Z")
        versions.append(
            validate_success(
                _resubmit(api, ctx, plan["id"], "Named aides.", "2026-08-11")
            )["version"]
        )
        versions.append(
            fx.review_cap(api, plan["id"], "REJECT", review_note="No schedule.")[
                "version"
            ]
        )
        fx.set_clock(api, "2026-08-05T00:00:00Z")
        versions.append(
            validate_success(
                _resubmit(api, ctx, plan["id"], "Aides plus schedule.", "2026-08-13")
            )["version"]
        )
        versions.append(
            fx.review_cap(api, plan["id"], "REJECT", review_note="Still uncovered.")[
                "version"
            ]
        )

        assert versions == [created_version + n for n in range(1, 6)], (
            f"expected five consecutive versions after {created_version}, got {versions}"
        )

        validate_error(
            _resubmit(api, ctx, plan["id"], "Third attempt.", "2026-08-14"),
            "ERR_CAP_REVIEW_CYCLE_EXHAUSTED",
            409,
        )
        assert (
            validate_success(api.get_cap(plan["id"], headers=supervisor_headers()))[
                "version"
            ]
            == versions[-1]
        )


def _posted_report(api, catalog):
    """A FINALIZED FAIL visit scoring 85.00, published to the register at
    2026-08-01T00:00:00Z with the provider at ladder step 0."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    inspector = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Birch Row Center",
        site_address="5 Birch Row",
        program_type="CENTER",
        requested_capacity=60,
    )
    complaint = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="WEB",
        allegation_category="SUPERVISION",
        affected_age_group="PRESCHOOL",
        narrative="Parent reports no written supervision plan is posted.",
        anonymous=True,
    )
    visit = fx.run_visit(
        api,
        provider["id"],
        inspector["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
        complaint_id=complaint["id"],
        catalog=catalog,
        citations=[
            {
                "code": CODE_SUPERVISION_PLAN,
                "narrative": "No written supervision plan anywhere on site.",
            }
        ],
        outcome="FAIL",
    )
    posting = fx.prepare_posting(
        api,
        visit["inspection"]["id"],
        consumer_summary="One critical supervision finding was cited at this site.",
        redaction_complete=True,
    )
    return {
        "provider_id": provider["id"],
        "inspection": visit["inspection"],
        "posting": posting,
    }


class TestPostingCorrectionSelfLoopBoundedAtTwo:
    """§3.9: "A posting already `CORRECTED` may be corrected again: that
    self-loop is the cyclic element of this lifecycle, and it is bounded"."""

    def test_a_prepared_posting_carries_no_public_number_yet(self, api, catalog):
        """Before publication the posting has no display score, no posted_at and no
        expiry, and its correction counter is zero.

        PRD §3.9: "The record is created in `PENDING_REDACTION` with `provider_id`
        copied from the inspection rather than supplied, `display_score`,
        `posted_at`, `expires_at`, `corrected_at` and `withdrawn_at` null,
        `enforcement_banner` at `NONE` and `correction_count` at 0."

        Design: Difficulty/non_linear_state_machine/non_linear_posting_correction_self_loop_bounded_at_two
        """
        ctx = _posted_report(api, catalog)
        posting = ctx["posting"]

        assert posting["posting_status"] == "PENDING_REDACTION"
        assert posting["correction_count"] == 0
        assert posting["display_score"] is None
        assert posting["expires_at"] is None
        assert posting["posted_at"] is None
        assert posting["corrected_at"] is None
        assert posting["withdrawn_at"] is None
        assert posting["enforcement_banner"] == "NONE"
        assert posting["provider_id"] == ctx["provider_id"]

    def test_publication_stamps_the_thirty_six_month_expiry_and_the_display_score(
        self, api, catalog
    ):
        """Publishing at 2026-08-01 expires the posting on 2029-08-01, and at
        ladder step 0 the display score equals the inspection's final score.

        PRD §3.9: "On success `posting_status` becomes `POSTED`, `posted_at` is
        stamped, and `expires_at` is set to 36 months after that instant."

        Design: Difficulty/non_linear_state_machine/non_linear_posting_correction_self_loop_bounded_at_two
        """
        ctx = _posted_report(api, catalog)
        posted = fx.publish_posting(api, ctx["posting"]["id"])

        assert posted["posting_status"] == "POSTED"
        assert_instant(posted["posted_at"], DEFAULT_LOGICAL_CLOCK, "posted_at")
        assert_instant(posted["expires_at"], "2029-08-01T00:00:00Z", "expires_at")
        assert posted["enforcement_banner"] == "NONE"
        assert_score(posted["display_score"], 85.00, "display_score")

    def test_the_second_correction_re_enters_the_same_state_and_the_third_is_refused(
        self, api, catalog
    ):
        """CORRECTED -> CORRECTED is a genuine self-loop that bumps the counter to
        2; the third correction is ERR_POSTING_CORRECTION_LIMIT and moves nothing,
        and the expiry stays pinned to the first publication.

        PRD §3.9: "A correction requires `correction_count` to be strictly below 2,
        or it is `ERR_POSTING_CORRECTION_LIMIT` (HTTP 409); it sets
        `posting_status` to `CORRECTED`, increments `correction_count`, stamps
        `corrected_at`, and recomputes `display_score` and `enforcement_banner`
        from the inspection's and provider's current values"

        Design: Difficulty/non_linear_state_machine/non_linear_posting_correction_self_loop_bounded_at_two
        """
        ctx = _posted_report(api, catalog)
        posting_id = ctx["posting"]["id"]
        fx.publish_posting(api, posting_id)

        fx.set_clock(api, "2026-08-02T00:00:00Z")
        first = validate_success(
            api.revise_posting(
                posting_id,
                "CORRECT",
                "Room number corrected in the consumer summary.",
                headers=admin_headers(),
            )
        )
        assert first["posting_status"] == "CORRECTED"
        assert first["correction_count"] == 1
        assert_instant(first["corrected_at"], "2026-08-02T00:00:00Z", "corrected_at")
        assert_score(first["display_score"], 85.00, "display_score")
        assert_instant(first["expires_at"], "2029-08-01T00:00:00Z", "expires_at")

        fx.set_clock(api, "2026-08-03T00:00:00Z")
        second = validate_success(
            api.revise_posting(
                posting_id,
                "CORRECT",
                "Inspector name spelling corrected.",
                headers=admin_headers(),
            )
        )
        assert second["posting_status"] == "CORRECTED", (
            "the self-loop re-enters CORRECTED rather than leaving it"
        )
        assert second["correction_count"] == 2
        assert_instant(second["corrected_at"], "2026-08-03T00:00:00Z", "corrected_at")
        assert_instant(second["expires_at"], "2029-08-01T00:00:00Z", "expires_at")

        validate_error(
            api.revise_posting(
                posting_id, "CORRECT", "Third correction attempt.", headers=admin_headers()
            ),
            "ERR_POSTING_CORRECTION_LIMIT",
            409,
        )

        unchanged = validate_success(api.get_posting(posting_id, headers=admin_headers()))
        assert unchanged["posting_status"] == "CORRECTED"
        assert unchanged["correction_count"] == 2
        assert_instant(unchanged["corrected_at"], "2026-08-03T00:00:00Z", "corrected_at")
        assert unchanged["version"] == second["version"]

    def test_withdrawal_is_terminal_and_clears_the_public_number(self, api, catalog):
        """A withdrawal from CORRECTED nulls the display score, and no correction is
        possible afterwards; the inspection's own final score never moves.

        PRD §3.9: "A withdrawal sets `posting_status` to the terminal `WITHDRAWN`,
        stamps `withdrawn_at`, sets `display_score` to null, and excludes the
        posting from the public register."

        Design: Difficulty/non_linear_state_machine/non_linear_posting_correction_self_loop_bounded_at_two
        """
        ctx = _posted_report(api, catalog)
        posting_id = ctx["posting"]["id"]
        inspection_id = ctx["inspection"]["id"]
        fx.publish_posting(api, posting_id)

        fx.set_clock(api, "2026-08-02T00:00:00Z")
        validate_success(
            api.revise_posting(
                posting_id, "CORRECT", "Room number corrected.", headers=admin_headers()
            )
        )
        fx.set_clock(api, "2026-08-03T00:00:00Z")
        validate_success(
            api.revise_posting(
                posting_id, "CORRECT", "Inspector name corrected.", headers=admin_headers()
            )
        )

        withdrawn = validate_success(
            api.revise_posting(
                posting_id,
                "WITHDRAW",
                "Report withdrawn pending an appeal decision.",
                headers=admin_headers(),
            )
        )
        assert withdrawn["posting_status"] == "WITHDRAWN"
        assert_instant(withdrawn["withdrawn_at"], "2026-08-03T00:00:00Z", "withdrawn_at")
        assert withdrawn["display_score"] is None

        validate_error(
            api.revise_posting(
                posting_id,
                "CORRECT",
                "Attempted correction after withdrawal.",
                headers=admin_headers(),
            ),
            "ERR_INVALID_POSTING_STATE",
            409,
        )

        inspection = validate_success(
            api.get_inspection(inspection_id, headers=supervisor_headers())
        )
        assert_score(
            inspection["final_compliance_score"], 85.00, "final_compliance_score"
        )
        assert_score(
            inspection["preliminary_compliance_score"],
            85.00,
            "preliminary_compliance_score",
        )
