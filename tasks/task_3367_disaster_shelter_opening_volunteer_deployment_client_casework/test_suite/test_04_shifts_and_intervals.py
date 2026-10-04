"""Shift intervals, workload caps, check-in windows and clock-driven deployment travel."""
from test_helpers import (
    ApiErrorId,
    create_shift,
    set_clock,
    setup_open_shelter,
    validate_error,
    validate_success,
)


def test_shift_starting_exactly_when_another_ends_is_accepted(api):
    """PRD §2.7: "The shift interval is inclusive at its start and exclusive at its end, and
    `shift_end_at` must be strictly after `shift_start_at`."

    Design: Difficulty/resource_temporal_overlap/shift_half_open_interval_adjacency_allowed
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    first = create_shift(
        bundle["deployment_id"], bundle["shelter_id"],
        functional_area="REGISTRATION",
        shift_start_at="2026-09-03T08:00:00Z", shift_end_at="2026-09-03T16:00:00Z")

    adjacent = validate_success(api.create_shift(
        {"volunteer_deployment_id": bundle["deployment_id"],
         "shelter_operation_id": bundle["shelter_id"],
         "functional_area": "FEEDING",
         "shift_start_at": "2026-09-03T16:00:00Z",
         "shift_end_at": "2026-09-03T20:00:00Z"},
        manager), 201)
    assert adjacent["status"] == "SCHEDULED", (
        "the end instant is exclusive, so an abutting shift does not overlap")
    assert adjacent["id"] != first["id"]


def test_shift_intruding_by_one_minute_is_rejected(api):
    """PRD §2.7: "A new shift assignment whose `shift_start_at` and `shift_end_at` interval
    intersects any non-cancelled shift already held by the same volunteer is refused with
    `ERR_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/shift_half_open_interval_adjacency_allowed
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    create_shift(
        bundle["deployment_id"], bundle["shelter_id"],
        functional_area="REGISTRATION",
        shift_start_at="2026-09-03T08:00:00Z", shift_end_at="2026-09-03T16:00:00Z")

    resp = api.create_shift(
        {"volunteer_deployment_id": bundle["deployment_id"],
         "shelter_operation_id": bundle["shelter_id"],
         "functional_area": "HEALTH",
         "shift_start_at": "2026-09-03T15:59:00Z",
         "shift_end_at": "2026-09-03T18:00:00Z"},
        manager)
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


def test_overlapping_fourth_shift_reports_the_temporal_error(api):
    """PRD §2.11: "Sixth, the interval collision checks of §2.7. Seventh, the uniqueness and
    workload caps — `incident_code` and `fund_code` uniqueness, the 21-day rotation limit, the
    40-day annual cap, the 3-shift ceiling, and the segregation-of-duties pairs."

    PRD §2.7: "A single deployment may hold at most 3 shift assignments that have not reached a
    terminal state; a fourth is refused with `ERR_MAX_SHIFTS_EXCEEDED` at HTTP status 409."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_fourth_overlapping_shift
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    create_shift(bundle["deployment_id"], bundle["shelter_id"], functional_area="REGISTRATION",
                 shift_start_at="2026-09-03T08:00:00Z", shift_end_at="2026-09-03T16:00:00Z")
    create_shift(bundle["deployment_id"], bundle["shelter_id"], functional_area="FEEDING",
                 shift_start_at="2026-09-03T17:00:00Z", shift_end_at="2026-09-03T21:00:00Z")
    create_shift(bundle["deployment_id"], bundle["shelter_id"], functional_area="DORMITORY",
                 shift_start_at="2026-09-04T08:00:00Z", shift_end_at="2026-09-04T12:00:00Z")

    resp = api.create_shift(
        {"volunteer_deployment_id": bundle["deployment_id"],
         "shelter_operation_id": bundle["shelter_id"],
         "functional_area": "HEALTH",
         "shift_start_at": "2026-09-03T15:00:00Z",
         "shift_end_at": "2026-09-03T18:00:00Z"},
        manager)
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


def test_fourth_shift_without_overlap_still_breaches_the_ceiling(api):
    """PRD §2.7: "A single deployment may hold at most 3 shift assignments that have not
    reached a terminal state; a fourth is refused with `ERR_MAX_SHIFTS_EXCEEDED` at HTTP
    status 409."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_fourth_overlapping_shift
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    create_shift(bundle["deployment_id"], bundle["shelter_id"], functional_area="REGISTRATION",
                 shift_start_at="2026-09-03T06:00:00Z", shift_end_at="2026-09-03T08:00:00Z")
    create_shift(bundle["deployment_id"], bundle["shelter_id"], functional_area="FEEDING",
                 shift_start_at="2026-09-03T10:00:00Z", shift_end_at="2026-09-03T12:00:00Z")
    create_shift(bundle["deployment_id"], bundle["shelter_id"], functional_area="DORMITORY",
                 shift_start_at="2026-09-03T14:00:00Z", shift_end_at="2026-09-03T16:00:00Z")

    resp = api.create_shift(
        {"volunteer_deployment_id": bundle["deployment_id"],
         "shelter_operation_id": bundle["shelter_id"],
         "functional_area": "HEALTH",
         "shift_start_at": "2026-09-03T18:00:00Z",
         "shift_end_at": "2026-09-03T20:00:00Z"},
        manager)
    validate_error(resp, ApiErrorId.ERR_MAX_SHIFTS_EXCEEDED)


def test_max_shifts_ceiling_is_isolated_from_the_overlap_rule(api):
    """PRD §2.7: "A single deployment may hold at most 3 shift assignments that have not reached
    a terminal state; a fourth is refused with `ERR_MAX_SHIFTS_EXCEEDED` at HTTP status 409."

    Design: Corner/errors/max_shifts_exceeded_on_fourth_non_overlapping_shift
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    starts = [("2026-09-03T06:00:00Z", "2026-09-03T08:00:00Z"),
              ("2026-09-03T10:00:00Z", "2026-09-03T12:00:00Z"),
              ("2026-09-03T14:00:00Z", "2026-09-03T16:00:00Z")]
    for area, (start, end) in zip(("REGISTRATION", "FEEDING", "DORMITORY"), starts):
        create_shift(bundle["deployment_id"], bundle["shelter_id"], functional_area=area,
                     shift_start_at=start, shift_end_at=end)

    resp = api.create_shift(
        {"volunteer_deployment_id": bundle["deployment_id"],
         "shelter_operation_id": bundle["shelter_id"],
         "functional_area": "SECURITY",
         "shift_start_at": "2026-09-03T18:00:00Z",
         "shift_end_at": "2026-09-03T20:00:00Z"},
        manager)
    validate_error(resp, ApiErrorId.ERR_MAX_SHIFTS_EXCEEDED)


def test_check_in_outside_the_window_is_refused(api):
    """PRD §3.4: "the check-in must occur no earlier than 60 minutes before `shift_start_at`,
    and the shelter must be in `OPEN` or `RESTRICTED` posture."

    Design: Corner/state_machines/shift_check_in_before_window_rejected
    """
    bundle = setup_open_shelter()
    volunteer_hdr = bundle["volunteer_headers"]

    shift = create_shift(
        bundle["deployment_id"], bundle["shelter_id"],
        functional_area="REGISTRATION",
        shift_start_at="2026-09-03T20:00:00Z", shift_end_at="2026-09-04T00:00:00Z")

    # The clock sits at 2026-09-03T00:00Z, twenty hours before the shift starts.
    resp = api.check_in_shift(shift["id"], volunteer_hdr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    set_clock("2026-09-03T19:30:00Z")
    checked_in = validate_success(api.check_in_shift(shift["id"], volunteer_hdr))
    assert checked_in["status"] == "CHECKED_IN"


def test_clock_alone_carries_the_deployment_through_travel(api):
    """PRD §2.10: "The complete set of clock-driven transitions is: a volunteer deployment
    moving `APPROVED` to `IN_TRANSIT` and then `IN_TRANSIT` to `ARRIVED`."

    PRD §3.4: "It moves from `APPROVED` to `IN_TRANSIT` as soon as the logical clock reaches
    `rotation_start_at` minus the lead time for its `travel_mode` — one day for `AIR`."

    Design: Corner/cross_cutting_complexity_layers/clock_drives_deployment_arrival_automatically
    """
    bundle = setup_open_shelter(open_the_shelter=False, open_clock="2026-09-01T00:00:00Z")
    coord = bundle["coordinator_headers"]

    approved = validate_success(api.get_deployment(bundle["deployment_id"], coord))
    assert approved["status"] == "APPROVED", "the default clock precedes the lead time"

    set_clock("2026-09-02T12:00:00Z")
    in_transit = validate_success(api.get_deployment(bundle["deployment_id"], coord))
    assert in_transit["status"] == "IN_TRANSIT"

    set_clock("2026-09-03T00:00:00Z")
    arrived = validate_success(api.get_deployment(bundle["deployment_id"], coord))
    assert arrived["status"] == "ARRIVED"

    region = validate_success(api.get_region(bundle["region_id"], coord))
    assert region["deployed_volunteer_count"] == 1
