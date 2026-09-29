"""
Requests that break two rules at once.

Each scenario constructs a single call that violates a low-numbered precedence
band and a high-numbered one simultaneously, checks that the lower band answers,
then removes the lower violation and checks that the higher one surfaces
unchanged. The second half is what proves the first refusal was precedence and not
a missing rule.
"""

from test_helpers.api_errors import (
    ERR_JOB_OPENING_NOT_OPEN,
    ERR_PARTICIPANT_CAP_EXCEEDED,
    ERR_PARTICIPANT_SUSPENDED,
    ERR_RECORD_CATEGORY_BARRED,
    ERR_SHIFT_OUTSIDE_WINDOW,
    ERR_WORK_NOT_AUTHORIZED,
)
from test_helpers.assertions import (
    assert_int_field,
    assert_money_cents,
    assert_opening_seat_identity,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    CATEGORY_TRANSIT_PASS,
    COMPLIANCE_COMPLIANT,
    EMPLOYMENT_OFFERED,
    OPENING_FILLED,
    POSTURE_OPEN,
    RECORD_PROPERTY_OFFENSE,
    RECORD_VIOLENT_OFFENSE,
    SHIFT_SCHEDULED,
    SUSPENSION_LIFTED,
    SUSPENSION_NONE,
    SUSPENSION_SUSPENDED,
    WORK_AUTH_APPROVED,
    WORK_AUTH_SUSPENDED,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
    SUPERVISION_OFFICER,
)

TRANSIT_LINES = [dict(description="Monthly transit pass", unit_cost_cents=10000, quantity=2)]


def _suspended_participant_over_the_cap(api, build):
    """A suspended participant and a request that also breaches the cap."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=10000)
    participant = build.participant()
    suspended = validate_unpaginated(
        api.set_suspension(
            participant["id"],
            f.suspension_payload(SUSPENSION_SUSPENDED, "Missed two supervision appointments"),
            PROGRAM_DIRECTOR,
        )
    )
    assert suspended["suspension_status"] == SUSPENSION_SUSPENDED
    return grant, participant


def _submit_transit_request(api, build, participant_id, grant_id):
    payload = f.support_request_payload(
        participant_id,
        grant_id,
        build.grant_version(grant_id),
        [f.line_item("Monthly transit pass", 10000, 2)],
        category=CATEGORY_TRANSIT_PASS,
    )
    return api.create_support_request(payload, CASE_MANAGER)


def test_participant_suspension_is_reported_ahead_of_the_per_participant_cap(
    api, build
):
    """
    The suspended participant sits in the related-entity band, above every fiscal
    cap, so the suspension answers even though the request would also breach the
    cap.

    PRD section 2.5: "A suspended participant sits in band nine, above every
    capacity gate in band twelve and every fiscal cap in band thirteen, so a
    supportive-services request for a suspended participant against a grant that
    would also breach the per-participant cap reports the suspension, not the cap."

    Design: Difficulty/priority_pair_validation_conflict/suspended_participant_error_beats_per_participant_cap_error
    """
    grant, participant = _suspended_participant_over_the_cap(api, build)

    refused = _submit_transit_request(api, build, participant["id"], grant["id"])
    validate_error(refused, ERR_PARTICIPANT_SUSPENDED, 409)


def test_lifting_the_suspension_exposes_the_cap_refusal_underneath_it(api, build):
    """
    With the higher-precedence violation removed, the identical request reports the
    fiscal cap, and neither attempt created a row.

    PRD section 3.8: "If that sum is strictly greater than the grant's
    `per_participant_cap_cents`, the request is refused with
    `ERR_PARTICIPANT_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_participant_error_beats_per_participant_cap_error
    """
    grant, participant = _suspended_participant_over_the_cap(api, build)
    validate_error(
        _submit_transit_request(api, build, participant["id"], grant["id"]),
        ERR_PARTICIPANT_SUSPENDED,
        409,
    )

    lifted = validate_unpaginated(
        api.set_suspension(
            participant["id"], f.suspension_payload(SUSPENSION_LIFTED), PROGRAM_DIRECTOR
        )
    )
    assert lifted["suspension_status"] == SUSPENSION_NONE
    assert lifted["engagement_posture"] == POSTURE_OPEN

    refused = _submit_transit_request(api, build, participant["id"], grant["id"])
    validate_error(refused, ERR_PARTICIPANT_CAP_EXCEEDED, 409)

    rows, meta = validate_paginated(
        api.list_support_requests(CASE_MANAGER, f.page_params(grant_id=grant["id"]))
    )
    assert meta["total_count"] == 0
    assert rows == []

    stored = validate_unpaginated(api.get_grant(grant["id"], FUNDER_ANALYST))
    assert_int_field(stored, "open_request_count", 0)
    assert_money_cents(stored, "committed_cents", 0)


def _barred_applicant_against_a_full_opening(api, build):
    """A one-seat opening already taken, and a barred second applicant."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    holder = build.participant_released()
    applicant = build.participant_released(
        full_name="Marcus Vale", record_categories=[RECORD_VIOLENT_OFFENSE]
    )
    partnership = build.partnership_active()
    opening = build.job_opening(
        partnership["id"],
        title="Night Dock Loader",
        openings_count=1,
        barred_record_categories=[RECORD_VIOLENT_OFFENSE],
    )
    held = build.placement_offered(holder["id"], opening["id"], grant["id"])
    filled = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert filled["status"] == OPENING_FILLED
    assert_int_field(filled, "remaining_openings", 0)
    return grant, applicant, opening, held


def _apply(api, build, participant_id, opening_id, grant_id):
    payload = f.placement_payload(
        participant_id, opening_id, build.opening_version(opening_id), grant_id
    )
    return api.create_placement(payload, CASE_MANAGER)


def test_a_barred_record_category_is_reported_ahead_of_a_full_opening(api, build):
    """
    The record bar sits above the capacity gate, so the barred applicant learns
    about the bar rather than about the exhausted seat.

    PRD section 2.5: "A barred record category sits in band ten, above the
    opening-capacity gate in band twelve, so a barred participant applying to a full
    opening reports the record bar."

    Design: Difficulty/priority_pair_validation_conflict/barred_record_category_error_beats_full_opening_error
    """
    grant, applicant, opening, held = _barred_applicant_against_a_full_opening(api, build)

    refused = _apply(api, build, applicant["id"], opening["id"], grant["id"])
    validate_error(refused, ERR_RECORD_CATEGORY_BARRED, 409)


def test_clearing_the_barred_category_exposes_the_capacity_refusal(api, build):
    """
    Revising the applicant's conviction categories removes the band-ten violation
    and the band-twelve capacity gate answers instead, with the opening's seat
    arithmetic untouched throughout.

    PRD section 3.4: "While an opening is `FILLED`, further placement creation
    against it is refused with `ERR_JOB_OPENING_NOT_OPEN`, and the same refusal
    covers an opening whose `remaining_openings` has reached 0 or below or whose
    `status` is `CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/barred_record_category_error_beats_full_opening_error
    """
    grant, applicant, opening, held = _barred_applicant_against_a_full_opening(api, build)
    validate_error(
        _apply(api, build, applicant["id"], opening["id"], grant["id"]),
        ERR_RECORD_CATEGORY_BARRED,
        409,
    )

    revised = validate_unpaginated(
        api.update_participant(
            applicant["id"], {"record_categories": [RECORD_PROPERTY_OFFENSE]}, CASE_MANAGER
        )
    )
    assert revised["record_categories"] == [RECORD_PROPERTY_OFFENSE]

    refused = _apply(api, build, applicant["id"], opening["id"], grant["id"])
    validate_error(refused, ERR_JOB_OPENING_NOT_OPEN, 409)

    stored = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert stored["status"] == OPENING_FILLED
    assert_int_field(stored, "offered_count", 1)
    assert_int_field(stored, "filled_count", 0)
    assert_int_field(stored, "remaining_openings", 0)
    assert_opening_seat_identity(stored)

    rows, meta = validate_paginated(
        api.list_placements(CASE_MANAGER, f.page_params(job_opening_id=opening["id"]))
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == held["id"]
    assert rows[0]["employment_status"] == EMPLOYMENT_OFFERED


def _unauthorised_placement_with_an_out_of_window_shift(api, build):
    """A live placement whose supervision authorisation has been withdrawn."""
    grant = build.grant(authorized_cents=5000000, per_participant_cap_cents=60000)
    participant = build.participant_released()
    case = build.case_authorized(participant["id"])
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"])
    placement = build.placement_active(participant["id"], opening["id"], grant["id"])
    withdrawn = validate_unpaginated(
        api.decide_work_authorization(
            case["id"], f.work_authorization_payload(WORK_AUTH_SUSPENDED), SUPERVISION_OFFICER
        )
    )
    assert withdrawn["work_authorization_status"] == WORK_AUTH_SUSPENDED
    return grant, participant, case, placement


def test_missing_work_authorisation_is_reported_ahead_of_the_window_breach(api, build):
    """
    A 06:00 shift falls outside the 08:00-to-17:00 window and belongs to an
    unauthorised participant; the authorisation gate answers.

    PRD section 2.5: "Work authorisation sits in band nine, above the
    window-containment check in band eleven, so an unauthorised participant whose
    proposed shift also falls outside a window reports the missing authorisation."

    Design: Difficulty/priority_pair_validation_conflict/work_not_authorized_error_beats_shift_outside_window_error
    """
    grant, participant, case, placement = _unauthorised_placement_with_an_out_of_window_shift(
        api, build
    )

    refused = api.create_work_shift(
        placement["id"],
        f.work_shift_payload("2026-08-03T06:00:00.000Z", "2026-08-03T08:00:00.000Z"),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_WORK_NOT_AUTHORIZED, 409)


def test_restoring_authorisation_exposes_the_window_refusal_then_accepts_an_in_window_shift(
    api, build
):
    """
    Once authorisation returns, the same 06:00 shift is refused for the window
    alone, while a shift inside the window is accepted and priced.

    PRD section 3.7: "A shift that starts before the window opens, ends after it
    closes, or crosses midnight into a second UTC calendar date is refused with
    `ERR_SHIFT_OUTSIDE_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/work_not_authorized_error_beats_shift_outside_window_error
    """
    grant, participant, case, placement = _unauthorised_placement_with_an_out_of_window_shift(
        api, build
    )
    early = f.work_shift_payload("2026-08-03T06:00:00.000Z", "2026-08-03T08:00:00.000Z")
    validate_error(
        api.create_work_shift(placement["id"], early, CASE_MANAGER),
        ERR_WORK_NOT_AUTHORIZED,
        409,
    )

    restored = validate_unpaginated(
        api.decide_work_authorization(
            case["id"],
            f.work_authorization_payload(WORK_AUTH_APPROVED, 480, 1020),
            SUPERVISION_OFFICER,
        )
    )
    assert restored["work_authorization_status"] == WORK_AUTH_APPROVED
    assert_int_field(restored, "authorization_change_count", 3)

    validate_error(
        api.create_work_shift(placement["id"], early, CASE_MANAGER),
        ERR_SHIFT_OUTSIDE_WINDOW,
        409,
    )

    accepted = validate_unpaginated(
        api.create_work_shift(
            placement["id"],
            f.work_shift_payload("2026-08-03T09:00:00.000Z", "2026-08-03T17:00:00.000Z"),
            CASE_MANAGER,
        ),
        201,
    )
    assert accepted["status"] == SHIFT_SCHEDULED
    assert accepted["scheduled_hours"] == 8.0

    settled = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(settled, "projected_subsidy_cents", 7400)
    assert_money_cents(settled, "actual_subsidy_cents", 0)
    assert settled["schedule_compliance"] == COMPLIANCE_COMPLIANT

    rows, meta = validate_paginated(
        api.list_placement_work_shifts(placement["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 7400)
