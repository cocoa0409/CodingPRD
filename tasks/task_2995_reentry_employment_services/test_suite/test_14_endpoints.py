"""
The endpoints that are more than a read or a single-column write.

Two computed reads that must agree with the rows they project, a partial update that
must leave everything it was not given alone, an action whose one call fires four
separate pieces of bookkeeping, and a body foreign key resolved against the wrong
collection.
"""

from test_helpers.api_errors import ERR_PARTICIPANT_NOT_FOUND, ERR_RECORD_CATEGORY_BARRED
from test_helpers.assertions import (
    assert_common_fields,
    assert_created_at_stable,
    assert_int_field,
    assert_match_breakdown,
    assert_money_cents,
    assert_one_decimal_place,
    assert_session_seat_identity,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    BARRIER_TIER_HIGH,
    COMPLIANCE_COMPLIANT,
    EMPLOYMENT_ACTIVE,
    OFFER_RESPONSE_ACCEPTED,
    OPENING_OPEN,
    POSTURE_OPEN,
    RECORD_PROPERTY_OFFENSE,
    RECORD_VIOLENT_OFFENSE,
    RELEASE_PLAN_APPROVED,
    RELEASE_PLAN_NONE,
    SESSION_TYPE_INTERVIEW_PRACTICE,
    STAGE_PLACED,
    STAGE_PRE_RELEASE,
    STAGE_RELEASE_READY,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    participant_headers,
)


def test_the_readiness_summary_projects_the_participant_row_field_for_field(api, build):
    """
    The summary invents nothing: every number it reports is the stored participant's
    own, and `readiness_met` is the whole four-part conjunction rather than a copy of the
    documentation figure.

    PRD section 3.1: "A computed readiness read exposes the predicate and its inputs
    for a single participant without mutating anything: it reports `participant_id`, the
    current `stage`, `doc_completeness_pct`, `required_document_count` (the size of
    `required_document_types`), `verified_document_count` (the size of
    `verified_document_types`), `barrier_score`, `barrier_tier`, `release_plan_status`,
    and `readiness_met`, the boolean value of the four-part predicate above."

    Design: Corner/endpoints/readiness_summary_reports_the_same_numbers_as_the_participant_row
    """
    participant = build.participant_release_ready()

    stored = validate_unpaginated(api.get_participant(participant["id"], CASE_MANAGER))
    assert stored["stage"] == STAGE_RELEASE_READY

    summary = validate_unpaginated(
        api.get_readiness_summary(participant["id"], CASE_MANAGER)
    )
    assert summary["participant_id"] == participant["id"]
    assert summary["stage"] == stored["stage"]
    assert_one_decimal_place(summary, "doc_completeness_pct", 80.0)
    assert summary["doc_completeness_pct"] == stored["doc_completeness_pct"]
    assert_int_field(summary, "required_document_count", 5)
    assert_int_field(summary, "verified_document_count", 4)
    assert len(stored["required_document_types"]) == 5
    assert len(stored["verified_document_types"]) == 4
    assert_one_decimal_place(summary, "barrier_score", 66.3)
    assert summary["barrier_tier"] == BARRIER_TIER_HIGH
    assert summary["barrier_score"] == stored["barrier_score"]
    assert summary["barrier_tier"] == stored["barrier_tier"]
    assert summary["release_plan_status"] == RELEASE_PLAN_APPROVED
    assert summary["release_plan_status"] == stored["release_plan_status"]
    assert summary["readiness_met"] is True


def test_a_preview_for_a_barred_participant_still_scores_and_names_the_blocker(
    api, build
):
    """
    A preview is a read and never fails on eligibility: it reports the full 75-point
    score alongside `eligible` false and the very identifier a real placement create
    would have raised.

    PRD section 3.6: "When `eligible` is false, `blocking_error_id` names the very
    error identifier a real placement creation would return, chosen by the same
    precedence ladder — so a preview against a full opening for a barred participant
    reports `ERR_RECORD_CATEGORY_BARRED`, matching what creation would say."

    The employer excludes violent offences, so the record bar fires; the arithmetic is
    28, 20, 7, 15, 0 and 5.

    Design: Corner/endpoints/match_preview_reports_the_blocking_error_for_a_barred_record_category
    """
    partnership = build.partnership_active(
        excluded_record_categories=[RECORD_VIOLENT_OFFENSE]
    )
    opening = build.job_opening(partnership["id"], barred_record_categories=[])
    participant = build.participant_released(record_categories=[RECORD_VIOLENT_OFFENSE])

    preview = validate_unpaginated(
        api.get_match_preview(
            opening["id"], CASE_MANAGER, {"participant_id": participant["id"]}
        )
    )
    assert preview["job_opening_id"] == opening["id"]
    assert preview["participant_id"] == participant["id"]
    assert preview["eligible"] is False
    assert preview["blocking_error_id"] == ERR_RECORD_CATEGORY_BARRED
    assert_int_field(preview, "match_score", 75)
    assert_match_breakdown(preview["match_breakdown"], 28, 20, 7, 15, 0, 5)

    rows, meta = validate_paginated(api.list_placements(CASE_MANAGER))
    assert meta["total_count"] == 0


def test_a_partial_update_rewrites_one_field_and_disturbs_nothing_else(api, build):
    """
    Every intake attribute is independently optional, so a one-key update leaves the
    other five and the computed assessment columns exactly as they were while advancing
    the row to its third version.

    PRD section 3.1: "Intake attributes remain editable. A `CaseManager` may revise
    any of `full_name`, `facility_name`, `facility_state`, `expected_release_date`,
    `record_categories`, and `required_document_types`, each independently optional in
    the update payload, and the same format and duplicate constraints apply to a revised
    array as to an original one."

    PRD section 2.4: "`version` (an integer that starts at 1 when the row is created
    and increases by exactly one on every accepted mutation of that row)"

    Design: Corner/endpoints/updating_a_participant_touches_only_the_supplied_fields
    """
    participant = build.participant()
    assessed = validate_unpaginated(
        api.record_assessment(participant["id"], f.assessment_payload(), CASE_MANAGER)
    )
    assert_int_field(assessed, "version", 2)

    updated = validate_unpaginated(
        api.update_participant(
            participant["id"], {"full_name": "Marcus A. Reed"}, CASE_MANAGER
        )
    )
    assert updated["full_name"] == "Marcus A. Reed"
    assert updated["facility_name"] == "Northgate Correctional"
    assert updated["facility_state"] == "OH"
    assert updated["expected_release_date"] == "2026-08-10"
    assert updated["record_categories"] == [RECORD_PROPERTY_OFFENSE]
    assert_one_decimal_place(updated, "barrier_score", 66.3)
    assert updated["barrier_tier"] == BARRIER_TIER_HIGH
    assert updated["stage"] == STAGE_PRE_RELEASE
    assert updated["release_plan_status"] == RELEASE_PLAN_NONE
    assert_int_field(updated, "version", 3)
    assert_common_fields(updated, 3)
    assert_created_at_stable(assessed, updated)


def test_a_grant_identifier_offered_as_an_enrollee_is_a_participant_miss(api, build):
    """
    The session in the path resolves, so the failure belongs to the body foreign key,
    and the seat counters do not move for a row that was never created.

    PRD section 2.5: "**Body foreign keys** — a foreign key supplied inside the
    request body matches no row, yielding the referenced collection's not-found code
    with HTTP 404."

    Design: Corner/endpoints/enrolling_a_participant_that_does_not_exist_returns_not_found
    """
    grant = build.grant(authorized_cents=100000, per_participant_cap_cents=60000)
    session = build.readiness_session(
        session_type=SESSION_TYPE_INTERVIEW_PRACTICE,
        coach_user_id="coach-1",
        starts_at="2026-08-06T13:00:00.000Z",
        ends_at="2026-08-06T15:00:00.000Z",
        seat_capacity=3,
    )

    refused = api.create_enrollment(
        session["id"], f.enrollment_payload(grant["id"]), CASE_MANAGER
    )
    validate_error(refused, ERR_PARTICIPANT_NOT_FOUND, 404)

    stored = validate_unpaginated(api.get_readiness_session(session["id"], CASE_MANAGER))
    assert_int_field(stored, "enrolled_count", 0)
    assert_int_field(stored, "remaining_seats", 3)
    assert_session_seat_identity(stored)

    rows, meta = validate_paginated(
        api.list_session_enrollments(session["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 0


def test_accepting_the_offer_swaps_a_seat_and_moves_four_other_rows(api, build):
    """
    One acceptance does five things: the placement goes live, the opening's offered
    seat becomes a filled one without changing what remains, the employer's live
    headcount rises, the participant reaches `PLACED`, and both subsidy figures start
    at zero.

    PRD section 3.6: "On acceptance the opening's `offered_count` falls by one while
    `filled_count` rises by one, leaving `remaining_openings` unchanged; the
    partnership's `active_placement_count` rises by one; the participant's `stage` moves
    `POST_RELEASE → PLACED`; and both `projected_subsidy_cents` and
    `actual_subsidy_cents` are recomputed, which yields 0 for each until shifts exist."

    PRD section 3.6: "`match_score` is an integer from 0 through 100 computed once at
    creation from the then-current participant, opening, and partnership values and
    never recomputed afterwards"

    Design: Corner/endpoints/accepting_an_offer_moves_the_participant_to_placed
    """
    grant = build.grant(
        authorized_cents=30000, per_participant_cap_cents=60000, retention_benchmark_pct=75.0
    )
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"], openings_count=2)
    participant = build.participant_released()
    offered = build.placement_offered(participant["id"], opening["id"], grant["id"])
    assert_int_field(offered, "match_score", 75)

    accepted = validate_unpaginated(
        api.respond_to_offer(
            offered["id"],
            f.offer_response_payload(OFFER_RESPONSE_ACCEPTED),
            participant_headers(participant["id"]),
        )
    )
    assert accepted["employment_status"] == EMPLOYMENT_ACTIVE
    assert_money_cents(accepted, "projected_subsidy_cents", 0)
    assert_money_cents(accepted, "actual_subsidy_cents", 0)
    assert accepted["schedule_compliance"] == COMPLIANCE_COMPLIANT
    assert_int_field(accepted, "match_score", 75)
    assert_match_breakdown(accepted["match_breakdown"], 28, 20, 7, 15, 0, 5)

    stored_opening = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(stored_opening, "offered_count", 0)
    assert_int_field(stored_opening, "filled_count", 1)
    assert_int_field(stored_opening, "remaining_openings", 1)
    assert stored_opening["status"] == OPENING_OPEN

    stored_partnership = validate_unpaginated(
        api.get_partnership(partnership["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(stored_partnership, "active_placement_count", 1)

    stored_participant = validate_unpaginated(
        api.get_participant(participant["id"], CASE_MANAGER)
    )
    assert stored_participant["stage"] == STAGE_PLACED
    assert stored_participant["engagement_posture"] == POSTURE_OPEN
