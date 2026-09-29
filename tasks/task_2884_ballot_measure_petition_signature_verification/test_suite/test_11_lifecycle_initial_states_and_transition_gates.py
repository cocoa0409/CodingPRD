"""State-machine behaviour: initial states, the validation cascade, the
registration and clearance gates, and refusals from states that admit nothing.

Every transition in this API is guarded, and the guards are deliberately
distinguishable: four different 409 codes separate a round-dimension refusal
from a batch-dimension one, from a re-invalidation, from a circulator-dimension
one, and the four 422 registration signals each name the single precondition
that fired.

Adjudication recorded here rather than weakened silently: the design index also
asks for `checked_signature_count == 5` on a batch whose round has not yet been
tallied. PRD §3.6 defines that field but ties its recomputation to the tally
("County reimbursement accrues at exactly those moments, once per batch the
round touched"), and §2.10's immediate-recompute rule is written about the
*petition's* counters, not a batch's. The pre-tally value of that one field is
therefore not uniquely derivable from the PRD and is not asserted; the
companion claim of the same bullet — that `verification_cost_cents` is still 0
before any tally — is pinned by §3.4 and §3.6 and is asserted.
"""
from test_helpers import (
    api_client,
    assert_instants_equal,
    add_line,
    create_registered_circulator,
    file_batch,
    file_petition,
    make_circulator_agent_headers,
    make_county_clerk_headers,
    make_examiner_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    read_batch,
    read_circulator,
    read_line,
    read_petition,
    read_round,
    register_circulator,
    register_standard,
    setup_circulation_ready,
    submit_petition,
    validate_error,
    validate_line,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import (
    close_circulation,
    decide_format,
    file_batch_with_lines,
    invalidate_batch,
    issue_determination,
    open_round,
    prepare_title_summary,
    record_training,
    revoke_circulator,
    set_clock,
    tally_round,
    void_round,
)

FILING_CLOCK = "2026-08-10T00:00:00Z"
FILING_STAMP = "2026-08-10T00:00:00.000Z"

CASCADE_VOTERS = [
    {"voter_id_number": "VA1", "county_code": "ALPHA", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "county_code": "ALPHA", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA3", "county_code": "ALPHA", "registration_status": "ACTIVE"},
    {"voter_id_number": "VB1", "county_code": "BRAVO", "registration_status": "ACTIVE"},
]

CASCADE_LINES = [
    {"line_number": 1, "claimed_voter_id_number": "VA1", "signature_hash": "H-VA1"},
    {"line_number": 2, "claimed_voter_id_number": "VA2", "signature_hash": "H-BAD2"},
    {"line_number": 3, "claimed_voter_id_number": "VB1", "signature_hash": "H-VB1"},
    {"line_number": 4, "claimed_voter_id_number": "VX9", "signature_hash": "H-VX9"},
    {"line_number": 5, "claimed_voter_id_number": "VA3", "signature_hash": "H-BAD3"},
]


def _cascade_world():
    """A census round over five lines engineered so each declared invalid
    reason fires exactly once."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides={"jurisdiction_code": "SOS-VAL"},
        counties=[("ALPHA", 20), ("BRAVO", 40)],
        voters=CASCADE_VOTERS,
    )
    set_clock(FILING_CLOCK)
    record = file_batch_with_lines(world, CASCADE_LINES, county_code="ALPHA")
    close_circulation(world["petition"]["id"])
    world["round"] = open_round(world["petition"]["id"], round_type="RANDOM_SAMPLE")
    return world, record


class TestChildEntitiesStartInDeclaredInitialState:
    """A new assignment is `ACTIVE`, a new batch is `RECEIVED` with every
    counter at 0, and a new line is `PENDING` with every pointer null."""

    def test_a_filed_batch_is_received_with_every_counter_at_zero(self):
        """The assignment behind it is `ACTIVE` with `paid_disclosure_ack`
        false, and the batch's `filed_at` is the logical clock at filing.

        PRD §3.4: "Filing stamps `filed_at` from the logical clock — the
        secondary key of the duplicate keeper ranking — and starts the batch at
        `RECEIVED` with `raw_count` 0, `accepted_raw_count` 0,
        `format_defect_count` 0, `checked_signature_count` 0 and
        `verification_cost_cents` 0, with `affidavit_notary_id`,
        `status_before_invalidation` and `invalidation_reason` all null."

        Design: Corner/state_machines/child_entities_start_in_declared_initial_state
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-INI"},
            counties=[("ALPHA", 20)],
            voters=["VA1"],
            measure_subject_codes=("ELECTIONS",),
        )

        assignment = world["assignments"]["c1"]
        assert assignment["status"] == "ACTIVE", "PRD §3.3: an assignment begins at ACTIVE"
        assert assignment["paid_disclosure_ack"] is False, (
            "PRD §3.3: paid_disclosure_ack accepts false when omitted"
        )

        set_clock(FILING_CLOCK)
        batch = file_batch(
            world["petition"]["id"],
            world["circulators"]["c1"]["id"],
            world["counties"]["ALPHA"]["id"],
        )

        assert batch["status"] == "RECEIVED"
        assert batch["raw_count"] == 0
        assert batch["accepted_raw_count"] == 0
        assert batch["format_defect_count"] == 0
        assert batch["checked_signature_count"] == 0
        assert batch["verification_cost_cents"] == 0
        assert batch["affidavit_notary_id"] is None
        assert batch["status_before_invalidation"] is None
        assert batch["invalidation_reason"] is None
        assert batch["is_supplemental"] is False
        assert batch["cure_period_id"] is None
        assert_instants_equal(batch["filed_at"], FILING_STAMP)

    def test_a_new_line_is_pending_and_feeds_the_raw_leg_alone(self):
        """The line starts `PENDING` with every pointer null, and the batch it
        joined moves `raw_count` to 1 while `accepted_raw_count` stays 0.

        PRD §3.4: "Each line begins with `validation_status` at `PENDING`,
        `in_sample` `false`, and `matched_voter_record_id`,
        `duplicate_of_signature_id`, `validated_in_round_id`,
        `status_before_void` and `void_reason` all null, with
        `manual_match_override_applied` `false`."

        Design: Corner/state_machines/child_entities_start_in_declared_initial_state
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={"jurisdiction_code": "SOS-IN2"},
            counties=[("ALPHA", 20)],
            voters=["VA1"],
        )
        set_clock(FILING_CLOCK)
        batch = file_batch(
            world["petition"]["id"],
            world["circulators"]["c1"]["id"],
            world["counties"]["ALPHA"]["id"],
        )

        line = add_line(batch["id"], line_number=1, claimed_voter_id_number="VA1")

        assert line["validation_status"] == "PENDING"
        assert line["in_sample"] is False
        assert line["manual_match_override_applied"] is False
        for pointer in (
            "matched_voter_record_id",
            "duplicate_of_signature_id",
            "validated_in_round_id",
            "status_before_void",
            "void_reason",
        ):
            assert line[pointer] is None, f"{pointer} must start null"

        after = read_batch(batch["id"])
        assert after["raw_count"] == 1
        assert after["accepted_raw_count"] == 0, (
            "PRD §3.4: accepted_raw_count is exactly 0 while the batch sits in RECEIVED"
        )
        assert after["status"] == "RECEIVED"

        petition = read_petition(world["petition"]["id"])
        assert petition["raw_signature_count"] == 1
        assert petition["accepted_raw_total"] == 0, (
            "a RECEIVED batch feeds the raw leg only"
        )


class TestSignatureValidationCascadeOutcomes:
    """Five lines under one census round exercise each declared invalid reason
    exactly once, in the cascade's declared order."""

    def test_each_declared_invalid_reason_fires_once_in_cascade_order(self):
        """A BRAVO voter on an ALPHA sheet is `INVALID_WRONG_COUNTY` even
        though its hash also matches, and an unknown claimed id leaves
        `matched_voter_record_id` null.

        PRD §3.5: "First, the line's `claimed_voter_id_number` is resolved
        against the roll's `voter_id_number`. If no roll entry exists at all,
        the line becomes `INVALID_NOT_REGISTERED` and `matched_voter_record_id`
        stays null. Second, if a roll entry was found but its
        `registration_status` is anything other than `ACTIVE`, the line likewise
        becomes `INVALID_NOT_REGISTERED`, but `matched_voter_record_id` is set
        to the record that was found. Third, if the matched voter's `county_id`
        differs from the batch's `county_id`, the line becomes
        `INVALID_WRONG_COUNTY` with `matched_voter_record_id` set — the voter is
        real and active, just registered somewhere else. Fourth, the line's
        `signature_hash` is compared with the matched voter's
        `signature_on_file_hash`; if they differ and `manual_match_override` is
        absent or `false`, the line becomes `INVALID_SIGNATURE_MISMATCH` with
        `matched_voter_record_id` set, whereas if the clerk supplied
        `manual_match_override` as `true` the mismatch is accepted,
        `manual_match_override_applied` is set to `true` on the line, and the
        cascade continues."

        Design: Corner/state_machines/signature_validation_produces_each_declared_invalid_reason
        """
        world, record = _cascade_world()
        alpha_id = world["counties"]["ALPHA"]["id"]
        lines = {line["line_number"]: line for line in record["lines"]}

        assert world["round"]["sample_size"] == 5, (
            "sample_pct_bps 10000 over a five-line pool is a census"
        )

        first = validate_line(lines[1]["id"], alpha_id)
        assert first["validation_status"] == "VALID"
        assert first["matched_voter_record_id"] == world["voters"]["VA1"]["id"]

        second = validate_line(lines[2]["id"], alpha_id)
        assert second["validation_status"] == "INVALID_SIGNATURE_MISMATCH"
        assert second["matched_voter_record_id"] == world["voters"]["VA2"]["id"], (
            "the voter resolved; only the hash failed"
        )

        third = validate_line(lines[3]["id"], alpha_id)
        assert third["validation_status"] == "INVALID_WRONG_COUNTY", (
            "the county check runs before the hash check"
        )
        assert third["matched_voter_record_id"] == world["voters"]["VB1"]["id"]

        fourth = validate_line(lines[4]["id"], alpha_id)
        assert fourth["validation_status"] == "INVALID_NOT_REGISTERED"
        assert fourth["matched_voter_record_id"] is None, (
            "no roll entry exists at all, so the pointer stays null"
        )

        fifth = validate_line(lines[5]["id"], alpha_id, manual_match_override=True)
        assert fifth["validation_status"] == "VALID"
        assert fifth["manual_match_override_applied"] is True
        assert fifth["matched_voter_record_id"] == world["voters"]["VA3"]["id"]

        assert read_line(lines[2]["id"])["manual_match_override_applied"] is False, (
            "the override applies only to the line that carried the flag"
        )

    def test_the_five_outcomes_move_credibility_and_leave_cost_untouched(self):
        """Three invalid of five examined lines score the circulator at 7000
        under the provisional variant, and no cost has accrued yet.

        PRD §3.9: "Under the **provisional** variant, used while
        `misconduct_strike_count` is 0, the raw score is 10000 less the invalid
        rate multiplied by 5000 and divided by 10000 with the remainder
        discarded, less a flat 500 basis points for each `FraudReferral` of this
        circulator whose `status` is `OPENED` or `REFERRED_TO_AG` — an unproven
        allegation weighs something, but the invalid rate weighs only half."

        Design: Corner/state_machines/signature_validation_produces_each_declared_invalid_reason
        """
        world, record = _cascade_world()
        alpha_id = world["counties"]["ALPHA"]["id"]
        lines = {line["line_number"]: line for line in record["lines"]}

        for number in (1, 2, 3, 4):
            validate_line(lines[number]["id"], alpha_id)
        validate_line(lines[5]["id"], alpha_id, manual_match_override=True)

        circulator = read_circulator(world["circulators"]["c1"]["id"])
        assert circulator["misconduct_strike_count"] == 0
        assert circulator["credibility_score_bps"] == 7000, (
            "checked 5, invalid 3, rate floor(3 * 10000 / 5) == 6000, "
            "10000 - floor(6000 * 5000 / 10000) == 7000"
        )

        batch = read_batch(record["batch"]["id"])
        assert batch["verification_cost_cents"] == 0, (
            "PRD §3.6: reimbursement accrues at the tally, not at validation"
        )
        petition = read_petition(world["petition"]["id"])
        assert petition["verification_cost_accrued_cents"] == 0


class TestCirculatorRegistrationPreconditions:
    """Each of the four preconditions guarding the two registration
    transitions is violated in isolation and names itself."""

    def test_training_gates_the_affidavit_and_only_two_courses_count(self):
        """An affidavit from `PENDING_TRAINING` is `ERR_TRAINING_NOT_COMPLETE`,
        an unapproved course is `ERR_TRAINING_COURSE_NOT_APPROVED`, and an
        unsworn affidavit from `TRAINED` is `ERR_AFFIDAVIT_NOT_SWORN`.

        PRD §3.3: "Recording training moves the circulator from
        `PENDING_TRAINING` to `TRAINED`, stamps `training_completed_at` from the
        logical clock, and records the supplied `training_course_code`; a code
        outside the approved pair `SOS-CIRC-101` and `SOS-CIRC-201` is refused
        with `ERR_TRAINING_COURSE_NOT_APPROVED`, and attempting to record
        training for a circulator that has already moved past
        `PENDING_TRAINING` is refused with `ERR_INVALID_CIRCULATOR_STATE`."

        Design: Corner/state_machines/circulator_registration_precondition_rejections
        """
        set_clock(CLOCK_EPOCH)
        circulator = register_circulator(full_name="Cora Carter")
        assert circulator["paid_disclosure_on_file"] is True

        validate_error(
            api_client.file_affidavit(
                circulator["id"], {"sworn": True}, make_sos_admin_headers()
            ),
            "ERR_TRAINING_NOT_COMPLETE",
            422,
        )

        validate_error(
            api_client.record_training(
                circulator["id"],
                {"training_course_code": "SOS-CIRC-999"},
                make_sos_admin_headers(),
            ),
            "ERR_TRAINING_COURSE_NOT_APPROVED",
            422,
        )
        after_bad_course = read_circulator(circulator["id"])
        assert after_bad_course["registration_status"] == "PENDING_TRAINING"
        assert after_bad_course["training_course_code"] is None

        trained = record_training(circulator["id"], training_course_code="SOS-CIRC-101")
        assert trained["registration_status"] == "TRAINED"
        assert trained["training_course_code"] == "SOS-CIRC-101"
        assert_instants_equal(trained["training_completed_at"], "2026-08-01T00:00:00.000Z")

        validate_error(
            api_client.file_affidavit(
                circulator["id"], {"sworn": False}, make_sos_admin_headers()
            ),
            "ERR_AFFIDAVIT_NOT_SWORN",
            422,
        )
        after_unsworn = read_circulator(circulator["id"])
        assert after_unsworn["registration_status"] == "TRAINED"
        assert after_unsworn["affidavit_filed_at"] is None

    def test_a_paid_circulator_needs_its_disclosure_on_file_first(self):
        """With training complete and the affidavit sworn, only
        `ERR_PAID_DISCLOSURE_MISSING` can be firing; filing the disclosure
        clears it and the agent may then swear for itself.

        PRD §3.3: "The circulator must actually be in `TRAINED`, else
        `ERR_TRAINING_NOT_COMPLETE`. `paid_disclosure_on_file` must be `true`,
        else `ERR_PAID_DISCLOSURE_MISSING` — the case a paid circulator hits
        when either `employer_name` or `disclosure_document_id` is still null.
        And the request's `sworn` flag must be `true`, else
        `ERR_AFFIDAVIT_NOT_SWORN`."

        Design: Corner/state_machines/circulator_registration_precondition_rejections
        """
        set_clock(CLOCK_EPOCH)
        paid = register_circulator(
            full_name="Paul Paid", residency_state_code="NV", is_paid=True
        )
        assert paid["paid_disclosure_on_file"] is False, (
            "a paid circulator with no employer and no document is not on file"
        )

        trained = record_training(paid["id"], training_course_code="SOS-CIRC-201")
        assert trained["registration_status"] == "TRAINED"

        validate_error(
            api_client.file_affidavit(paid["id"], {"sworn": True}, make_sos_admin_headers()),
            "ERR_PAID_DISCLOSURE_MISSING",
            422,
        )

        disclosed = validate_success(
            api_client.file_paid_disclosure(
                paid["id"],
                {"disclosure_document_id": "DISC-1", "employer_name": "Signatures Inc"},
                make_sos_admin_headers(),
            )
        )
        assert disclosed["paid_disclosure_on_file"] is True
        assert disclosed["disclosure_document_id"] == "DISC-1"
        assert disclosed["employer_name"] == "Signatures Inc"

        registered = validate_success(
            api_client.file_affidavit(
                paid["id"], {"sworn": True}, make_circulator_agent_headers(paid["id"])
            )
        )
        assert registered["registration_status"] == "REGISTERED"
        assert_instants_equal(registered["affidavit_filed_at"], "2026-08-01T00:00:00.000Z")


class TestSingleSubjectAndTitleSummaryClearanceGates:
    """The two gates between `FORMAT_REVIEW` and the street: one subject code
    at approval, and both title and summary written before clearance."""

    def test_approval_demands_exactly_one_subject_code(self):
        """Two subject codes are accepted at create and at submit, and refused
        only by the examiner's `APPROVE`.

        PRD §3.2: "Approval carries the single-subject rule with it: the
        petition's `measure_subject_codes` must hold exactly one code at the
        moment of approval, and a petition still carrying two or more subject
        codes is refused with `ERR_SINGLE_SUBJECT_VIOLATION`."

        Design: Corner/state_machines/single_subject_and_title_summary_clearance_gates
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(jurisdiction_code="SOS-GAT")

        multi = file_petition(
            standard["id"],
            measure_subject_codes=("TAX", "HEALTH"),
            submitted_title="Two Subject Measure",
        )
        submitted = submit_petition(multi["id"])
        assert submitted["status"] == "FORMAT_REVIEW"
        assert submitted["measure_subject_codes"] == ["TAX", "HEALTH"]

        validate_error(
            api_client.format_decision(
                multi["id"],
                {"decision": "APPROVE", "reviewer_note": "two subjects"},
                make_examiner_headers(),
            ),
            "ERR_SINGLE_SUBJECT_VIOLATION",
            422,
        )

        after = read_petition(multi["id"])
        assert after["status"] == "FORMAT_REVIEW", "a refused approval is not a rejection"
        assert after["format_review_round"] == 0, (
            "the round counter only moves on a recorded decision"
        )

    def test_clearance_waits_for_the_title_then_freezes_the_threshold(self):
        """Clearance is refused while either field is null, the title write is
        a `TITLE_PENDING` self-loop, and clearance freezes the requirement and
        the deadline.

        PRD §3.2: "Both `official_title` and `official_summary` must be non-null
        by then; a petition sent for clearance while either is still null is
        refused with `ERR_TITLE_SUMMARY_MISSING`."

        Design: Corner/state_machines/single_subject_and_title_summary_clearance_gates
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(jurisdiction_code="SOS-GA2")
        petition = file_petition(
            standard["id"],
            measure_subject_codes=("TAX",),
            submitted_title="One Subject Measure",
        )
        submit_petition(petition["id"])
        approved = decide_format(petition["id"], decision="APPROVE")
        assert approved["status"] == "TITLE_PENDING"

        validate_error(
            api_client.clear_for_circulation(petition["id"], make_sos_admin_headers()),
            "ERR_TITLE_SUMMARY_MISSING",
            422,
        )
        blocked = read_petition(petition["id"])
        assert blocked["status"] == "TITLE_PENDING"
        assert blocked["cleared_at"] is None

        titled = prepare_title_summary(
            petition["id"],
            official_title="The Tax Fairness Act",
            official_summary="Adjusts the property tax base.",
        )
        assert titled["status"] == "TITLE_PENDING", "the title write is a self-loop"
        assert titled["official_title"] == "The Tax Fairness Act"
        assert titled["official_summary"] == "Adjusts the property tax base."

        cleared = validate_success(
            api_client.clear_for_circulation(petition["id"], make_sos_admin_headers())
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["required_valid_signatures"] == 2, (
            "ceil(100 * 200 / 10000) == 2"
        )
        assert_instants_equal(cleared["cleared_at"], "2026-08-01T00:00:00.000Z")
        assert_instants_equal(cleared["circulation_deadline"], "2027-01-28T00:00:00.000Z")


class TestPetitionSubmissionIsNotIdempotent:
    """Replaying `submit` against a petition already under review is refused
    and, crucially, does not consume a review round."""

    def test_a_replayed_submit_is_refused_and_consumes_no_review_round(self):
        """The second submit is `ERR_INVALID_PETITION_STATE` and leaves
        `format_review_round` and `updated_at` exactly where they were.

        PRD §3.2: "Submitting the petition for review moves it from `DRAFT` to
        `FORMAT_REVIEW`, and the same act moves it from `FORMAT_REJECTED` back
        to `FORMAT_REVIEW` — this is the revision cycle."

        Design: Corner/state_machines/petition_submit_twice_second_attempt_rejected
        """
        set_clock(CLOCK_EPOCH)
        standard = register_standard(jurisdiction_code="SOS-RTY")
        petition = file_petition(standard["id"], submitted_title="Retry Measure")
        assert petition["status"] == "DRAFT"
        assert petition["format_review_round"] == 0

        first = submit_petition(petition["id"])
        assert first["status"] == "FORMAT_REVIEW"
        assert first["format_review_round"] == 0, (
            "PRD §3.2: the counter is incremented by every format decision, not by submission"
        )
        assert_instants_equal(first["updated_at"], "2026-08-01T00:00:00.000Z")

        validate_error(
            api_client.submit_petition(petition["id"], make_proponent_headers()),
            "ERR_INVALID_PETITION_STATE",
            409,
        )

        after = read_petition(petition["id"])
        assert after["status"] == "FORMAT_REVIEW"
        assert after["format_review_round"] == 0
        assert_instants_equal(after["updated_at"], first["updated_at"])
        assert after["version"] == first["version"], "a refused replay is not a mutation"


TRANSITION_VOTERS = [
    {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA3", "registration_status": "INACTIVE"},
    {"voter_id_number": "VA4", "registration_status": "INACTIVE"},
]


def _tallied_four_line_world(jurisdiction_code):
    """Four matching-hash lines, two of them naming INACTIVE voters, examined
    by one census round and tallied SUFFICIENT."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides={
            "jurisdiction_code": jurisdiction_code,
            "sufficiency_upper_bps": 10000,
        },
        counties=[("ALPHA", 20)],
        voters=TRANSITION_VOTERS,
    )
    set_clock(FILING_CLOCK)
    record = file_batch_with_lines(world, ["VA1", "VA2", "VA3", "VA4"])
    close_circulation(world["petition"]["id"])
    world["round"] = open_round(world["petition"]["id"], round_type="RANDOM_SAMPLE")
    alpha_id = world["counties"]["ALPHA"]["id"]
    for line in record["lines"]:
        validate_line(line["id"], alpha_id)
    world["round"] = tally_round(world["round"]["id"])
    record["batch"] = read_batch(record["batch"]["id"])
    return world, record


class TestTransitionsRefusedFromStatesThatDoNotAdmitThem:
    """Nine transitions are attempted from the wrong state, and the four
    distinct 409 codes name the dimension that refused."""

    def test_the_round_dimension_refuses_a_second_tally_and_a_second_void(self):
        """Both a re-tally of a `CLOSED` round and a re-void of a `VOIDED` one
        are `ERR_INVALID_ROUND_STATE`.

        PRD §3.6: "The round must be `OPEN` — tallying one that is not is
        refused with `ERR_INVALID_ROUND_STATE` — and every line the round
        selected must have moved off `PENDING`, else the tally is refused with
        `ERR_ROUND_HAS_PENDING_SIGNATURES`."

        Design: Corner/state_machines/invalid_from_state_rejections_across_round_batch_and_circulator
        """
        world, _ = _tallied_four_line_world("SOS-TR1")
        round_id = world["round"]["id"]
        assert world["round"]["status"] == "CLOSED"
        assert world["round"]["determination"] == "SUFFICIENT", (
            "projected 2 at an upper gate of 2 is SUFFICIENT"
        )

        validate_error(
            api_client.tally_round(round_id, make_examiner_headers()),
            "ERR_INVALID_ROUND_STATE",
            409,
        )

        voided = void_round(round_id, voided_reason="examiner error")
        assert voided["status"] == "VOIDED", "a CLOSED round is voidable while the petition lives"

        validate_error(
            api_client.void_round(
                round_id, {"voided_reason": "again"}, make_sos_admin_headers()
            ),
            "ERR_INVALID_ROUND_STATE",
            409,
        )
        assert read_round(round_id)["status"] == "VOIDED"

    def test_the_batch_dimension_separates_a_wrong_state_from_a_terminal_one(self):
        """A second affidavit verification and a late line are
        `ERR_INVALID_BATCH_STATE`, while a second invalidation is the dedicated
        `ERR_BATCH_ALREADY_TERMINAL`.

        PRD §3.9: "A `SosAdmin` invalidates a batch with a mandatory
        `invalidation_reason`; the batch must not already be `REJECTED_FORMAT`
        or `INVALIDATED`, else the request is refused with
        `ERR_BATCH_ALREADY_TERMINAL`."

        Design: Corner/state_machines/invalid_from_state_rejections_across_round_batch_and_circulator
        """
        world, record = _tallied_four_line_world("SOS-TR2")
        batch_id = record["batch"]["id"]
        county_id = world["counties"]["ALPHA"]["id"]
        assert record["batch"]["status"] == "SAMPLED"

        validate_error(
            api_client.verify_affidavit(
                batch_id,
                {"affidavit_notary_id": "NOT-2"},
                make_county_clerk_headers(county_id),
            ),
            "ERR_INVALID_BATCH_STATE",
            409,
        )
        assert read_batch(batch_id)["affidavit_notary_id"] == "NOT-1"

        void_round(world["round"]["id"], voided_reason="examiner error")
        restored = read_batch(batch_id)
        assert restored["status"] == "AFFIDAVIT_VERIFIED", (
            "PRD §3.9: voiding restores every batch the round touched"
        )

        validate_error(
            api_client.add_signature(
                batch_id,
                {
                    "line_number": 5,
                    "signer_name": "Late Larry",
                    "claimed_voter_id_number": "VA1",
                    "signed_on": "2026-08-05T00:00:00Z",
                    "signature_hash": "H-VA1",
                },
                make_proponent_headers(),
            ),
            "ERR_INVALID_BATCH_STATE",
            409,
        )
        assert read_batch(batch_id)["raw_count"] == 4

        invalidated = invalidate_batch(batch_id, invalidation_reason="clerical strike")
        assert invalidated["status"] == "INVALIDATED"
        assert invalidated["status_before_invalidation"] == "AFFIDAVIT_VERIFIED"

        validate_error(
            api_client.invalidate_batch(
                batch_id, {"invalidation_reason": "again"}, make_sos_admin_headers()
            ),
            "ERR_BATCH_ALREADY_TERMINAL",
            409,
        )

    def test_the_circulator_dimension_collapses_four_probes_onto_one_code(self):
        """Suspending from `PENDING_TRAINING`, reinstating a `REGISTERED`
        circulator, re-recording training and re-revoking are all
        `ERR_INVALID_CIRCULATOR_STATE`.

        PRD §2.11: "The signals are `ERR_INVALID_PETITION_STATE`,
        `ERR_INVALID_BATCH_STATE`, `ERR_BATCH_ALREADY_TERMINAL`,
        `ERR_INVALID_ROUND_STATE`, `ERR_ROUND_ALREADY_OPEN`,
        `ERR_INVALID_CIRCULATOR_STATE`, `ERR_INVALID_CHALLENGE_STATE`,
        `ERR_REFERRAL_NOT_WITH_AG` and `ERR_CHALLENGE_ALREADY_FILED`, all HTTP
        409."

        Design: Corner/state_machines/invalid_from_state_rejections_across_round_batch_and_circulator
        """
        set_clock(CLOCK_EPOCH)
        trainee = register_circulator(full_name="Trina Trainee")
        registered = create_registered_circulator(full_name="Cora Carter")
        assert trainee["registration_status"] == "PENDING_TRAINING"
        assert registered["registration_status"] == "REGISTERED"

        validate_error(
            api_client.suspend_circulator(
                trainee["id"], make_sos_admin_headers(), {"reason": "from PENDING_TRAINING"}
            ),
            "ERR_INVALID_CIRCULATOR_STATE",
            409,
        )
        assert read_circulator(trainee["id"])["registration_status"] == "PENDING_TRAINING"

        validate_error(
            api_client.reinstate_circulator(registered["id"], make_sos_admin_headers()),
            "ERR_INVALID_CIRCULATOR_STATE",
            409,
        )

        validate_error(
            api_client.record_training(
                registered["id"],
                {"training_course_code": "SOS-CIRC-201"},
                make_sos_admin_headers(),
            ),
            "ERR_INVALID_CIRCULATOR_STATE",
            409,
        )
        assert read_circulator(registered["id"])["training_course_code"] == "SOS-CIRC-101"

        revoked = revoke_circulator(registered["id"], reason="misconduct")
        assert revoked["registration_status"] == "REVOKED"

        validate_error(
            api_client.revoke_circulator(
                registered["id"], make_sos_admin_headers(), {"reason": "again"}
            ),
            "ERR_INVALID_CIRCULATOR_STATE",
            409,
        )
        assert read_circulator(registered["id"])["registration_status"] == "REVOKED"


class TestCertifiedPetitionLocksEveryLaterWrite:
    """`CERTIFIED` is terminal, and the lock is enforced on the petition rather
    than on each child's own status."""

    def test_five_write_families_all_bounce_off_a_certified_petition(self):
        """Filing signatures, opening a round, voiding the certifying round,
        opening a cure period and re-deciding all return
        `ERR_INVALID_PETITION_STATE`, and the ledger is untouched.

        PRD §3.2: "`CERTIFIED` and `FAILED` are terminal: no further transition
        leaves them, and no operation that would mutate the petition is accepted
        once it is in either, which is refused with
        `ERR_INVALID_PETITION_STATE`."

        Design: Corner/state_machines/certified_petition_locks_every_later_write
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={
                "jurisdiction_code": "SOS-LCK",
                "signature_pct_bps": 100,
                "sufficiency_upper_bps": 10000,
            },
            counties=[("ALPHA", 20)],
            voters=[{"voter_id_number": "VA1", "registration_status": "ACTIVE"}],
        )
        petition_id = world["petition"]["id"]
        assert world["petition"]["required_valid_signatures"] == 1, (
            "ceil(100 * 100 / 10000) is one signature"
        )

        set_clock(FILING_CLOCK)
        record = file_batch_with_lines(world, ["VA1"])
        close_circulation(petition_id)
        opened = open_round(petition_id, round_type="RANDOM_SAMPLE")
        validate_line(record["lines"][0]["id"], world["counties"]["ALPHA"]["id"])
        tallied = tally_round(opened["id"])

        assert tallied["determination"] == "SUFFICIENT"
        assert tallied["tallied_by_examiner_id"] == "exam-1"
        assert tallied["validity_rate_bps"] == 10000
        assert tallied["projected_valid_count"] == 1

        certified = issue_determination(petition_id, determination="CERTIFY")
        assert certified["status"] == "CERTIFIED"
        assert_instants_equal(certified["updated_at"], FILING_STAMP)
        assert certified["projected_valid_count"] == 1
        assert certified["verification_cost_accrued_cents"] == 5, (
            "one checked line at 4750 millicents rounds half-up to 5 cents"
        )
        assert certified["qualifying_county_count"] == 1

        validate_error(
            api_client.file_signatures(petition_id, make_proponent_headers()),
            "ERR_INVALID_PETITION_STATE",
            409,
        )
        validate_error(
            api_client.create_verification_round(
                petition_id, {"round_type": "FULL_CHECK"}, make_examiner_headers()
            ),
            "ERR_INVALID_PETITION_STATE",
            409,
        )
        rounds, meta = validate_paginated(
            api_client.list_verification_rounds(
                make_examiner_headers(), params={"petition_id": petition_id}
            )
        )
        assert meta["total_count"] == 1, "the refused create left no second round behind"
        assert [row["id"] for row in rounds] == [opened["id"]]

        validate_error(
            api_client.void_round(
                opened["id"],
                {"voided_reason": "post-certification unwind attempt"},
                make_sos_admin_headers(),
            ),
            "ERR_INVALID_PETITION_STATE",
            409,
        )
        assert read_round(opened["id"])["status"] == "CLOSED", (
            "the guard is the petition's terminal status, not the round's own"
        )

        validate_error(
            api_client.create_cure_period(petition_id, make_sos_admin_headers()),
            "ERR_INVALID_PETITION_STATE",
            409,
        )
        validate_error(
            api_client.issue_determination(
                petition_id, {"determination": "FAIL"}, make_examiner_headers("exam-2")
            ),
            "ERR_INVALID_PETITION_STATE",
            409,
        )

        after = read_petition(petition_id)
        assert after == certified, (
            "five refusals must leave the certified petition byte-identical"
        )
