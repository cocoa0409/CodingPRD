"""Declared state-machine transitions: the happy-path moves and their pinned
side effects, the refusals that guard the invalid ones, and the cascades a
single transition fires on its children.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import (
    close_term_payload,
    create_attempt_payload,
    create_transcript_record_payload,
    submit_attempt_payload,
)
from test_helpers.test_users import make_student_headers

SECOND_TERM_START_UTC = "2026-12-01T00:00:00.000Z"
SECOND_TERM_END_UTC = "2027-03-01T00:00:00.000Z"
WITHDRAW_CLOCK_UTC = "2026-09-11T00:00:00.000Z"
SECOND_SUSPENSION_UTC = "2026-09-10T00:00:00.000Z"
REPLACEMENT_DUE_UTC = "2026-09-15T00:00:00.000Z"


def _draft_program_with_one_active_competency():
    """A DRAFT program carrying exactly one ACTIVE competency, so publication's
    map precondition is satisfied."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    assert program["status"] == "DRAFT"
    competency = fx.create_competency(program["id"])
    assert competency["status"] == "ACTIVE"
    return program, competency


def test_publishing_a_draft_program_stamps_the_clock_and_recounts_the_map():
    """Publication is a 200 that moves DRAFT to PUBLISHED, stamps the logical
    clock rather than wall time, recounts the map at 1 and increments the version
    the draft carried a moment earlier.

    PRD: "On success the program records `published_at_utc` as the logical clock,
    recomputes `competency_count`, and increments its `version`."

    Design: Corner/state_machines/program_publish_moves_draft_to_published
    """
    program, _competency = _draft_program_with_one_active_competency()
    # Adding the competency already mutated the program: "Creation also increments
    # the owning program's `competency_count` and its `version`." So the baseline
    # publication increments is the draft's version as it stands now.
    version_before_publication = fx.refresh_program(program["id"])["version"]

    published = validate_success(
        api_client.publish_program(program["id"], fx.REGISTRAR), 200
    )
    A.assert_program(published)
    assert published["status"] == "PUBLISHED"
    A.assert_instant_equals(published["published_at_utc"], BASE_CLOCK_UTC,
                            "published_at_utc")
    assert published["competency_count"] == 1
    assert published["version"] == version_before_publication + 1


def test_publishing_an_already_published_program_neither_restamps_nor_bumps():
    """Publication is not idempotent-success: the second identical call is a
    conflict, and the stamp taken at the first publication survives untouched
    even though the clock has since moved on.

    PRD: "It requires the program to be a draft — a second publication of an
    already-published program is refused with `ERR_PROGRAM_ALREADY_PUBLISHED` —
    and it requires at least one competency to exist under the program with
    `status` `ACTIVE`, because a program with an empty map has nothing to assess."

    Design: Corner/state_machines/program_publish_twice_is_rejected
    """
    program, _competency = _draft_program_with_one_active_competency()
    published = fx.publish_program(program["id"])
    fx.set_clock("2026-09-05T00:00:00.000Z")

    validate_error(
        api_client.publish_program(program["id"], fx.REGISTRAR),
        ApiErrorId.ERR_PROGRAM_ALREADY_PUBLISHED.value, 409,
    )

    after = fx.refresh_program(program["id"])
    A.assert_instant_equals(after["published_at_utc"], BASE_CLOCK_UTC,
                            "published_at_utc")
    # The refused second publication is not a mutation, so the version the first
    # publication left behind must still be the one on the row.
    assert after["version"] == published["version"]


def test_activation_stamps_the_clock_and_leaves_the_progress_axis_alone():
    """The applicant becomes ACTIVE at the logical clock with version 1 rising to
    2, while the independent progress axis stays where enrollment left it.

    PRD: "Activation moves `enrollment_status` from `APPLICANT` to `ACTIVE`,
    requires the student to still be an applicant, requires the owning program to
    be published, sets `activated_at_utc` to the logical clock, and increments the
    student's `version`."

    Design: Corner/state_machines/student_activate_applies_declared_side_effects
    """
    program, _competency = _draft_program_with_one_active_competency()
    program = fx.publish_program(program["id"])
    applicant = fx.create_student(program["id"])
    assert applicant["enrollment_status"] == "APPLICANT"
    assert applicant["version"] == 1

    activated = validate_success(
        api_client.activate_student(applicant["id"], fx.REGISTRAR), 200
    )
    A.assert_student(activated)
    assert activated["enrollment_status"] == "ACTIVE"
    A.assert_instant_equals(activated["activated_at_utc"], BASE_CLOCK_UTC,
                            "activated_at_utc")
    assert activated["sap_status"] == "GOOD_STANDING"
    assert activated["version"] == 2


def test_a_submission_without_the_attestation_leaves_the_attempt_untouched_in_draft():
    """The attestation flag is a hard precondition rather than a stored opinion:
    with it false the submission is refused and nothing about the attempt moves —
    not its status, not its submitted instant, not its hash, not its version.

    PRD: "Because these assessments are unproctored, the attestation is not
    decorative: `integrity_attestation_accepted` must be exactly true and
    `client_fingerprint` must be a non-empty string, or the submission is refused
    with `ERR_ATTESTATION_REQUIRED`."

    Design: Corner/state_machines/attempt_submit_without_attestation_rejected
    """
    ctx = fx.assessment_ready()
    assert ctx["attempt"]["status"] == "DRAFT"

    response = api_client.submit_attempt(
        ctx["attempt"]["id"],
        submit_attempt_payload(artifact_hash="sha256:no-attestation",
                               integrity_attestation_accepted=False,
                               client_fingerprint="fp-no-attestation"),
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ATTESTATION_REQUIRED.value, 422)

    after = fx.refresh_attempt(ctx["attempt"]["id"])
    assert after["status"] == "DRAFT"
    assert after["submitted_at_utc"] is None
    assert after["version"] == 1
    assert after["artifact_hash"] is None
    assert after["integrity_attestation_accepted"] is False


def _term_cancelled_before_it_started():
    """One PENDING term for 375000 cents, closed as CANCELLED on the day it would
    have begun."""
    ctx = fx.base_chain(activate_the_term=False)
    assert ctx["term"]["status"] == "PENDING"
    ctx["closed"] = validate_success(
        api_client.close_subscription_term(
            ctx["term"]["id"], close_term_payload("CANCELLED", BASE_CLOCK_UTC),
            fx.REGISTRAR,
        ),
        200,
    )
    return ctx


def test_cancelling_a_term_that_never_started_refunds_the_whole_tuition():
    """The PENDING close path measures no attendance at all: zero days, zero
    earning, the entire tuition refunded and nothing left charged.

    PRD: "It has no attendance to measure, so it does not run the arithmetic at
    all: `closed_effective_utc` takes the supplied `effective_utc`, `attended_days`
    is 0, `earned_pct` is `0.0000`, `institutional_refund_cents` equals the whole
    `tuition_cents`, `net_institutional_charge_cents` is 0, every scheduled or held
    award on the term is cancelled with `cancelled_amount_cents` equal to
    `scheduled_amount_cents` and `outstanding_amount_cents` driven to 0, and the
    term's `version` increments."

    Design: Corner/state_machines/activate_a_cancelled_term_is_rejected
    """
    ctx = _term_cancelled_before_it_started()
    closed = ctx["closed"]

    assert closed["status"] == "CANCELLED"
    assert closed["attended_days"] == 0
    A.assert_number_equals(closed["earned_pct"], 0.0000, "earned_pct")
    A.assert_cents(closed["institutional_refund_cents"], 375000,
                   "institutional_refund_cents")
    A.assert_cents(closed["net_institutional_charge_cents"], 0,
                   "net_institutional_charge_cents")
    A.assert_instant_equals(closed["closed_effective_utc"], BASE_CLOCK_UTC,
                            "closed_effective_utc")


def test_a_cancelled_term_can_never_be_activated():
    """Activation is not among a cancelled term's outgoing transitions, so the
    request is a conflict and the term stays cancelled with no activation stamp.

    PRD: "Three preconditions apply: the term must be pending, or the request is
    refused with `ERR_TERM_NOT_PENDING`; the student's `enrollment_status` must be
    `ACTIVE`; and no other term of the same student may already be `ACTIVE`,
    because a student subscribes to one period at a time."

    Design: Corner/state_machines/activate_a_cancelled_term_is_rejected
    """
    ctx = _term_cancelled_before_it_started()

    validate_error(
        api_client.activate_subscription_term(ctx["term"]["id"], fx.REGISTRAR),
        ApiErrorId.ERR_TERM_NOT_PENDING.value, 409,
    )

    after = fx.refresh_term(ctx["term"]["id"])
    assert after["status"] == "CANCELLED"
    assert after["activated_at_utc"] is None


def _fresh_attempt():
    """A published rubric on the competency, an active term, and one attempt
    created and nothing more."""
    ctx = fx.base_chain(with_blueprint=True)
    ctx["created"] = validate_success(
        api_client.create_attempt(
            create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"]),
            make_student_headers(ctx["student"]["id"]),
        ),
        201,
    )
    return ctx


def test_a_freshly_opened_attempt_carries_every_score_field_as_null():
    """The initial state is DRAFT at ordinal 1 with the entire scoring half of the
    row still empty and no integrity hold in place.

    PRD: "A fresh attempt carries `artifact_hash` null, `client_fingerprint` null,
    `integrity_attestation_accepted` false, `submitted_at_utc` null,
    `scores_received_count` 0, `final_score_pct` null, `score_variant` null,
    `is_provisional_score` false, `critical_fail` false, `integrity_hold` false,
    `held_from_status` null, `revision_count` 0, `scored_at_utc` null,
    `mastered_at_utc` null, and `cooloff_until_utc` null."

    Design: Corner/state_machines/attempt_starts_in_draft_initial_state
    """
    attempt = _fresh_attempt()["created"]

    A.assert_attempt(attempt)
    assert attempt["status"] == "DRAFT"
    assert attempt["attempt_number"] == 1
    assert attempt["scores_received_count"] == 0
    assert attempt["revision_count"] == 0
    assert attempt["integrity_hold"] is False
    assert attempt["held_from_status"] is None
    assert attempt["final_score_pct"] is None
    assert attempt["score_variant"] is None
    assert attempt["is_provisional_score"] is False
    assert attempt["critical_fail"] is False
    assert attempt["artifact_hash"] is None
    assert attempt["client_fingerprint"] is None
    assert attempt["integrity_attestation_accepted"] is False
    assert attempt["submitted_at_utc"] is None
    assert attempt["scored_at_utc"] is None
    assert attempt["mastered_at_utc"] is None
    assert attempt["cooloff_until_utc"] is None
    assert attempt["version"] == 1


def test_the_new_attempt_pins_the_blueprint_in_force_and_the_active_term():
    """Neither reference is supplied by the caller: the rubric comes from the
    window lookup against the logical clock and the container comes from the
    student's live subscription.

    PRD: "Its `blueprint_id` is resolved by the window lookup of §3.2 against the
    logical clock and is never re-pinned afterwards."

    Design: Corner/state_machines/attempt_starts_in_draft_initial_state
    """
    ctx = _fresh_attempt()

    assert ctx["created"]["blueprint_id"] == ctx["blueprint"]["id"]
    assert ctx["created"]["term_id"] == ctx["term"]["id"]
    assert ctx["created"]["student_id"] == ctx["student"]["id"]
    assert ctx["created"]["competency_id"] == ctx["competency"]["id"]


def _two_transcripts_for_one_student():
    """Two transcript records built back to back for a student who has mastered
    nothing, so both carry zero lines and only their ordering matters."""
    ctx = fx.base_chain(create_the_term=False)
    ctx["first"] = fx.create_transcript(ctx["student"]["id"], purpose="TRANSFER")
    assert ctx["first"]["status"] == "DRAFT"
    ctx["second"] = validate_success(
        api_client.create_transcript_record(
            create_transcript_record_payload(ctx["student"]["id"],
                                             purpose="STUDENT_COPY"),
            fx.REGISTRAR,
        ),
        201,
    )
    return ctx


def test_a_second_transcript_voids_the_first_draft_as_superseded():
    """The newer record is a plain DRAFT while the older one is voided, and the
    reason recorded is supersession rather than a change in the unit total.

    PRD: "The record is created in `DRAFT`, and creating it voids any earlier draft
    record for the same student with `voided_reason` `SUPERSEDED`."

    Design: Corner/state_machines/issuing_a_superseded_transcript_is_locked_out
    """
    ctx = _two_transcripts_for_one_student()

    assert ctx["second"]["status"] == "DRAFT"
    first = fx.refresh_transcript(ctx["first"]["id"])
    A.assert_transcript_record(first)
    assert first["status"] == "VOIDED"
    assert first["voided_reason"] == "SUPERSEDED"
    assert first["issued_at_utc"] is None


def test_the_superseded_transcript_can_no_longer_be_issued():
    """VOIDED is terminal on the certification axis, and the refusal names the
    void specifically rather than the generic already-issued code.

    PRD: "It requires the record to be in `DRAFT` — an already-issued or voided
    record is refused with `ERR_TRANSCRIPT_ALREADY_ISSUED`, and a voided record
    specifically with `ERR_TRANSCRIPT_VOIDED` — and it requires that no integrity
    case of the subject student is `OPEN` or `UNDER_INVESTIGATION`, or it is
    refused with `ERR_TRANSCRIPT_INTEGRITY_PENDING`."

    Design: Corner/state_machines/issuing_a_superseded_transcript_is_locked_out
    """
    ctx = _two_transcripts_for_one_student()

    validate_error(
        api_client.issue_transcript_record(ctx["first"]["id"], fx.REGISTRAR),
        ApiErrorId.ERR_TRANSCRIPT_VOIDED.value, 409,
    )
    assert fx.refresh_transcript(ctx["first"]["id"])["status"] == "VOIDED"


def test_each_suspension_restamps_the_instant_at_the_clock_of_that_suspension():
    """The loop is traversed twice with no cap. The first suspension stamps the
    base instant; after a reinstatement and a nine-day move of the clock the second
    suspension overwrites the stamp with the later instant.

    PRD: "Suspension moves an active student to `SUSPENDED` with a `reason` in the
    payload; it sets `suspended_at_utc` to the logical clock, increments `version`,
    and carries one substantial cascade — every attempt of that student sitting in
    `DRAFT`, `UNDER_REVIEW`, or `ADJUDICATION` is moved to `REVISION_REQUESTED`,
    and every score on those attempts that was still submitted is voided with
    `voided_reason` set to `REVISION_REQUESTED`."

    Design: Corner/state_machines/student_suspend_reinstate_cycle_repeats
    """
    ctx = fx.base_chain(create_the_term=False)
    assert ctx["student"]["version"] == 2

    first = fx.suspend_student(ctx["student"]["id"], reason="First administrative hold")
    assert first["enrollment_status"] == "SUSPENDED"
    A.assert_instant_equals(first["suspended_at_utc"], BASE_CLOCK_UTC,
                            "suspended_at_utc")
    assert first["version"] == 3

    fx.reinstate_student(ctx["student"]["id"])
    fx.set_clock(SECOND_SUSPENSION_UTC)

    second = fx.suspend_student(ctx["student"]["id"],
                               reason="Second administrative hold")
    assert second["enrollment_status"] == "SUSPENDED"
    A.assert_instant_equals(second["suspended_at_utc"], SECOND_SUSPENSION_UTC,
                            "suspended_at_utc")
    assert second["version"] == 5


def test_reinstatement_leaves_the_progress_axis_and_the_suspension_record_alone():
    """Both reinstatements return the student to ACTIVE and bump the version, and
    the progress axis stays in good standing throughout because the two dimensions
    move for different reasons.

    PRD: "Reinstatement moves a suspended student back to `ACTIVE`, but only when
    no integrity case for that student is `OPEN` or `UNDER_INVESTIGATION`; it leaves
    `suspended_at_utc` in place as the historical record and leaves `sap_status`
    exactly where it was, and increments `version`."

    Design: Corner/state_machines/student_suspend_reinstate_cycle_repeats
    """
    ctx = fx.base_chain(create_the_term=False)

    fx.suspend_student(ctx["student"]["id"], reason="First administrative hold")
    first_back = fx.reinstate_student(ctx["student"]["id"])
    assert first_back["enrollment_status"] == "ACTIVE"
    assert first_back["version"] == 4
    A.assert_instant_equals(first_back["suspended_at_utc"], BASE_CLOCK_UTC,
                            "suspended_at_utc")

    fx.set_clock(SECOND_SUSPENSION_UTC)
    fx.suspend_student(ctx["student"]["id"], reason="Second administrative hold")
    second_back = fx.reinstate_student(ctx["student"]["id"])
    assert second_back["enrollment_status"] == "ACTIVE"
    assert second_back["sap_status"] == "GOOD_STANDING"
    assert second_back["version"] == 6


def _retired_competency_with_its_rubric():
    """A published rubric on IT-101 and an active term, then IT-101 retired with no
    live attempt anywhere on it."""
    ctx = fx.base_chain(with_blueprint=True)
    ctx["retired"] = fx.retire_competency(ctx["competency"]["id"])
    return ctx


def test_retirement_closes_the_rubric_timeline_at_the_moment_of_retirement():
    """Retirement is not only a status change: the published rubric's window is
    closed at the logical clock and the rubric itself moves to superseded.

    PRD: "Retirement carries three side effects beyond the status change: the owning
    program's `competency_count` decreases by 1 and its `version` increments; every
    blueprint of this competency whose `status` is `PUBLISHED` has its
    `effective_to_utc` set to the logical clock and its `status` changed to
    `SUPERSEDED`, so the rubric timeline closes at the moment of retirement; and the
    competency's own `version` increments."

    Design: Corner/state_machines/attempt_creation_guarded_by_competency_status
    """
    ctx = _retired_competency_with_its_rubric()
    assert ctx["retired"]["status"] == "RETIRED"

    blueprint = fx.refresh_blueprint(ctx["blueprint"]["id"])
    assert blueprint["status"] == "SUPERSEDED"
    A.assert_instant_equals(blueprint["effective_to_utc"], BASE_CLOCK_UTC,
                            "effective_to_utc")


def test_no_attempt_may_be_opened_on_a_retired_competency():
    """The retirement guard fires ahead of the missing-rubric complaint that the
    same retirement created, so the caller learns the competency is closed rather
    than that its rubric window has shut.

    PRD: "Any later attempt to retire, to publish a blueprint against, or to open an
    attempt on a retired competency is refused with `ERR_COMPETENCY_RETIRED`."

    Design: Corner/state_machines/attempt_creation_guarded_by_competency_status
    """
    ctx = _retired_competency_with_its_rubric()

    response = api_client.create_attempt(
        create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_COMPETENCY_RETIRED.value, 409)

    A.assert_page(
        api_client.list_attempts(fx.REGISTRAR,
                                 params={"student_id": ctx["student"]["id"]}),
        0,
    )


def test_withdrawal_sweeps_the_active_term_and_the_assignment_but_not_the_pending_term():
    """One request mutates three entities downward. The withdrawal instant is the
    supplied one rather than the clock, the live term closes as cancelled on that
    same instant, the live assignment ends and returns the mentor's slot, and the
    term that had not started yet is left exactly where it was.

    PRD: "On success `withdrawn_at_utc` is set to the supplied `effective_utc`, not
    to the clock; every subscription term of the student whose `status` is `ACTIVE`
    is closed as `CANCELLED` with `closed_effective_utc` set to that same
    `effective_utc`, which runs the term close-out arithmetic of §3.9 on each of
    them; every mentor assignment of the student whose `status` is `ACTIVE` is
    ended, each ending decrementing its mentor's `current_caseload` by 1; every aid
    disbursement of the student that is scheduled or held is cancelled; and the
    student's `version` increments."

    Design: Corner/state_machines/withdraw_cascades_down_to_term_and_assignment
    """
    ctx = fx.base_chain()
    later_term = fx.create_term(ctx["student"]["id"],
                               term_start_utc=SECOND_TERM_START_UTC,
                               term_end_utc=SECOND_TERM_END_UTC)
    assert later_term["status"] == "PENDING"
    mentor = fx.create_mentor(max_caseload=5, cadence_days=7)
    assignment = fx.assign_mentor(fx.refresh_student(ctx["student"]["id"]),
                                 mentor["id"])
    assert assignment["status"] == "ACTIVE"

    fx.set_clock(WITHDRAW_CLOCK_UTC)
    withdrawn = fx.withdraw_student(ctx["student"]["id"], WITHDRAW_CLOCK_UTC,
                                   reason="Learner relocated")
    assert withdrawn["enrollment_status"] == "WITHDRAWN"
    A.assert_instant_equals(withdrawn["withdrawn_at_utc"], WITHDRAW_CLOCK_UTC,
                            "withdrawn_at_utc")

    live = fx.refresh_term(ctx["term"]["id"])
    assert live["status"] == "CANCELLED"
    A.assert_instant_equals(live["closed_effective_utc"], WITHDRAW_CLOCK_UTC,
                            "closed_effective_utc")
    assert fx.refresh_term(later_term["id"])["status"] == "PENDING"

    ended = fx.refresh_assignment(assignment["id"])
    assert ended["status"] == "ENDED"
    A.assert_instant_equals(ended["ended_at_utc"], WITHDRAW_CLOCK_UTC,
                            "ended_at_utc")
    assert fx.refresh_mentor(mentor["id"])["current_caseload"] == 0


def _assignment_handed_from_alpha_to_beta():
    """An explicit assignment to Mentor Alpha, then a superseding explicit
    assignment to Mentor Beta whose contact rhythm is twice as long."""
    ctx = fx.base_chain(create_the_term=False)
    ctx["alpha"] = fx.create_mentor(full_name="Mentor Alpha",
                                   email="alpha@example.edu",
                                   max_caseload=5, cadence_days=7)
    ctx["beta"] = fx.create_mentor(full_name="Mentor Beta",
                                  email="beta@example.edu",
                                  max_caseload=5, cadence_days=14)
    ctx["first"] = fx.assign_mentor(ctx["student"], ctx["alpha"]["id"])
    assert ctx["first"]["selection_mode"] == "EXPLICIT"
    assert fx.refresh_mentor(ctx["alpha"]["id"])["current_caseload"] == 1
    ctx["student"] = fx.refresh_student(ctx["student"]["id"])
    assert ctx["student"]["version"] == 3
    ctx["second"] = fx.assign_mentor(ctx["student"], ctx["beta"]["id"])
    return ctx


def test_the_superseding_assignment_moves_the_caseload_slot_between_two_mentors():
    """The slot moves rather than duplicating: the outgoing mentor drops to zero,
    the incoming one rises to one, the old pairing ends instead of vanishing, and
    the student holds exactly one live assignment.

    PRD: "Creating the assignment also supersedes whatever came before: the
    student's prior active assignment, if any, is ended and that mentor's
    `current_caseload` decreases by 1, while the newly chosen mentor's
    `current_caseload` increases by 1 and their `version` increments."

    Design: Corner/state_machines/assignment_replacement_moves_the_caseload_slot
    """
    ctx = _assignment_handed_from_alpha_to_beta()

    assert ctx["second"]["status"] == "ACTIVE"
    superseded = fx.refresh_assignment(ctx["first"]["id"])
    assert superseded["status"] == "ENDED"
    A.assert_instant_equals(superseded["ended_at_utc"], BASE_CLOCK_UTC,
                            "ended_at_utc")
    assert fx.refresh_mentor(ctx["alpha"]["id"])["current_caseload"] == 0
    assert fx.refresh_mentor(ctx["beta"]["id"])["current_caseload"] == 1

    A.assert_page(
        api_client.list_mentor_assignments(
            fx.REGISTRAR,
            params={"student_id": ctx["student"]["id"], "status": "ACTIVE"},
        ),
        1,
    )


def test_the_replacement_assignment_sets_its_own_cadence_anchor():
    """The new pairing takes the incoming mentor's fortnightly rhythm rather than
    inheriting the outgoing weekly one, so the next contact falls fourteen days
    after the handover.

    PRD: "Its `next_contact_due_utc` is the assignment instant advanced by
    `cadence_days` days, its `cadence_status` is `COMPLIANT`, and its `overdue_days`
    is 0."

    Design: Corner/state_machines/assignment_replacement_moves_the_caseload_slot
    """
    ctx = _assignment_handed_from_alpha_to_beta()
    replacement = ctx["second"]

    A.assert_mentor_assignment(replacement)
    assert replacement["cadence_days"] == 14
    A.assert_instant_equals(replacement["assigned_at_utc"], BASE_CLOCK_UTC,
                            "assigned_at_utc")
    A.assert_instant_equals(replacement["next_contact_due_utc"],
                            REPLACEMENT_DUE_UTC, "next_contact_due_utc")
    assert replacement["cadence_status"] == "COMPLIANT"
    assert replacement["overdue_days"] == 0


def test_a_dismissed_case_restores_the_attempt_to_where_the_hold_began():
    """Opening the case is a reversible detour. The attempt is parked in
    INTEGRITY_HOLD with the review status it left recorded, and the dismissal undoes
    every side effect without leaving a strike behind.

    PRD: "A `DISMISSED` outcome forces `sanction` to `NONE`, sets `resolved_at_utc`
    to the logical clock and `resolved_by_user_id` to the acting officer, sets the
    attempt's `integrity_hold` to false, and — when the attempt is sitting in
    `INTEGRITY_HOLD` — restores it to whatever `held_from_status` recorded, clearing
    that field back to null."

    Design: Corner/state_machines/dismissed_case_restores_the_held_status
    """
    ctx = fx.attempt_under_review(
        submit_overrides={"artifact_hash": "sha256:comp1",
                          "client_fingerprint": "fp-comp-1"},
    )
    assert ctx["attempt"]["status"] == "UNDER_REVIEW"

    case = fx.open_case(ctx["attempt"]["id"], opener_user_id="io-1",
                       signal_type="THIRD_PARTY_REPORT", severity="LOW",
                       note="Anonymous tip")
    held = fx.refresh_attempt(ctx["attempt"]["id"])
    assert held["status"] == "INTEGRITY_HOLD"
    assert held["held_from_status"] == "UNDER_REVIEW"
    assert held["integrity_hold"] is True

    fx.investigate_case(case["id"], officer_user_id="io-2")
    resolved = fx.resolve_case(case["id"], "DISMISSED", sanction="NONE",
                              resolver_user_id="io-2")
    assert resolved["status"] == "DISMISSED"
    assert resolved["sanction"] == "NONE"
    A.assert_instant_equals(resolved["resolved_at_utc"], BASE_CLOCK_UTC,
                            "resolved_at_utc")

    back = fx.refresh_attempt(ctx["attempt"]["id"])
    assert back["status"] == "UNDER_REVIEW"
    assert back["held_from_status"] is None
    assert back["integrity_hold"] is False

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["integrity_strike_count"] == 0
    assert student["enrollment_status"] == "ACTIVE"


def _term_with_one_submitted_and_one_draft_attempt():
    """Two rubric-backed competencies in one active term: IT-101 submitted into
    review, IT-102 left sitting in draft, observed from ten days in."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    first = fx.create_competency(program["id"], code="IT-101",
                                title="Relational Data Modeling",
                                unit_value=4, level="FOUNDATION")
    second = fx.create_competency(program["id"], code="IT-102",
                                 title="Query Optimisation",
                                 unit_value=4, level="FOUNDATION")
    fx.create_blueprint(first)
    fx.create_blueprint(second)
    program = fx.publish_program(program["id"])
    student = fx.activate_student(fx.create_student(program["id"])["id"])
    term = fx.activate_term(fx.create_term(student["id"])["id"])

    submitted = fx.open_attempt(student["id"], first["id"])
    submitted = fx.submit_attempt(submitted["id"], student["id"],
                                 artifact_hash="sha256:cond1",
                                 client_fingerprint="fp-cond-1")
    assert submitted["status"] == "UNDER_REVIEW"
    draft = fx.open_attempt(student["id"], second["id"])
    assert draft["status"] == "DRAFT"

    fx.set_clock(WITHDRAW_CLOCK_UTC)
    return {"program": program, "student": student, "term": term,
            "submitted": submitted, "draft": draft}


def test_closing_the_term_voids_the_draft_attempt_and_spares_the_one_under_review():
    """The sweep is scoped to the child's own state, so the draft attempt is voided
    while its sibling waiting for a reader is untouched.

    PRD: "Whichever branch runs, `closed_effective_utc` records the supplied
    instant, every attempt booked to the term whose status is `DRAFT` or
    `REVISION_REQUESTED` is voided, and the term's `version` increments."

    Design: Corner/state_machines/term_close_voids_only_draft_stage_attempts
    """
    ctx = _term_with_one_submitted_and_one_draft_attempt()

    closed = fx.close_term(ctx["term"]["id"], "COMPLETED", WITHDRAW_CLOCK_UTC)
    assert closed["status"] == "COMPLETED"
    A.assert_instant_equals(closed["closed_effective_utc"], WITHDRAW_CLOCK_UTC,
                            "closed_effective_utc")

    assert fx.refresh_attempt(ctx["draft"]["id"])["status"] == "VOIDED"
    assert fx.refresh_attempt(ctx["submitted"]["id"])["status"] == "UNDER_REVIEW"


def test_the_completed_branch_pins_full_earning_regardless_of_attended_days():
    """Ten days into a ninety-one day period the earned fraction is still pinned at
    one, nothing is refunded and the whole tuition stands charged — while the day
    count itself is reported honestly.

    PRD: "`COMPLETED` is the *earned* branch: `earned_pct` is set to `1.0000`,
    `institutional_refund_cents` to 0, and `net_institutional_charge_cents` to the
    full `tuition_cents`, regardless of how few days the student actually attended;
    `attended_days` is still computed and reported."

    Design: Corner/state_machines/term_close_voids_only_draft_stage_attempts
    """
    ctx = _term_with_one_submitted_and_one_draft_attempt()

    closed = fx.close_term(ctx["term"]["id"], "COMPLETED", WITHDRAW_CLOCK_UTC)
    assert closed["attended_days"] == 10
    A.assert_number_equals(closed["earned_pct"], 1.0000, "earned_pct")
    A.assert_cents(closed["institutional_refund_cents"], 0,
                   "institutional_refund_cents")
    A.assert_cents(closed["net_institutional_charge_cents"], 375000,
                   "net_institutional_charge_cents")
