"""Installation jobs: notice coordination, labor accounting and overlap semantics."""

import pytest

from test_helpers import (
    HARDWARE,
    MANAGER,
    ApiErrorId,
    advance_clock,
    certify_visit,
    create_installation_job,
    get_success_data,
    pin_clock,
    provision_building,
    provision_property,
    provision_unit,
    read_guest_pass,
    read_installation_job,
    read_maintenance_visit,
    request_visit,
    setup_active_resident_with_guest_pass,
    setup_occupied_unit_with_online_lock,
    setup_unit_with_online_lock,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Labor accounting
# ---------------------------------------------------------------------------

def test_hub_install_lands_in_the_standard_tier_and_carries_rework(api):
    """PRD §3.8: "The base hours depend on the device: ... and 1.0 for a `HUB`. A
    base below 1.0 puts the job in the simple tier; a base at or above 1.0 puts
    it in the standard tier. A simple-tier job carries no rework surcharge; a
    standard-tier job carries a rework surcharge of one quarter of the base."

    Design: Difficulty/combinatorial_formula/installation_labor_tier_before_rework
    """
    pin_clock()
    prop = provision_property()
    bld = provision_building(prop["id"], wifi_rssi_dbm=-60)
    job, _ = create_installation_job(
        bld["id"], prop["id"], device_type="HUB",
        access_window_start="2026-09-02T13:00:00Z",
        access_window_end="2026-09-02T17:00:00Z",
    )
    started = validate_success(
        api.schedule_installation_job(
            job["id"], {"scheduled_start_at": "2026-09-02T13:30:00Z"}, HARDWARE
        ),
        200,
    )
    assert started["status"] == "IN_PROGRESS"

    completed = validate_success(api.complete_installation_job(job["id"], HARDWARE), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["labor_hours"] == pytest.approx(1.25, abs=0.01), (
        "base 1.0 puts the job in the standard tier, so a quarter of the base is added"
    )


def test_labor_hours_vary_by_device_class_within_the_simple_tier(api):
    """PRD §3.8: "The base hours depend on the device: 0.5 for a `SMART_LOCK`, 0.4
    for a `THERMOSTAT`, 0.25 for a `LEAK_SENSOR`, 0.75 for `COMMUNITY_ACCESS`,
    and 1.0 for a `HUB`."
    PRD §2.11: "Installation labor hours are expressed to two decimal places,
    rounded half-up."

    Design: Difficulty/combinatorial_formula/installation_labor_tier_before_rework
    """
    pin_clock()
    prop, bld, unit, lock = setup_unit_with_online_lock(unit_number="U-TR1")

    hours = {}
    for device_type, scheduled_start in (
        ("LEAK_SENSOR", "2026-09-03T09:30:00Z"),
        ("COMMUNITY_ACCESS", "2026-09-04T09:30:00Z"),
    ):
        job, _ = create_installation_job(
            bld["id"], prop["id"], unit_id=unit["id"], device_type=device_type,
            access_window_start="2026-09-03T09:00:00Z",
            access_window_end="2026-09-06T18:00:00Z",
        )
        get_success_data(
            api.schedule_installation_job(
                job["id"], {"scheduled_start_at": scheduled_start}, HARDWARE
            )
        )
        finished = validate_success(api.complete_installation_job(job["id"], HARDWARE), 200)
        hours[device_type] = finished["labor_hours"]

    assert hours["LEAK_SENSOR"] == pytest.approx(0.25, abs=0.01), "simple tier, no rework"
    assert hours["COMMUNITY_ACCESS"] == pytest.approx(0.75, abs=0.01), "simple tier, no rework"


def test_smart_lock_install_stays_in_the_simple_tier(api):
    """PRD §3.8: "0.5 for a `SMART_LOCK` ... A base below 1.0 puts the job in the
    simple tier ... A simple-tier job carries no rework surcharge."

    Design: Corner/calculations/labor_hours_smart_lock_simple_tier_has_no_rework
    """
    pin_clock()
    prop, bld, unit, lock = setup_unit_with_online_lock(unit_number="U-SS1")
    job, _ = create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="SMART_LOCK",
        access_window_start="2026-09-03T09:00:00Z",
        access_window_end="2026-09-03T12:00:00Z",
    )
    get_success_data(
        api.schedule_installation_job(
            job["id"], {"scheduled_start_at": "2026-09-03T09:30:00Z"}, HARDWARE
        )
    )

    completed = validate_success(api.complete_installation_job(job["id"], HARDWARE), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["labor_hours"] == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# Resident-coordinated installs
# ---------------------------------------------------------------------------

def test_resident_coordinated_install_without_any_visit_is_refused(api):
    """PRD §3.8: "When `requires_resident_coordination` is true, starting the job
    requires the target unit to be `OCCUPIED` and requires a `MaintenanceVisit`
    on that unit in `NOTICE_CERTIFIED` status whose window covers the job's
    `scheduled_start_at`."
    PRD §2.12: "this check guards ... installation-job start."

    Design: Difficulty/cross_entity_state_dependency/installation_schedule_requires_certified_notice_window
    """
    pin_clock()
    prop, bld, unit, lock, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-NN2", onboard=True
    )
    job, _ = create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="THERMOSTAT",
        requires_resident_coordination=True,
        access_window_start="2026-09-07T10:00:00Z",
        access_window_end="2026-09-07T12:00:00Z",
    )

    resp = api.schedule_installation_job(
        job["id"], {"scheduled_start_at": "2026-09-07T11:00:00Z"}, HARDWARE
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert read_installation_job(bld["id"], job["id"])["status"] == "SCHEDULED"


def test_resident_coordinated_install_with_an_uncertified_visit_is_refused(api):
    """PRD §3.8: "requires the target unit to be `OCCUPIED` and requires a
    `MaintenanceVisit` on that unit in `NOTICE_CERTIFIED` status whose window
    covers the job's `scheduled_start_at`."
    PRD §2.12: "this check guards ... installation-job start."

    Design: Difficulty/cross_entity_state_dependency/installation_schedule_requires_certified_notice_window
    """
    pin_clock()
    prop, bld, unit, lock, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-NN3", onboard=True
    )
    request_visit(
        unit["id"], start_at="2026-09-04T09:00:00Z", end_at="2026-09-04T11:00:00Z"
    )
    job, _ = create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="THERMOSTAT",
        requires_resident_coordination=True,
        access_window_start="2026-09-07T10:00:00Z",
        access_window_end="2026-09-07T12:00:00Z",
    )

    resp = api.schedule_installation_job(
        job["id"], {"scheduled_start_at": "2026-09-07T11:00:00Z"}, HARDWARE
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert read_installation_job(bld["id"], job["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Overlap semantics around an installation
# ---------------------------------------------------------------------------

def test_install_start_inside_the_buffer_after_a_maintenance_visit_is_rejected(api):
    """PRD §3.8: "starting a job requires that no maintenance visit and no tour
    session on that unit overlaps the install interval — the interval beginning
    at `scheduled_start_at` and running for 120 minutes, the estimated install
    duration — and that a 30-minute buffer around that span also be clear. Any
    collision is refused with `ERR_UNIT_SCHEDULE_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/installation_job_buffered_overlap_conflict
    """
    pin_clock()
    prop, bld, unit = _unit_with_certified_visit(
        unit_number="U-BB1", visit_start="2026-09-04T09:00:00Z",
        visit_end="2026-09-04T11:00:00Z",
    )
    job, _ = create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="THERMOSTAT",
        access_window_start="2026-09-04T13:00:00Z",
        access_window_end="2026-09-04T17:00:00Z",
    )

    resp = api.schedule_installation_job(
        job["id"], {"scheduled_start_at": "2026-09-04T11:15:00Z"}, HARDWARE
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_SCHEDULE_CONFLICT, 409)


def test_install_start_clear_of_the_buffer_is_accepted(api):
    """PRD §3.8: "and that a 30-minute buffer around that span also be clear. Any
    collision is refused with `ERR_UNIT_SCHEDULE_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/installation_job_buffered_overlap_conflict
    """
    pin_clock()
    prop, bld, unit = _unit_with_certified_visit(
        unit_number="U-BB2", visit_start="2026-09-04T09:00:00Z",
        visit_end="2026-09-04T11:00:00Z",
    )
    job, _ = create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="THERMOSTAT",
        access_window_start="2026-09-04T13:00:00Z",
        access_window_end="2026-09-04T17:00:00Z",
    )

    started = validate_success(
        api.schedule_installation_job(
            job["id"], {"scheduled_start_at": "2026-09-04T12:00:00Z"}, HARDWARE
        ),
        200,
    )
    assert started["status"] == "IN_PROGRESS"


def test_install_start_one_minute_inside_the_buffer_is_still_rejected(api):
    """PRD §3.8: "the interval beginning at `scheduled_start_at` and running for
    120 minutes, the estimated install duration — and that a 30-minute buffer
    around that span also be clear."

    Design: Difficulty/resource_temporal_overlap/installation_job_buffered_overlap_conflict
    """
    pin_clock()
    prop, bld, unit = _unit_with_certified_visit(
        unit_number="U-BB3", visit_start="2026-09-04T09:00:00Z",
        visit_end="2026-09-04T11:00:00Z",
    )
    too_early, _ = create_installation_job(
        bld["id"], prop["id"], unit_id=unit["id"], device_type="THERMOSTAT",
        access_window_start="2026-09-04T13:00:00Z",
        access_window_end="2026-09-04T17:00:00Z",
    )
    resp = api.schedule_installation_job(
        too_early["id"], {"scheduled_start_at": "2026-09-04T11:29:00Z"}, HARDWARE
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_SCHEDULE_CONFLICT, 409)


def test_guest_pass_overlapping_an_existing_pass_is_rejected(api):
    """PRD §2.6: "Occupations of the same unit may not overlap. Any request that
    would create or start an occupation whose interval intersects an existing one
    on the same unit is refused with `ERR_UNIT_SCHEDULE_CONFLICT` and an HTTP
    status of 409. The rule is checked when a maintenance visit is requested,
    when a guest pass is issued against a unit, and when a scheduled installation
    job is started."

    Design: Difficulty/resource_temporal_overlap/guest_pass_strict_overlap_rejected_adjacent_accepted
    """
    pin_clock()
    prop, bld, unit, device, resident = setup_occupied_unit_with_online_lock(
        unit_number="U-GG1", onboard=True
    )
    # An existing occupation of the same unit: a certified maintenance window
    # spanning 2026-09-10T09:00–2026-09-12T09:00. PRD §2.6 names
    # `MaintenanceVisit` and `TourSession` as the two resource types that occupy
    # a unit's calendar, and says the overlap rule is checked when a guest pass
    # is issued against a unit.
    visit = request_visit(
        unit["id"], start_at="2026-09-10T09:00:00Z", end_at="2026-09-12T09:00:00Z"
    )
    certify_visit(visit["id"], notice_mailed_at="2026-09-01T09:00:00Z")

    resp = api.issue_guest_pass(
        unit["id"],
        {"host_resident_id": resident["id"], "guest_label": "Overlap",
         "start_at": "2026-09-11T10:00:00Z", "end_at": "2026-09-13T10:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_SCHEDULE_CONFLICT, 409)
    assert get_success_data(
        api.list_guest_passes(MANAGER, {"unit_id": unit["id"]})
    ) == []
    assert read_maintenance_visit(unit["id"], visit["id"])["status"] == "NOTICE_CERTIFIED"


def test_guest_pass_adjacent_to_an_existing_pass_is_accepted(api):
    """PRD §2.6: "Occupations of the same unit may not overlap. Any request that
    would create or start an occupation whose interval intersects an existing one
    on the same unit is refused with `ERR_UNIT_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/guest_pass_strict_overlap_rejected_adjacent_accepted
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        start_at="2026-09-10T09:00:00Z", end_at="2026-09-12T09:00:00Z",
        unit_number="U-GG2",
    )

    adj = validate_success(
        api.issue_guest_pass(
            unit["id"],
            {"host_resident_id": resident["id"], "guest_label": "Adjacent",
             "start_at": "2026-09-12T09:00:00Z", "end_at": "2026-09-13T09:00:00Z"},
            MANAGER,
        ),
        201,
    )
    assert adj["status"] == "ACTIVE"
    assert read_guest_pass(unit["id"], gpass["id"])["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Guest-pass extension
# ---------------------------------------------------------------------------

def test_extending_an_active_guest_pass_is_rejected(api):
    """PRD §3.6: "An expired pass can be revived. A `PropertyManager` or the
    resident host extends a pass by supplying `new_end_at`, and the platform
    requires three things: the pass is `EXPIRED`."

    Design: Corner/state_machines/guest_pass_extend_from_active_returns_invalid_state
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        start_at="2026-09-05T09:00:00Z", end_at="2026-09-06T09:00:00Z",
        unit_number="U-AA1",
    )

    resp = api.extend_guest_pass(gpass["id"], {"new_end_at": "2026-09-08T09:00:00Z"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    stored = read_guest_pass(unit["id"], gpass["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["end_at"].startswith("2026-09-06T09:00")


def test_expired_guest_pass_is_revived_by_an_extension_past_the_present(api):
    """PRD §3.6: "On success the pass returns to `ACTIVE` and its `end_at`
    becomes the supplied value."
    PRD §3.10: "guest passes whose `end_at` has arrived are expired."

    Design: Corner/state_machines/guest_pass_extend_from_active_returns_invalid_state
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        start_at="2026-09-05T09:00:00Z", end_at="2026-09-06T09:00:00Z",
        unit_number="U-AA2",
    )
    advance_clock("2026-09-07T00:00:00Z")
    assert read_guest_pass(unit["id"], gpass["id"])["status"] == "EXPIRED"

    revived = validate_success(
        api.extend_guest_pass(gpass["id"], {"new_end_at": "2026-09-08T09:00:00Z"}, MANAGER),
        200,
    )
    assert revived["status"] == "ACTIVE"
    assert revived["end_at"].startswith("2026-09-08T09:00")


def test_guest_pass_extension_into_the_past_is_refused(api):
    """PRD §3.6: "the new end is later than the current logical clock ... A pass
    whose host is revoked, or whose new window does not extend past the present,
    is refused with `ERR_CREDENTIAL_OUT_OF_SCOPE` (409)."

    Design: Corner/state_machines/guest_pass_extend_from_active_returns_invalid_state
    """
    pin_clock()
    prop, bld, unit, device, resident, gpass = setup_active_resident_with_guest_pass(
        start_at="2026-09-05T09:00:00Z", end_at="2026-09-06T09:00:00Z",
        unit_number="U-AA3",
    )
    advance_clock("2026-09-07T00:00:00Z")

    resp = api.extend_guest_pass(gpass["id"], {"new_end_at": "2026-09-02T09:00:00Z"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_OUT_OF_SCOPE, 409)


# ---------------------------------------------------------------------------
# Local helper
# ---------------------------------------------------------------------------

def _unit_with_certified_visit(unit_number, visit_start, visit_end):
    """Building that passes connectivity, one unit, and a certified visit on it."""
    pin_clock()
    prop = provision_property(unit_capacity=2)
    bld = provision_building(prop["id"], wifi_rssi_dbm=-60)
    unit = provision_unit(prop["id"], unit_number=unit_number, building_id=bld["id"])
    visit = request_visit(unit["id"], start_at=visit_start, end_at=visit_end)
    certify_visit(visit["id"], notice_mailed_at="2026-09-01T08:00:00Z")
    return prop, bld, unit