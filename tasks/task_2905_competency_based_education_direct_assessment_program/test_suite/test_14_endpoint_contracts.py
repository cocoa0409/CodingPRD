"""Endpoint contracts: the mentor create/read/list triple, the two action
endpoints that guard their own preconditions, the prerequisite link, and the
fully derived progress summary at its zero state.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import create_mentor_payload


def test_the_registered_mentor_round_trips_through_the_read_and_the_filtered_list():
    """The create / read / list triple returns one row: an empty caseload, an active
    standing and version one, readable both by id and through the ACTIVE filter.

    PRD: "The record starts with `current_caseload` at 0 and `status` `ACTIVE`."

    Design: Corner/endpoints/mentor_crud_triple_round_trips
    """
    fx.set_clock(BASE_CLOCK_UTC)

    response = api_client.create_mentor(
        create_mentor_payload(full_name="Mentor Meg", email="meg@example.edu",
                              max_caseload=20, cadence_days=21),
        fx.REGISTRAR,
    )
    created = validate_success(response, 201)
    A.assert_mentor(created)
    assert created["status"] == "ACTIVE"
    assert created["current_caseload"] == 0
    assert created["version"] == 1

    read_back = validate_success(api_client.get_mentor(created["id"], fx.REGISTRAR))
    assert read_back["full_name"] == "Mentor Meg"
    assert read_back["max_caseload"] == 20
    assert read_back["cadence_days"] == 21
    assert read_back["version"] == 1

    listed = api_client.list_mentors(fx.REGISTRAR, params={"status": "ACTIVE"})
    A.assert_page(listed, 1, expected_count=1, expected_has_more=False)


def test_the_standing_endpoint_is_the_only_mutation_the_collection_offers():
    """Availability is the sole field a later call can move, and moving it off ACTIVE
    both bumps the version and drops the row out of the ACTIVE-filtered list.

    PRD: "Availability can later be set to `ACTIVE`, `ON_LEAVE`, or `INACTIVE`; a
    mentor who is not `ACTIVE` keeps every assignment they already hold but is
    excluded from automatic selection."

    Design: Corner/endpoints/mentor_crud_triple_round_trips
    """
    fx.set_clock(BASE_CLOCK_UTC)
    mentor = fx.create_mentor(full_name="Mentor Meg", email="meg@example.edu",
                              max_caseload=20, cadence_days=21)

    moved = fx.set_mentor_status(mentor["id"], "ON_LEAVE")
    assert moved["status"] == "ON_LEAVE"
    assert moved["version"] == 2
    assert moved["max_caseload"] == 20
    assert moved["cadence_days"] == 21

    A.assert_page(api_client.list_mentors(fx.REGISTRAR, params={"status": "ACTIVE"}), 0)
    A.assert_page(
        api_client.list_mentors(fx.REGISTRAR, params={"status": "ON_LEAVE"}), 1)


def test_ending_the_assignment_stamps_the_clock_and_frees_the_caseload_slot():
    """The action endpoint transitions and settles the books in one move: the pairing
    ends at the logical clock and the mentor's slot comes back.

    PRD: "Ending an assignment moves `status` from `ACTIVE` to `ENDED`, sets
    `ended_at_utc` to the logical clock, clears `endorsed_competency_ids` to an empty
    array so unconsumed endorsements do not survive the pairing that granted them,
    decrements the mentor's `current_caseload` by 1 and increments that mentor's
    `version`, and increments the assignment's own `version`."

    Design: Corner/endpoints/ending_an_assignment_twice_is_refused
    """
    ctx = fx.mentored_scenario()
    assert ctx["mentor"]["current_caseload"] == 1

    ended = validate_success(
        api_client.end_mentor_assignment(ctx["assignment"]["id"], fx.REGISTRAR))
    assert ended["status"] == "ENDED"
    A.assert_instant_equals(ended["ended_at_utc"], BASE_CLOCK_UTC, "ended_at_utc")
    assert ended["version"] == 2
    assert ended["endorsed_competency_ids"] == []

    assert fx.refresh_mentor(ctx["mentor"]["id"])["current_caseload"] == 0


def test_the_second_end_is_refused_and_never_drives_the_caseload_negative():
    """The same endpoint enforces its own precondition, so the repeat call cannot
    decrement a slot that has already been returned.

    PRD: "Recording a contact, recording an endorsement, or ending an assignment needs
    an active assignment, or else `ERR_ASSIGNMENT_NOT_ACTIVE`."

    Design: Corner/endpoints/ending_an_assignment_twice_is_refused
    """
    ctx = fx.mentored_scenario()
    fx.end_assignment(ctx["assignment"]["id"])

    response = api_client.end_mentor_assignment(ctx["assignment"]["id"], fx.REGISTRAR)
    validate_error(response, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value, 409)

    assert fx.refresh_mentor(ctx["mentor"]["id"])["current_caseload"] == 0
    assignment = fx.refresh_assignment(ctx["assignment"]["id"])
    assert assignment["status"] == "ENDED"
    assert assignment["version"] == 2


def _draft_program_with_two_unlinked_competencies():
    """IT-101 and IT-201 registered in a program that has not been published yet, with
    no prerequisite edge between them."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program()
    foundation = fx.create_competency(program["id"], code="IT-101",
                                      title="Relational Data Modeling",
                                      unit_value=4, level="FOUNDATION")
    dependent = fx.create_competency(program["id"], code="IT-201",
                                     title="Query Optimization",
                                     unit_value=4, level="CORE")
    assert program["status"] == "DRAFT"
    assert dependent["prerequisite_competency_id"] is None
    return {"program": program, "foundation": foundation, "dependent": dependent}


def test_the_link_endpoint_refuses_to_edit_the_map_of_an_unpublished_program():
    """Both competencies exist and the edge is legal, yet the link is one of the three
    operations that first require the owning program to be published.

    PRD: "The referenced program is published before a student may enrol in it, before
    a prerequisite edge may be set on one of its competencies, and before an attempt
    may be created against one of its competencies — otherwise
    `ERR_PROGRAM_NOT_PUBLISHED`. Applies to student enrollment, setting a competency
    prerequisite, and attempt creation."

    Design: Corner/endpoints/prerequisite_link_endpoint_associates_two_competencies
    """
    ctx = _draft_program_with_two_unlinked_competencies()

    response = api_client.set_competency_prerequisite(
        ctx["dependent"]["id"],
        {"prerequisite_competency_id": ctx["foundation"]["id"]},
        fx.REGISTRAR,
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_PUBLISHED.value, 409)

    unchanged = fx.refresh_competency(ctx["dependent"]["id"])
    assert unchanged["prerequisite_competency_id"] is None
    assert unchanged["version"] == 1


def test_the_published_map_accepts_the_link_and_versions_only_the_dependent_side():
    """After publication the identical call writes the edge, and the ancestor named as
    the prerequisite is left entirely alone.

    PRD: "Re-pointing runs both graph checks again and then recomputes
    `prerequisite_depth` not only for the competency being edited but for every
    competency reachable through it, since a change at the base of a chain shifts the
    depth of everything above it. The competency's `version` increments."

    Design: Corner/endpoints/prerequisite_link_endpoint_associates_two_competencies
    """
    ctx = _draft_program_with_two_unlinked_competencies()
    fx.publish_program(ctx["program"]["id"])

    response = api_client.set_competency_prerequisite(
        ctx["dependent"]["id"],
        {"prerequisite_competency_id": ctx["foundation"]["id"]},
        fx.REGISTRAR,
    )
    linked = validate_success(response)
    assert linked["prerequisite_competency_id"] == ctx["foundation"]["id"]
    assert linked["version"] == 2

    ancestor = fx.refresh_competency(ctx["foundation"]["id"])
    assert ancestor["version"] == 1
    assert ancestor["prerequisite_competency_id"] is None


def test_the_zero_state_summary_derives_every_total_to_its_identity_element():
    """Nothing has been mastered and no aid exists, so each figure is computed down to
    zero rather than left absent.

    PRD: "It reports `student_id`, `enrollment_status`, `sap_status`,
    `mastered_unit_total`, `mastered_competency_count`, the program's
    `required_unit_total`, and `cumulative_credit_equivalency`; then
    `aid_credit_equivalency_sum`, which is the sum of `credit_equivalency_earned` over
    the student's terms excluding cancelled ones, and `credit_equivalency_variance`,
    which is `cumulative_credit_equivalency` minus `aid_credit_equivalency_sum` rounded
    half up to one decimal — the variance is the reconciliation gap itself, published as
    a first-class number rather than hidden."

    Design: Corner/endpoints/progress_summary_zero_state_is_fully_derived
    """
    ctx = fx.base_chain()

    summary = fx.progress_summary(ctx["student"]["id"])
    A.assert_progress_summary_shape(summary)
    assert summary["student_id"] == ctx["student"]["id"]
    assert summary["enrollment_status"] == "ACTIVE"
    assert summary["sap_status"] == "GOOD_STANDING"
    assert summary["mastered_unit_total"] == 0
    assert summary["mastered_competency_count"] == 0
    A.assert_number_equals(summary["cumulative_credit_equivalency"], 0.0,
                           "cumulative_credit_equivalency")
    assert summary["aid_credit_equivalency_sum"] == 0
    A.assert_number_equals(summary["credit_equivalency_variance"], 0.0,
                           "credit_equivalency_variance")
    A.assert_credit_equivalency_variance(summary)


def test_the_zero_state_summary_reports_no_mentoring_state_rather_than_a_default_one():
    """With no active assignment the mentoring fields are null rather than a compliant
    default, and the three aid roll-ups are all zero cents.

    PRD: "It also reports the aid ledger roll-ups `aid_scheduled_total_cents`,
    `aid_retained_total_cents` and `aid_returned_total_cents`; the current mentoring
    state as `active_mentor_assignment_id`, `cadence_status` and `overdue_days`, which
    are null, null and 0 respectively when the student has no active assignment; and
    `open_integrity_case_count`."

    Design: Corner/endpoints/progress_summary_zero_state_is_fully_derived
    """
    ctx = fx.base_chain()

    summary = fx.progress_summary(ctx["student"]["id"])
    assert summary["active_mentor_assignment_id"] is None
    assert summary["cadence_status"] is None
    assert summary["overdue_days"] == 0
    assert summary["aid_scheduled_total_cents"] == 0
    assert summary["aid_retained_total_cents"] == 0
    assert summary["aid_returned_total_cents"] == 0
    assert summary["open_integrity_case_count"] == 0


def test_a_scheduled_award_cannot_be_returned_before_it_was_ever_released():
    """The return action reads the award's own status, not the term's, so a scheduled
    row is refused and its ledger is left exactly as it stood.

    PRD: "The award must be `DISBURSED`, or the request is refused with
    `ERR_AID_NOT_DISBURSED`, and the term must be `LAPSED` or `CANCELLED` with an
    `earned_pct` strictly below 1.0000 — a fully earned term has nothing to return."

    Design: Corner/endpoints/aid_return_allowed_only_from_disbursed
    """
    ctx = fx.scheduled_aid_scenario()
    award = ctx["award"]
    assert award["status"] == "SCHEDULED"
    assert award["scheduled_amount_cents"] == 200000
    assert award["outstanding_amount_cents"] == 200000

    response = api_client.return_aid(award["id"], fx.AID_OFFICER)
    validate_error(response, ApiErrorId.ERR_AID_NOT_DISBURSED.value, 409)

    after = fx.refresh_award(award["id"])
    assert after["status"] == "SCHEDULED"
    assert after["outstanding_amount_cents"] == 200000
    assert after["returned_amount_cents"] == 0
    assert after["retained_amount_cents"] == 0
    assert after["cancelled_amount_cents"] == 0
    A.assert_aid_ledger_identity(after)
