"""Screening gates and shift scheduling rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_kettle_location_ok,
    count_shifts_for_ringer,
    create_cleared_ringer,
    create_shift,
    create_shift_ok,
    get_kettle_location,
    get_ringer,
    get_shift,
    setup_ringing_scenario,
    validate_error,
    validate_success,
    work_shift,
)


def test_shift_create_against_draft_location_rejected(api, volunteer_coordinator_headers):
    """PRD §3.3: "Six gates stand between a request and a created shift. The
    kettle location must be `ACTIVE`".
    PRD §2.9: "The kettle location referenced by the request is `ACTIVE`;
    otherwise `ERR_LOCATION_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/shift_creation_depends_on_kettle_location_state
    """
    network = setup_ringing_scenario(activate_location=False)
    resp = create_shift(network.location["id"], network.ringer["id"],
                        "2026-11-17T09:00:00Z", "2026-11-17T17:00:00Z")
    validate_error(resp, ApiErrorId.ERR_LOCATION_NOT_ACTIVE)
    assert count_shifts_for_ringer(network.ringer["id"]) == 0


def test_shift_create_succeeds_once_location_activated(api, volunteer_coordinator_headers):
    """PRD §3.3: "Six gates stand between a request and a created shift. The
    kettle location must be `ACTIVE`; the host site behind it must hold an
    `APPROVED` permission; the owning campaign must be `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/shift_creation_depends_on_kettle_location_state
    """
    network = setup_ringing_scenario(activate_location=False)
    activated = activate_kettle_location_ok(network.location["id"])
    assert activated["status"] == "ACTIVE"

    shift = create_shift_ok(network.location["id"], network.ringer["id"],
                            "2026-11-17T09:00:00Z", "2026-11-17T17:00:00Z")
    assert shift["status"] == "SCHEDULED"
    assert shift["bell_ringer_id"] == network.ringer["id"]
    assert count_shifts_for_ringer(network.ringer["id"]) == 1


def test_shift_duration_480_accepted(api, volunteer_coordinator_headers):
    """PRD §2.9: "The shift duration does not exceed 480 minutes, where exactly
    480 minutes is accepted and 481 is rejected; otherwise `ERR_SHIFT_TOO_LONG`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/shift_duration_boundary_480_accepted_481_rejected
    """
    network = setup_ringing_scenario(
        ringer_overrides={"ringer_type": "PAID_SEASONAL", "hourly_rate_cents": 1500})
    shift = create_shift_ok(network.location["id"], network.ringer["id"],
                            "2026-11-17T09:00:00Z", "2026-11-17T17:00:00Z",
                            break_minutes=30)
    assert shift["status"] == "SCHEDULED"


def test_shift_duration_481_rejected(api, volunteer_coordinator_headers):
    """PRD §2.9: "The shift duration does not exceed 480 minutes, where exactly
    480 minutes is accepted and 481 is rejected; otherwise `ERR_SHIFT_TOO_LONG`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/shift_duration_boundary_480_accepted_481_rejected
    """
    network = setup_ringing_scenario(
        ringer_overrides={"ringer_type": "PAID_SEASONAL", "hourly_rate_cents": 1500})
    resp = create_shift(network.location["id"], network.ringer["id"],
                        "2026-11-18T09:00:00Z", "2026-11-18T17:01:00Z", break_minutes=30)
    validate_error(resp, ApiErrorId.ERR_SHIFT_TOO_LONG)
    assert count_shifts_for_ringer(network.ringer["id"]) == 0


def test_shift_paid_amount_uses_overtime_multiplier(api, volunteer_coordinator_headers):
    """PRD §3.3: "the `paid_hours` field is the paid minutes divided by sixty,
    rounded half up to two decimal places; and `paid_amount_cents` is the base
    minutes divided by sixty, multiplied by the ringer's `hourly_rate_cents`,
    plus the overtime minutes divided by sixty, multiplied by
    `hourly_rate_cents` and then by one and a half".

    Design: Difficulty/boundary_precision_check/shift_duration_boundary_480_accepted_481_rejected
    """
    network = setup_ringing_scenario(
        ringer_overrides={"ringer_type": "PAID_SEASONAL", "hourly_rate_cents": 1500})
    shift = create_shift_ok(network.location["id"], network.ringer["id"],
                            "2026-11-17T09:00:00Z", "2026-11-17T17:00:00Z",
                            break_minutes=30)

    completed = work_shift(shift["id"], network.ringer["id"], "2026-11-17T09:00:00Z")
    assert completed["status"] == "COMPLETED"
    # 480 minutes less a 30 minute break is 450 paid minutes = 7.5 hours.
    assert completed["paid_hours"] == pytest.approx(7.5, abs=0.001)
    # 7 base hours at 1500 plus 0.5 overtime hours at 1500 * 1.5.
    assert completed["paid_amount_cents"] == 11625


def test_shift_overlapping_existing_shift_rejected(api, volunteer_coordinator_headers):
    """PRD §3.3: "any overlap of the requested interval with one of them is
    refused with `ERR_SHIFT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/ringer_half_open_overlap_with_rest_buffer
    """
    network = setup_ringing_scenario()
    create_shift_ok(network.location["id"], network.ringer["id"],
                    "2026-11-16T09:00:00Z", "2026-11-16T17:00:00Z")

    resp = create_shift(network.location["id"], network.ringer["id"],
                        "2026-11-16T16:30:00Z", "2026-11-16T17:30:00Z")
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


def test_shift_gap_under_rest_buffer_rejected(api, volunteer_coordinator_headers):
    """PRD §3.3: "The gap between this shift and the ringer's nearest adjacent
    shift may not be shorter than 30 minutes, and a gap of exactly 30 minutes
    is accepted while 29 minutes is refused with
    `ERR_RINGER_REST_BUFFER_VIOLATION` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/ringer_half_open_overlap_with_rest_buffer
    """
    network = setup_ringing_scenario()
    create_shift_ok(network.location["id"], network.ringer["id"],
                    "2026-11-16T09:00:00Z", "2026-11-16T17:00:00Z")

    resp = create_shift(network.location["id"], network.ringer["id"],
                        "2026-11-16T17:15:00Z", "2026-11-16T18:00:00Z")
    validate_error(resp, ApiErrorId.ERR_RINGER_REST_BUFFER_VIOLATION)


def test_shift_gap_exactly_rest_buffer_accepted(api, volunteer_coordinator_headers):
    """PRD §3.3: "The gap between this shift and the ringer's nearest adjacent
    shift may not be shorter than 30 minutes, and a gap of exactly 30 minutes
    is accepted while 29 minutes is refused".
    PRD §3.3: "Creating a shift increases the ringer's `scheduled_hours` by the
    shift's duration in hours".

    Design: Difficulty/resource_temporal_overlap/ringer_half_open_overlap_with_rest_buffer
    """
    network = setup_ringing_scenario()
    create_shift_ok(network.location["id"], network.ringer["id"],
                    "2026-11-16T09:00:00Z", "2026-11-16T17:00:00Z")

    shift = create_shift_ok(network.location["id"], network.ringer["id"],
                            "2026-11-16T17:30:00Z", "2026-11-16T18:30:00Z")
    assert shift["status"] == "SCHEDULED"
    assert get_ringer(network.ringer["id"])["scheduled_hours"] == pytest.approx(9.0, abs=0.001)


# DELETED (Step 7, PRD-First): test_dual_violation_reports_rest_buffer_before_overlap
# asserted that a shift request which both overlaps an existing shift and leaves
# no rest gap reports ERR_RINGER_REST_BUFFER_VIOLATION (ladder step 19) rather
# than ERR_SHIFT_OVERLAP (step 22). PRD §3.3 scopes the rest-buffer rule to "the
# ringer's nearest *adjacent* shift" (a disjoint interval) and states the
# overlap rule separately, and §3.3's auto-assign candidate pool lists "no
# overlapping shift" and "no shift whose boundary lies within 30 minutes" as two
# distinct exclusions — so PRD does not uniquely determine the precedence, and
# the sibling test test_shift_overlapping_existing_shift_rejected (16:30-17:30
# over 09:00-17:00 -> ERR_SHIFT_OVERLAP) requires the opposite outcome for the
# same class of request. The precedence rule came only from the withheld design
# index (Difficulty/priority_pair_validation_conflict/
# business_safety_beats_business_constraint_on_shift_create). The 30-minute-gap
# half of this test is already covered by
# test_shift_gap_exactly_rest_buffer_accepted.


def test_shift_create_rejected_when_screening_not_cleared(api, volunteer_coordinator_headers):
    """PRD §2.9: "The bell ringer referenced by the request has a `CLEARED`
    screening whose expiry is later than the shift start; otherwise
    `ERR_SCREENING_NOT_CLEARED` (HTTP 409)."
    PRD §3.3: "A ringer may be engaged and unscreened, or screened and
    suspended; neither dimension implies the other."

    Design: Corner/state_machines/shift_create_rejected_when_screening_not_cleared
    """
    network = setup_ringing_scenario()
    ringer = get_ringer(network.ringer["id"])
    assert ringer["screening_status"] == "CLEARED"

    from test_helpers import create_ringer
    fresh = create_ringer(network.unit["id"], full_name="Ada Kim",
                          email="ada.kim@example.org",
                          date_of_birth="1991-03-14T00:00:00Z")
    assert fresh["screening_status"] == "NOT_STARTED"

    resp = create_shift(network.location["id"], fresh["id"],
                        "2026-11-20T09:00:00Z", "2026-11-20T17:00:00Z")
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED)

    after = get_ringer(fresh["id"])
    assert after["screening_status"] == "NOT_STARTED"
    assert count_shifts_for_ringer(fresh["id"]) == 0


def test_shift_complete_from_scheduled_rejected(api, volunteer_coordinator_headers):
    """PRD §3.3: "A `CHECKED_IN` shift moves to `COMPLETED`, which is terminal."
    PRD §2.9: "The target resource is in a state that permits the requested
    operation; otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/shift_complete_from_scheduled_rejected
    """
    network = setup_ringing_scenario()
    shift = create_shift_ok(network.location["id"], network.ringer["id"],
                            "2026-11-20T09:00:00Z", "2026-11-20T17:00:00Z")

    resp = api.complete_shift(shift["id"], volunteer_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    after = get_shift(shift["id"])
    assert after["status"] == "SCHEDULED"
    assert get_kettle_location(network.location["id"])["covered_minutes"] == 0


def test_minor_curfew_violation_rejected(api, volunteer_coordinator_headers):
    """PRD §2.9: "A ringer whose age at the shift start is under 18 is not
    scheduled to end after the 20:00 local curfew; otherwise
    `ERR_MINOR_CURFEW_VIOLATION` (HTTP 422)."

    Design: Corner/validations/minor_curfew_violation_rejected
    """
    network = setup_ringing_scenario()
    minor = create_cleared_ringer(network.unit["id"], full_name="Teen Ringer",
                                  email="teen.ringer@example.org",
                                  date_of_birth="2010-01-01T00:00:00Z")
    adult = create_cleared_ringer(network.unit["id"], full_name="Adult Ringer",
                                  email="adult.ringer@example.org",
                                  date_of_birth="1980-01-01T00:00:00Z")

    resp = create_shift(network.location["id"], minor["id"],
                        "2026-11-20T15:00:00Z", "2026-11-20T23:00:00Z")
    validate_error(resp, ApiErrorId.ERR_MINOR_CURFEW_VIOLATION)

    accepted = create_shift_ok(network.location["id"], adult["id"],
                               "2026-11-20T15:00:00Z", "2026-11-20T23:00:00Z")
    assert accepted["status"] == "SCHEDULED"
    assert count_shifts_for_ringer(minor["id"]) == 0


def test_labor_budget_exceeded_on_shift_completion(api, volunteer_coordinator_headers):
    """PRD §3.3: "completing a `PAID_SEASONAL` shift whose `paid_amount_cents`
    would push `labor_committed_cents` above the campaign's
    `labor_budget_cents` is refused with `ERR_LABOR_BUDGET_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/labor_budget_exceeded_on_shift_completion
    """
    from test_helpers import check_in, confirm_shift, get_campaign, set_clock
    network = setup_ringing_scenario(
        campaign_overrides={"labor_budget_cents": 5000},
        ringer_overrides={"ringer_type": "PAID_SEASONAL", "hourly_rate_cents": 1500})
    shift = create_shift_ok(network.location["id"], network.ringer["id"],
                            "2026-11-20T09:00:00Z", "2026-11-20T17:00:00Z")
    confirm_shift(shift["id"])
    set_clock("2026-11-20T09:00:00Z")
    validate_success(check_in(shift["id"], network.ringer["id"]))

    resp = api.complete_shift(shift["id"], volunteer_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_LABOR_BUDGET_EXCEEDED)

    assert get_shift(shift["id"])["status"] == "CHECKED_IN"
    assert get_campaign(network.campaign["id"])["labor_committed_cents"] == 0


def test_shift_with_exactly_thirty_minute_gap_accepted(api, volunteer_coordinator_headers):
    """PRD §2.9: "The gap between the ringer's consecutive shifts is at least 30
    minutes, where a gap of exactly 30 minutes is accepted and 29 is rejected;
    otherwise `ERR_RINGER_REST_BUFFER_VIOLATION` (HTTP 409)."
    PRD §3.3: "Creating a shift increases the ringer's `scheduled_hours` by the
    shift's duration in hours".

    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_shift_create
    """
    network = setup_ringing_scenario()
    create_shift_ok(network.location["id"], network.ringer["id"],
                    "2026-11-16T09:00:00Z", "2026-11-16T17:00:00Z")

    accepted = create_shift_ok(network.location["id"], network.ringer["id"],
                               "2026-11-16T17:30:00Z", "2026-11-16T18:30:00Z")
    assert accepted["status"] == "SCHEDULED"
    assert get_ringer(network.ringer["id"])["scheduled_hours"] == pytest.approx(9.0, abs=0.001)
