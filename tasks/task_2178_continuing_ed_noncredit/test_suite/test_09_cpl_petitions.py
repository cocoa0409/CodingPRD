"""Credit for prior learning: the review loop, segregation of duties and the conversion."""

from test_helpers import (
    ADMIN,
    ADMIN2,
    COURSE_EXT_050,
    COURSE_EXT_150,
    COURSE_EXT_300,
    REGISTRAR,
    ApiErrorId,
    make_learner_headers,
    read_petition,
    read_record,
    read_registration,
    reset_clock,
    review_petition,
    set_clock,
    setup_draft_petition_with_citation,
    setup_petition_under_review,
    submit_petition,
    validate_error,
    validate_success,
)

MICRO_OFFERING = {"session_count": 4, "tuition_cents": 25000}
CAPSTONE_OFFERING = {"session_count": 4, "tuition_cents": 120000}


class TestRevisionLoop:
    """The petition re-enters SUBMITTED and UNDER_REVIEW it has already occupied."""

    def test_request_revision_advances_the_round_and_returns_to_submitted(self, api):
        """PRD 3.10: "From `UNDER_REVIEW` the reviewer may send it back, moving it
        `UNDER_REVIEW → REVISION_REQUESTED`, incrementing `revision_round` by 1,
        re-stamping `assessed_by_user_id` with the acting `X-User-ID`, and optionally
        recording a `decision_note` explaining what needs fixing."
        PRD 3.10: "Submission moves the petition to `SUBMITTED` and is available from
        `DRAFT` and from `REVISION_REQUESTED` alike — that second edge is what closes
        the review cycle."

        Design: Difficulty/non_linear_state_machine/cpl_petition_revision_loop_returns_to_submitted
        """
        reset_clock()
        scene = setup_petition_under_review(
            target_course_spec=COURSE_EXT_150,
            course_spec=COURSE_EXT_050,
            offering_overrides=MICRO_OFFERING,
        )
        sent_back = validate_success(
            api.request_petition_revision(
                scene["petition_id"],
                {"decision_note": "Add the contact-hour transcript."},
                ADMIN,
            )
        )
        assert sent_back["status"] == "REVISION_REQUESTED"
        assert sent_back["revision_round"] == 1

        resubmitted = validate_success(
            api.submit_petition(
                scene["petition_id"], make_learner_headers(scene["learner_id"])
            )
        )
        assert resubmitted["status"] == "SUBMITTED"

    def test_the_second_review_restamps_the_assessor(self, api):
        """PRD 3.10: "A `ProgramAdmin` takes a submitted petition under review, moving
        it `SUBMITTED → UNDER_REVIEW` and stamping `assessed_by_user_id` with the acting
        `X-User-ID`."
        PRD 3.10: "The learner then resubmits, and the cycle `SUBMITTED → UNDER_REVIEW →
        REVISION_REQUESTED → SUBMITTED` may run until the budget is spent. Each of these
        transitions increments the petition's `version` by 1."

        Design: Difficulty/non_linear_state_machine/cpl_petition_revision_loop_returns_to_submitted
        """
        reset_clock()
        scene = setup_petition_under_review(
            target_course_spec=COURSE_EXT_150,
            course_spec=COURSE_EXT_050,
            offering_overrides=MICRO_OFFERING,
        )
        api.request_petition_revision(
            scene["petition_id"], {"decision_note": "Add the contact-hour transcript."}, ADMIN
        )
        submit_petition(scene["petition_id"], scene["learner_id"])

        second_review = validate_success(
            api.review_petition(scene["petition_id"], ADMIN2)
        )
        assert second_review["status"] == "UNDER_REVIEW"
        assert second_review["assessed_by_user_id"] == "admin-2"
        assert read_petition(scene["petition_id"])["revision_round"] == 1


class TestSegregationOutranksZeroAward:
    """A decision that breaks both rules reports the earlier-evaluated one."""

    def test_same_admin_deciding_reports_segregation_of_duties(self, api):
        """PRD 2.8: "When a request would fail more than one rule, exactly one error is
        returned, and which one is fully determined: rules are evaluated in ascending
        priority order and the **first** rule that fails determines the response."
        PRD 3.10: "The acting `X-User-ID` must differ from the petition's
        `assessed_by_user_id` — the person who assessed the petition may not be the
        person who decides it — and an attempt by the same operator is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD 3.10: "If the resulting `awarded_credit_units` is zero or less and the
        decision is `APPROVE`, the approval is refused with `ERR_CPL_AWARD_ZERO` (HTTP
        422); a denial with a zero award is perfectly legal and simply records the zero."

        Design: Difficulty/priority_pair_validation_conflict/safety_segregation_of_duties_wins_over_fiscal_cpl_award_zero
        """
        reset_clock()
        scene = setup_petition_under_review(
            target_course_spec=COURSE_EXT_150,
            course_spec=COURSE_EXT_050,
            offering_overrides=MICRO_OFFERING,
        )
        error = validate_error(
            api.decide_petition(
                scene["petition_id"],
                {"decision": "APPROVE", "decision_note": "Looks sufficient."},
                ADMIN,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert error["error_id"] != "ERR_CPL_AWARD_ZERO"

    def test_the_refused_decision_leaves_the_petition_under_review_and_unpriced(self, api):
        """PRD 3.10: "Adjudication is a `ProgramAdmin` action taken from `UNDER_REVIEW`
        with a `decision` of `APPROVE` or `DENY` and an optional `decision_note`."
        PRD 3.10: "Both outcomes record the conversion arithmetic: `claimed_ceu_total`
        and `awarded_credit_units` are computed and stored **even on a denial**, so a
        denied petition still shows what it would have been worth."
        PRD 3.10: "A `ProgramAdmin` takes a submitted petition under review, moving it
        `SUBMITTED → UNDER_REVIEW` and stamping `assessed_by_user_id` with the acting
        `X-User-ID`."

        Design: Difficulty/priority_pair_validation_conflict/safety_segregation_of_duties_wins_over_fiscal_cpl_award_zero
        """
        reset_clock()
        scene = setup_petition_under_review(
            target_course_spec=COURSE_EXT_150,
            course_spec=COURSE_EXT_050,
            offering_overrides=MICRO_OFFERING,
        )
        api.decide_petition(
            scene["petition_id"],
            {"decision": "APPROVE", "decision_note": "Looks sufficient."},
            ADMIN,
        )
        petition = read_petition(scene["petition_id"])
        assert petition["status"] == "UNDER_REVIEW"
        assert petition["awarded_credit_units"] is None
        assert petition["assessed_by_user_id"] == "admin-1"


class TestSubmitDependsOnCitedRecordState:
    """A petition may only be submitted while every cited record is still ISSUED."""

    def test_revoking_the_cited_record_blocks_submission(self, api):
        """PRD 3.10: "Every cited completion record must still be `ISSUED` and still
        belong to this learner, or the submission fails with
        `ERR_CITATION_NOT_ELIGIBLE`."
        PRD 3.7: "On success the record moves `ISSUED → REVOKED`, the originating
        registration moves `COMPLETED → NO_SHOW` on its seat axis, and the learner's
        `lifetime_completed_count`, `lifetime_ceu_total` and `loyalty_tier` are
        recomputed by the same rule as above; because the record has left the issued
        input set, `lifetime_ceu_total` returns to exactly its pre-award value with no
        residual drift."

        Design: Difficulty/cross_entity_state_dependency/cpl_submit_depends_on_cited_completion_record_still_issued
        """
        reset_clock()
        scene = setup_draft_petition_with_citation(
            target_course_spec=COURSE_EXT_150,
            course_spec=COURSE_EXT_050,
            offering_overrides=MICRO_OFFERING,
        )
        revoked = validate_success(
            api.revoke_completion_record(scene["record_id"], REGISTRAR)
        )
        assert revoked["status"] == "REVOKED"

        validate_error(
            api.submit_petition(
                scene["petition_id"], make_learner_headers(scene["learner_id"])
            ),
            ApiErrorId.ERR_CITATION_NOT_ELIGIBLE,
            422,
        )

    def test_the_blocked_petition_stays_in_draft_and_the_seat_becomes_no_show(self, api):
        """PRD 3.10: "The petition is created in `status` `DRAFT` with `revision_round`
        at 0, `assessed_by_user_id` null, `claimed_ceu_total` null,
        `awarded_credit_units` null and `decision_note` null."
        PRD 3.7: "On success the record moves `ISSUED → REVOKED`, the originating
        registration moves `COMPLETED → NO_SHOW` on its seat axis, and the learner's
        `lifetime_completed_count`, `lifetime_ceu_total` and `loyalty_tier` are
        recomputed by the same rule as above; because the record has left the issued
        input set, `lifetime_ceu_total` returns to exactly its pre-award value with no
        residual drift."

        Design: Difficulty/cross_entity_state_dependency/cpl_submit_depends_on_cited_completion_record_still_issued
        """
        reset_clock()
        scene = setup_draft_petition_with_citation(
            target_course_spec=COURSE_EXT_150,
            course_spec=COURSE_EXT_050,
            offering_overrides=MICRO_OFFERING,
        )
        api.revoke_completion_record(scene["record_id"], REGISTRAR)
        api.submit_petition(
            scene["petition_id"], make_learner_headers(scene["learner_id"])
        )

        assert read_petition(scene["petition_id"])["status"] == "DRAFT"
        assert read_record(scene["record_id"])["status"] == "REVOKED"
        assert read_registration(scene["registration_id"])["enrollment_status"] == "NO_SHOW"


def test_third_revision_request_exhausts_the_budget(api):
    """PRD 3.10: "The revision budget is two rounds: a revision request is permitted
    only while `revision_round` is strictly below 2, and the third attempt is refused
    with `ERR_CPL_REVISION_LIMIT` (HTTP 409)."

    Design: Corner/state_machines/cpl_request_revision_beyond_limit_returns_cpl_revision_limit
    """
    reset_clock()
    scene = setup_petition_under_review(
        target_course_spec=COURSE_EXT_150,
        course_spec=COURSE_EXT_050,
        offering_overrides=MICRO_OFFERING,
    )
    api.request_petition_revision(scene["petition_id"], {"decision_note": "Round one."}, ADMIN)
    submit_petition(scene["petition_id"], scene["learner_id"])
    review_petition(scene["petition_id"], ADMIN)
    second = validate_success(
        api.request_petition_revision(
            scene["petition_id"], {"decision_note": "Round two."}, ADMIN
        )
    )
    assert second["revision_round"] == 2
    submit_petition(scene["petition_id"], scene["learner_id"])
    review_petition(scene["petition_id"], ADMIN)

    validate_error(
        api.request_petition_revision(
            scene["petition_id"], {"decision_note": "Round three."}, ADMIN
        ),
        ApiErrorId.ERR_CPL_REVISION_LIMIT,
        409,
    )
    petition = read_petition(scene["petition_id"])
    assert petition["status"] == "UNDER_REVIEW"
    assert petition["revision_round"] == 2


def test_conversion_caps_the_award_at_seventy_five_percent_of_course_credits(api):
    """PRD 3.10: "Raw credits are then `claimed_ceu_total` divided by a CEU-to-credit
    divisor of 3.0. A ceiling is imposed by the target course itself: no petition may
    award more than 75 percent of the target course's own `cpl_credit_units`, so the
    capped credits are the smaller of the raw credits and that ceiling."
    PRD 3.10: "Finally `awarded_credit_units` is quantised **downwards** to a
    half-credit step: divide the capped credits by 0.5, take the floor, and multiply
    back by 0.5. Flooring is mandatory here — rounding to the nearest half credit is
    wrong and will award credit the school has not earned."

    Design: Corner/calculations/cpl_conversion_caps_award_at_seventy_five_percent_of_course_credits
    """
    reset_clock()
    scene = setup_petition_under_review(
        target_course_spec=COURSE_EXT_050,
        course_spec=COURSE_EXT_300,
        offering_overrides=CAPSTONE_OFFERING,
    )
    assert scene["record"]["ceu_awarded"] == 3.0

    data = validate_success(
        api.decide_petition(
            scene["petition_id"],
            {"decision": "APPROVE", "decision_note": "Capstone evidence accepted."},
            ADMIN2,
        )
    )
    assert data["claimed_ceu_total"] == 3.0
    assert data["awarded_credit_units"] == 0.5, (
        f"the 1.0-credit target course caps the award at 0.75, which floors to 0.5, "
        f"got {data['awarded_credit_units']}"
    )
    assert data["awarded_credit_units"] != 1.0
    assert data["status"] == "APPROVED"
    assert data["revision_round"] == 0


def test_conversion_halves_the_contribution_of_a_record_older_than_five_years(api):
    """PRD 3.10: "For each citation, measure the age of the cited record as the
    interval between the current logical clock and the record's `issued_at`, divided by
    365 days of 86,400 seconds each and floored to a whole number of years. A record
    aged 5 years or more attracts a recency decay factor of 0.5; a younger record
    attracts a factor of 1.0."
    PRD 3.10: "The citation's contribution is the record's `ceu_awarded` multiplied by
    the citation's `weight` and by that factor, rounded half up to two decimal places —
    **per citation**, before any summing. `claimed_ceu_total` is the sum of those
    individually rounded contributions, itself rounded half up to two decimal places."

    Design: Corner/calculations/cpl_conversion_halves_contribution_of_records_older_than_five_years
    """
    reset_clock()
    scene = setup_petition_under_review(
        target_course_spec=COURSE_EXT_150,
        course_spec=COURSE_EXT_300,
        offering_overrides=CAPSTONE_OFFERING,
    )
    assert scene["record"]["issued_at"] == "2026-09-01T00:00:00.000Z"
    set_clock("2032-09-01T00:00:00Z")

    data = validate_success(
        api.decide_petition(
            scene["petition_id"],
            {"decision": "APPROVE", "decision_note": "Aged evidence, half weight."},
            ADMIN2,
        )
    )
    assert data["claimed_ceu_total"] == 1.5, (
        f"3.0 CEU decayed by 0.5 contributes 1.5, got {data['claimed_ceu_total']}"
    )
    assert data["claimed_ceu_total"] != 3.0
    assert data["awarded_credit_units"] == 0.5
    assert data["awarded_credit_units"] != 1.0
    assert data["status"] == "APPROVED"


def test_approving_a_zero_credit_award_is_refused(api):
    """PRD 3.10: "If the resulting `awarded_credit_units` is zero or less and the
    decision is `APPROVE`, the approval is refused with `ERR_CPL_AWARD_ZERO` (HTTP 422);
    a denial with a zero award is perfectly legal and simply records the zero."
    PRD 3.10: "Finally `awarded_credit_units` is quantised **downwards** to a
    half-credit step: divide the capped credits by 0.5, take the floor, and multiply
    back by 0.5. Flooring is mandatory here — rounding to the nearest half credit is
    wrong and will award credit the school has not earned."

    Design: Corner/errors/cpl_approve_with_zero_award_by_independent_admin_returns_422
    """
    reset_clock()
    scene = setup_petition_under_review(
        target_course_spec=COURSE_EXT_150,
        course_spec=COURSE_EXT_050,
        offering_overrides=MICRO_OFFERING,
    )
    validate_error(
        api.decide_petition(
            scene["petition_id"],
            {"decision": "APPROVE", "decision_note": "Independent reviewer."},
            ADMIN2,
        ),
        ApiErrorId.ERR_CPL_AWARD_ZERO,
        422,
    )
    petition = read_petition(scene["petition_id"])
    assert petition["status"] == "UNDER_REVIEW"
    assert petition["awarded_credit_units"] is None


def test_second_petition_for_an_already_awarded_course_is_refused(api):
    """PRD 3.10: "The learner must not already hold another petition for the same
    `target_course_id` in `status` `APPROVED`, or the submission fails with
    `ERR_CPL_DUPLICATE_AWARD`."
    PRD 3.10: "`decision_note` is written from the payload, the petition moves
    `UNDER_REVIEW → APPROVED` or `UNDER_REVIEW → DENIED` — both terminal — and its
    `version` increments by 1."

    Design: Corner/errors/second_petition_for_already_awarded_course_returns_cpl_duplicate_award
    """
    reset_clock()
    scene = setup_petition_under_review(
        target_course_spec=COURSE_EXT_150,
        course_spec=COURSE_EXT_300,
        offering_overrides=CAPSTONE_OFFERING,
    )
    approved = validate_success(
        api.decide_petition(
            scene["petition_id"], {"decision": "APPROVE", "decision_note": "Approved."}, ADMIN2
        )
    )
    assert approved["awarded_credit_units"] == 1.0
    assert approved["status"] == "APPROVED"

    second = validate_success(
        api.create_petition(
            {
                "learner_id": scene["learner_id"],
                "target_course_id": scene["target_course_id"],
            },
            make_learner_headers(scene["learner_id"]),
        ),
        201,
    )
    validate_success(
        api.create_citation(
            second["id"],
            {"completion_record_id": scene["record_id"], "weight": 1.0},
            make_learner_headers(scene["learner_id"]),
        ),
        201,
    )
    validate_error(
        api.submit_petition(second["id"], make_learner_headers(scene["learner_id"])),
        ApiErrorId.ERR_CPL_DUPLICATE_AWARD,
        409,
    )
    assert read_petition(second["id"])["status"] == "DRAFT"
    assert read_petition(scene["petition_id"])["status"] == "APPROVED"
