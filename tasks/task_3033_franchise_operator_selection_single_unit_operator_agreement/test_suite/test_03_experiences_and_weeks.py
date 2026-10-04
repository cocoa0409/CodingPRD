"""In-restaurant experience shift counting, operating-week calendar, and
week-close guards."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, TEST_USERS,
    setup_candidate, submit_application, advance_to_interviews, pass_interviews,
    pass_assessment, setup_restaurant_available, setup_active_operator,
    set_clock, create_experience_payload, create_week_payload,
)

ADMIN = TEST_USERS["system_admin_headers"]
FC = TEST_USERS["field_consultant_headers"]


def _drive_to_in_restaurant(api):
    """Candidate + application advanced into the IN_RESTAURANT stage with an
    AVAILABLE restaurant ready to host. Returns (candidate, application, restaurant)."""
    restaurant = setup_restaurant_available()
    candidate = setup_candidate()
    application = submit_application(candidate)
    app_id = application["id"]
    advance_to_interviews(app_id)
    pass_interviews(app_id)
    get_success_data(api.advance_application(app_id, FC))
    pass_assessment(app_id, candidate["id"])
    get_success_data(api.advance_application(app_id, FC))
    current = get_success_data(api.get_application(app_id, ADMIN))
    assert current["stage"] == "IN_RESTAURANT"
    return candidate, current, restaurant


def test_experience_zero_operating_days_rejected_empty_set(api):
    """PRD §3.4: "A block that contains no non-Sunday operating day at all — for
    instance, a block exactly one Sunday long — is refused with
    `ERR_NO_OPERATING_DAYS`."

    Design: Difficulty/boundary_precision_check/experience_zero_operating_days_rejected_empty_set
    """
    set_clock()
    _, application, restaurant = _drive_to_in_restaurant(api)
    # 2026-09-13 is a Sunday.
    resp = api.create_experience(
        application["id"],
        create_experience_payload(restaurant["id"],
                                  starts_on="2026-09-13T00:00:00Z",
                                  ends_on="2026-09-13T00:00:00Z"),
        FC,
    )
    validate_error(resp, ApiErrorId.ERR_NO_OPERATING_DAYS)


def test_experience_sunday_only_block_creates_no_experience(api):
    """PRD §3.4: "A block that contains no non-Sunday operating day at all — for
    instance, a block exactly one Sunday long — is refused with
    `ERR_NO_OPERATING_DAYS`."

    Design: Difficulty/boundary_precision_check/experience_zero_operating_days_rejected_empty_set
    """
    set_clock()
    _, application, restaurant = _drive_to_in_restaurant(api)
    resp = api.create_experience(
        application["id"],
        create_experience_payload(restaurant["id"],
                                  starts_on="2026-09-13T00:00:00Z",
                                  ends_on="2026-09-13T00:00:00Z"),
        FC,
    )
    validate_error(resp, ApiErrorId.ERR_NO_OPERATING_DAYS)
    listed = get_success_data(api.list_experiences_of_application(application["id"], FC))
    assert listed == [], f"no experience should persist after refusal, got {listed}"


def test_experience_block_spanning_sunday_counts_six_shifts(api):
    """PRD §3.4: "the system computes the block's `required_shift_count` at
    creation: the number of calendar dates in that inclusive range whose weekday
    is not Sunday."

    Design: Corner/state_machines/experience_block_spanning_sunday_counts_six_shifts
    """
    set_clock()
    _, application, restaurant = _drive_to_in_restaurant(api)
    # Monday 2026-09-07 through Sunday 2026-09-13 inclusive: 7 dates, 1 Sunday.
    resp = api.create_experience(
        application["id"],
        create_experience_payload(restaurant["id"],
                                  starts_on="2026-09-07T00:00:00Z",
                                  ends_on="2026-09-13T00:00:00Z"),
        FC,
    )
    experience = validate_success(resp, expected_status=201)
    assert experience["required_shift_count"] == 6
    assert experience["status"] == "SCHEDULED"
    assert experience["completed_shift_count"] == 0


def test_experience_complete_requires_all_shifts_signed_off(api):
    """PRD §3.4: "Attempting to complete a block whose signed-off shifts fall
    short is refused with `ERR_SHIFT_SHORTFALL`."

    Design: Corner/state_machines/experience_complete_requires_all_shifts_signed_off
    """
    set_clock()
    _, application, restaurant = _drive_to_in_restaurant(api)
    resp = api.create_experience(
        application["id"], create_experience_payload(restaurant["id"]), FC
    )
    experience = get_success_data(resp)
    assert experience["required_shift_count"] == 6
    set_clock("2026-09-07T00:00:00Z")
    for _ in range(5):
        validate_success(api.signoff_experience(application["id"], experience["id"], FC))
    resp = api.complete_experience(application["id"], experience["id"], FC)
    validate_error(resp, ApiErrorId.ERR_SHIFT_SHORTFALL)
    current = get_success_data(api.get_experience(experience["id"], FC))
    assert current["status"] == "IN_PROGRESS"
    assert current["completed_shift_count"] == 5


def test_operating_week_operating_day_count_is_always_six(api):
    """PRD §3.7: "Every operating week has an `operating_day_count` of exactly
    6, Monday through Saturday, because Sunday is excluded by the closed-Sunday
    calendar."
    PRD §3.6: "Every restaurant's `sunday_closed` flag is always true; the
    closed-Sunday calendar is not negotiable."

    Design: Corner/entities/operating_week_operating_day_count_is_always_six
    """
    set_clock()
    restaurant = setup_restaurant_available(site_code="GA-ATL-100")
    resp = api.create_week(restaurant["id"], create_week_payload(), FC)
    week = validate_success(resp, expected_status=201)
    assert week["operating_day_count"] == 6
    assert week["week_status"] == "PLANNED"
    current = get_success_data(api.get_restaurant(restaurant["id"], ADMIN))
    assert current["sunday_closed"] is True


def test_week_close_on_planned_week_returns_invalid_state(api):
    """PRD §2.8: "The order is: first, authentication of the headers
    (`ERR_UNAUTHENTICATED`); second, role authorization for the endpoint
    (`ERR_FORBIDDEN`); third, left-to-right existence of every path identifier
    (`ERR_NOT_FOUND`); fourth, whether the target resource's current state
    permits the requested transition (`ERR_INVALID_STATE`); and only then the
    domain-specific business checks — the scorecard-publish operator-state rule,
    the single-unit restriction, agreement immutability, the closed-Sunday block
    rule, the week-elapsed rule, the exit notice-period rule, the interview
    stage rule, successor eligibility, scorecard period overlap, missing
    actuals, duplicate statements, and duplicate weeks"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_week_close
    """
    set_clock()
    restaurant = setup_restaurant_available(site_code="GA-ATL-009")
    resp = api.create_week(restaurant["id"], create_week_payload(), FC)
    week = get_success_data(resp)
    # Clock is still 2026-09-01: the week is PLANNED (state violation) and the
    # six operating days have not elapsed (temporal violation); the state check
    # is listed earlier in the fixed priority order.
    resp = api.close_week(
        restaurant["id"], week["id"],
        {"actual_revenue_cents": 10_000_000, "expected_week_version": week["version"]},
        FC,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_week_close_on_planned_week_never_reports_week_not_elapsed(api):
    """PRD §2.8: "When a request could fail more than one rule, failures surface
    in a fixed priority order, and the caller sees the earliest applicable
    failure."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_week_close
    """
    set_clock()
    restaurant = setup_restaurant_available(site_code="GA-ATL-009")
    week = get_success_data(api.create_week(restaurant["id"], create_week_payload(), FC))
    resp = api.close_week(
        restaurant["id"], week["id"],
        {"actual_revenue_cents": 10_000_000, "expected_week_version": week["version"]},
        FC,
    )
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_INVALID_STATE"
    assert body["data"]["error_id"] != "ERR_WEEK_NOT_ELAPSED"
    current = get_success_data(api.get_week(week["id"], FC))
    assert current["week_status"] == "PLANNED"


def test_operating_week_duplicate_start_per_restaurant_rejected(api):
    """PRD §3.7: "the same restaurant may not hold two weeks with the same
    `week_start_on` — a duplicate is refused with `ERR_DUPLICATE_WEEK`."

    Design: Difficulty/resource_temporal_overlap/operating_week_unique_start_per_restaurant_zero_gap_calendar
    """
    set_clock()
    restaurant = setup_restaurant_available(site_code="GA-ATL-015")
    validate_success(api.create_week(restaurant["id"], create_week_payload(), FC), expected_status=201)
    resp = api.create_week(restaurant["id"], create_week_payload(), FC)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_WEEK)


def test_operating_week_duplicate_start_leaves_single_week(api):
    """PRD §3.7: "the same restaurant may not hold two weeks with the same
    `week_start_on` — a duplicate is refused with `ERR_DUPLICATE_WEEK`."

    Design: Difficulty/resource_temporal_overlap/operating_week_unique_start_per_restaurant_zero_gap_calendar
    """
    set_clock()
    restaurant = setup_restaurant_available(site_code="GA-ATL-015")
    validate_success(api.create_week(restaurant["id"], create_week_payload(), FC), expected_status=201)
    validate_error(api.create_week(restaurant["id"], create_week_payload(), FC),
                   ApiErrorId.ERR_DUPLICATE_WEEK)
    data, meta = validate_paginated(api.list_weeks_of_restaurant(restaurant["id"], FC))
    assert len(data) == 1
    assert meta["total_count"] == 1


def test_stale_week_version_on_close_rejected_occ(api):
    """PRD §2.9: "Closing an operating week likewise requires
    `expected_week_version`, holding the `version` of the week as the caller
    last read it. A mismatch with the week's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/stale_week_version_on_close_rejected_occ
    """
    set_clock()
    ctx = setup_active_operator()
    resp = api.create_week(ctx["restaurant"]["id"],
                           create_week_payload(week_start_on="2026-09-14T00:00:00Z"), FC)
    week = get_success_data(resp)
    set_clock("2026-09-21T00:00:00Z")
    resp = api.close_week(
        ctx["restaurant"]["id"], week["id"],
        {"actual_revenue_cents": 10_000_000, "expected_week_version": week["version"] - 1},
        FC,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = get_success_data(api.get_week(week["id"], FC))
    assert current["week_status"] == "OPEN"
