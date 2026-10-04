"""Legal clearance: parallel background/suitability dimensions, adjudication
order, and segregation of duties."""

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_START,
    LEGAL_REVIEWER_BACKGROUND_ID,
    LEGAL_REVIEWER_SUITABILITY_ID,
    TEST_USERS,
    adjudicate_background,
    adjudicate_background_payload,
    api_client,
    assert_legal_overall_consistency,
    create_applicant,
    create_program_with_opening,
    determine_suitability,
    determine_suitability_payload,
    get_legal_clearance,
    make_legal_reviewer_headers,
    run_applicant_to_accepted,
    set_clock,
    validate_error,
)

LEGAL = TEST_USERS["legal_reviewer_headers"]


class TestParallelDimensions:
    def test_suitability_requires_adjudicated_background_first(self):
        """PRD §3.6: "The determination, again keyed by an `outcome`,
        requires the suitability dimension still `PENDING`, the lifecycle
        still `ACTIVE`, and the background already adjudicated — determining
        suitability while the background is still `PENDING` fails with
        `ERR_INVALID_STATE`."
        PRD §3.6: "A derived `overall_status` summarizes the pair: `VOID`
        when the clearance's `lifecycle` is `VOID`; otherwise `DENIED` when
        the background is `ADVERSE` or the suitability `UNFAVORABLE`;
        otherwise `CLEARED` when the background is `CLEAR` and the
        suitability `FAVORABLE`; otherwise still `PENDING`."

        Design: Difficulty/non_linear_state_machine/legal_clearance_parallel_dimensions_order_independence
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        clearance = bundle["legal_clearance"]
        assert clearance["background_check_status"] == "PENDING"
        assert clearance["suitability_status"] == "PENDING"
        assert clearance["overall_status"] == "PENDING"

        # Suitability first is rejected: the background is still PENDING.
        validate_error(
            api_client.determine_suitability(
                clearance["id"], determine_suitability_payload(outcome="FAVORABLE"),
                make_legal_reviewer_headers(LEGAL_REVIEWER_SUITABILITY_ID)),
            ApiErrorId.ERR_INVALID_STATE, 409)
        unchanged = get_legal_clearance(bundle["application"]["id"])
        assert unchanged["background_check_status"] == "PENDING"
        assert unchanged["suitability_status"] == "PENDING"
        assert_legal_overall_consistency(unchanged)

        # Background resolves; suitability is untouched (independent dimension).
        adjudicate_background(clearance["id"], outcome="CLEAR",
                              reviewer_id=LEGAL_REVIEWER_BACKGROUND_ID)
        mid = get_legal_clearance(bundle["application"]["id"])
        assert mid["background_check_status"] == "CLEAR"
        assert mid["background_adjudicated_by"] == LEGAL_REVIEWER_BACKGROUND_ID
        assert mid["suitability_status"] == "PENDING"
        assert mid["overall_status"] == "PENDING"
        assert_legal_overall_consistency(mid)

        # Now suitability resolves and the clearance completes.
        determine_suitability(clearance["id"], outcome="FAVORABLE",
                              reviewer_id=LEGAL_REVIEWER_SUITABILITY_ID)
        done = get_legal_clearance(bundle["application"]["id"])
        assert done["suitability_status"] == "FAVORABLE"
        assert done["suitability_decided_by"] == LEGAL_REVIEWER_SUITABILITY_ID
        assert done["overall_status"] == "CLEARED"
        assert_legal_overall_consistency(done)

    def test_dimensions_reject_replay_after_resolution(self):
        """PRD §3.6: "A `LegalReviewer` adjudicates the background check by
        supplying an `outcome`. The act requires the background dimension
        still `PENDING` and the lifecycle still `ACTIVE`, failing with
        `ERR_INVALID_STATE` otherwise, and records the reviewer's `X-User-ID`
        as `background_adjudicated_by`."
        PRD §3.6: "The determination, again keyed by an `outcome`, requires
        the suitability dimension still `PENDING`, the lifecycle still
        `ACTIVE`, and the background already adjudicated — determining
        suitability while the background is still `PENDING` fails with
        `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/legal_clearance_parallel_dimensions_order_independence
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        clearance = bundle["legal_clearance"]
        adjudicate_background(clearance["id"], outcome="CLEAR",
                              reviewer_id=LEGAL_REVIEWER_BACKGROUND_ID)
        determine_suitability(clearance["id"], outcome="FAVORABLE",
                              reviewer_id=LEGAL_REVIEWER_SUITABILITY_ID)

        # Neither dimension is PENDING any more: both acts are rejected.
        validate_error(
            api_client.adjudicate_background(
                clearance["id"], adjudicate_background_payload(outcome="ADVERSE"),
                make_legal_reviewer_headers(LEGAL_REVIEWER_BACKGROUND_ID)),
            ApiErrorId.ERR_INVALID_STATE, 409)
        validate_error(
            api_client.determine_suitability(
                clearance["id"], determine_suitability_payload(outcome="UNFAVORABLE"),
                make_legal_reviewer_headers(LEGAL_REVIEWER_SUITABILITY_ID)),
            ApiErrorId.ERR_INVALID_STATE, 409)
        final = get_legal_clearance(bundle["application"]["id"])
        assert final["overall_status"] == "CLEARED"
        assert_legal_overall_consistency(final)


class TestSegregationOfDuties:
    def test_suitability_self_approval_rejected(self):
        """PRD §3.6: "Segregation of duties forbids the same officer from
        holding both pens: when the caller's `X-User-ID` equals the
        clearance's `background_adjudicated_by`, the attempt is rejected with
        `ERR_SUITABILITY_SELF_APPROVAL` (HTTP 422)."
        PRD §3.6: "A `FAVORABLE` outcome with a `CLEAR` background completes
        the clearance, `overall_status` becoming `CLEARED`, while an
        `UNFAVORABLE` outcome denies it and fires the identical denial
        cascade, voiding any in-flight medical clearance on the way out."

        Design: Corner/validations/suitability_self_approval_rejected
        """
        set_clock(DEFAULT_CLOCK_START)
        program, opening = create_program_with_opening()
        ana = create_applicant()
        bundle = run_applicant_to_accepted(ana, opening)
        clearance = bundle["legal_clearance"]
        adjudicate_background(clearance["id"], outcome="CLEAR",
                              reviewer_id=LEGAL_REVIEWER_BACKGROUND_ID)

        # The background adjudicator cannot also determine suitability.
        validate_error(
            api_client.determine_suitability(
                clearance["id"], determine_suitability_payload(outcome="FAVORABLE"),
                make_legal_reviewer_headers(LEGAL_REVIEWER_BACKGROUND_ID)),
            ApiErrorId.ERR_SUITABILITY_SELF_APPROVAL, 422)
        mid = get_legal_clearance(bundle["application"]["id"])
        assert mid["suitability_status"] == "PENDING"

        # A different reviewer succeeds.
        determine_suitability(clearance["id"], outcome="FAVORABLE",
                              reviewer_id=LEGAL_REVIEWER_SUITABILITY_ID)
        done = get_legal_clearance(bundle["application"]["id"])
        assert done["suitability_status"] == "FAVORABLE"
        assert done["suitability_decided_by"] == LEGAL_REVIEWER_SUITABILITY_ID
        assert done["background_adjudicated_by"] == LEGAL_REVIEWER_BACKGROUND_ID
        assert done["suitability_decided_by"] != done["background_adjudicated_by"]
        assert done["overall_status"] == "CLEARED"
        assert_legal_overall_consistency(done)
