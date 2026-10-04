"""Property creation, the capacity ceilings, the clerk, and the roster."""
from test_helpers import (
    ApiErrorId,
    assert_resort,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_new_resort_opens_with_open_posture_and_empty_roster(api, platform_ops_headers):
    """PRD §2.5: "A newly created property begins with its `pool_posture` already
    `OPEN`, an `ops_run_index` of 0, `manager_override_used` false, and an empty
    rotation roster."

    Design: Corner/entities/resort_create_returns_initial_posture_and_roster
    """
    resort = fx.create_resort(name="Sandusky")
    assert_resort(resort)
    assert resort["pool_posture"] == "OPEN"
    assert resort["ops_run_index"] == 0
    assert resort["manager_override_used"] is False
    assert resort["managers"] == []


def test_resort_read_returns_the_declared_capacity_ceilings(api, platform_ops_headers):
    """PRD §2.5: "The two ceilings themselves may be revised after the property
    exists, but only by `platform_ops` and only against a supplied expected version
    of the property, so that a ceiling may not be changed out from under a caller
    who has already priced a sale against it."

    Design: Corner/entities/resort_get_returns_stored_capacity_ceilings
    """
    resort = fx.create_resort(name="Mason", park_capacity_occupancy_units=24, day_pass_cap_units=12)
    fetched = validate_success(api.get_resort(resort["id"], platform_ops_headers))
    assert fetched["park_capacity_occupancy_units"] == 24
    assert fetched["day_pass_cap_units"] == 12


def test_capacity_ledger_reports_every_named_bucket(api, aquatics_manager_headers):
    """PRD §2.5: "Stated as a rule, the total `occupancy_units` for a service date
    is the sum of the room contribution, the day-pass contribution, the group
    contribution, and the cabana contribution for that date, taken in that order,
    and `capacity_remaining_units` is the property's
    `park_capacity_occupancy_units` minus that total."

    Design: Corner/endpoints/capacity_read_reports_all_named_buckets
    """
    resort, room_type = fx.setup_resort_with_room_type(park_capacity_occupancy_units=20)
    fx.create_reservation(resort["id"], room_type["id"], guest_count=4)
    ledger = validate_success(
        api.get_capacity(
            resort["id"], aquatics_manager_headers, params={"service_date": "2026-09-03"}
        )
    )
    assert ledger["service_date"] == "2026-09-03"
    assert ledger["room_units_reserved"] == 4
    assert ledger["day_pass_reserved_units"] == 0
    assert ledger["group_reserved_units"] == 0
    assert ledger["cabana_day_units"] == 0
    assert ledger["occupancy_units"] == 4
    assert ledger["capacity_remaining_units"] == 16


def test_attendance_console_read_reports_the_same_occupancy_total(api, platform_ops_headers):
    """PRD §2.5: "An attendance-console variant of the same read reports the
    `service_date`, the `occupancy_units`, and the `capacity_remaining_units`
    alone."

    Design: Corner/errors/attendance_capacity_read_matches_capacity_read
    """
    resort, room_type = fx.setup_resort_with_room_type(park_capacity_occupancy_units=20)
    fx.create_reservation(resort["id"], room_type["id"], guest_count=4)
    console = validate_success(
        api.get_attendance_capacity(
            resort["id"], platform_ops_headers, params={"service_date": "2026-09-03"}
        )
    )
    assert console["occupancy_units"] == 4
    assert console["capacity_remaining_units"] == 16


def test_resort_version_increments_by_one_on_each_capacity_write(api, platform_ops_headers):
    """PRD §2.9: "In each case, if the supplied value does not match the parent
    entity's current `version`, the request is refused before any resource is
    created: the mismatched day-pass sale is refused with
    `ERR_STALE_RESORT_VERSION` (HTTP 412) and the mismatched cabana hold with
    `ERR_STALE_CABANA_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/resort_version_increments_on_every_capacity_write
    """
    resort = fx.create_resort()
    first_version = resort["version"]
    fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=2)
    refreshed = validate_success(api.get_resort(resort["id"], platform_ops_headers))
    assert refreshed["version"] == first_version + 1
    assert refreshed["version"] != first_version


def test_only_a_platform_operator_may_create_a_resort(api, platform_ops_headers, front_desk_headers):
    """PRD §2.1: "Behaviour that is reserved to a single role — creating properties
    and room types, editing capacity ceilings, publishing the rotation roster,
    lapsing advance holds, releasing a booked cabana, advancing the logical clock,
    simulating the deposit gateway — is exclusive to `platform_ops`."

    Design: Corner/rbac/front_desk_cannot_create_resort
    """
    existing = fx.create_resort(name="Concord")
    refused = api.create_resort(
        {
            "name": "Second Resort",
            "park_capacity_occupancy_units": 20,
            "day_pass_cap_units": 10,
            "arcade_credit_rate_cents_per_unit": 250,
        },
        front_desk_headers,
    )
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN.value)
    still_there = validate_success(api.get_resort(existing["id"], platform_ops_headers))
    assert still_there["name"] == "Concord"

def test_room_type_list_honours_limit_and_reports_the_envelope(api, anonymous_headers):
    """PRD §2.3: "`limit` caps how many resources are returned and defaults to 10
    when the caller omits it; the value must be at least 1 and at most 100."
    PRD §2.3: "Responses that carry a collection include the four pagination fields
    in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/room_type_list_paginates_with_envelope_fields
    """
    from test_helpers import validate_paginated

    resort = fx.create_resort(name="Gurnee")
    fx.create_room_type(resort["id"], code="WOLF", max_occupancy=8, base_rate_cents=18900)
    fx.create_room_type(resort["id"], code="KIDCABIN", max_occupancy=7, base_rate_cents=21500)
    fx.create_room_type(resort["id"], code="CABANA", max_occupancy=4, base_rate_cents=12000,
                        is_cabana=True)
    data, meta = validate_paginated(
        api.list_room_types(resort["id"], anonymous_headers, params={"limit": 2, "offset": 0})
    )
    assert isinstance(data, list) and len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_a_missing_role_header_is_refused_as_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that names a role the
    platform does not recognise, is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    resort = fx.create_resort(name="Sandusky")
    response = api.get_resort(resort["id"], {"X-User-ID": "no-role-here"})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_an_arbitrary_operator_id_is_accepted_for_an_opaque_role(api):
    """PRD §2.1: "Five of the six are opaque roles. When `X-User-Role` is
    `platform_ops`, `FrontDesk`, `AquaticsManager`, `GateAttendant`, or
    `Anonymous`, `X-User-ID` is an opaque operator identifier that is not tied to
    any persisted entity."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    resort = fx.create_resort(name="Sandusky")
    fetched = validate_success(api.get_resort(resort["id"], fx.PLATFORM_OPS))
    assert fetched["id"] == resort["id"]


def test_day_pass_detail_read_for_an_unminted_pass_is_not_found(api, front_desk_headers):
    """PRD §2.11: "The walk stops at the first identifier that does not resolve
    under the resource that precedes it, and the caller receives `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/day_pass_not_found_returns_404
    """
    resort = fx.create_resort(name="Concord")
    response = api.get_day_pass(
        resort["id"], "0f0f0f0f-0000-4000-8000-000000000000", front_desk_headers
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value)


def test_a_water_reading_against_an_unminted_attraction_is_not_found(api, aquatics_manager_headers):
    """PRD §2.11: "This ordering also applies to creation and modification
    operations whose body carries a foreign-key input rather than a path segment: a
    referenced resource is resolved before any business rule is evaluated, and a
    missing referent is reported as `ERR_NOT_FOUND` regardless of what other rule
    the request might also have violated."

    Design: Corner/entities/water_quality_log_rejects_unknown_attraction
    """
    resort = fx.create_resort(name="Bloomington")
    response = api.create_water_quality_log(
        resort["id"],
        {
            "attraction_id": "0f0f0f0f-0000-4000-8000-000000000001",
            "sampled_at": "2026-09-03T09:00:00Z",
            "ph_reading": 7.4,
            "free_chlorine_ppm": 2.0,
            "turbidity_ntu": 0.3,
        },
        aquatics_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value)


def test_the_arcade_post_role_list_admits_front_desk_and_refuses_the_gate(api, front_desk_headers,
                                                                         gate_attendant_headers):
    """PRD §3.4: "`FrontDesk` and `Anonymous` may post a charge against a folio, the
    latter so that a guest can top up their own band from their phone at the
    arcade."

    Design: Corner/endpoints/only_anonymous_and_front_desk_may_post_arcade_grants
    """
    resort, _room_type, _reservation, band = fx.setup_active_guest_band(guest_count=2)
    granted = validate_success(
        api.post_arcade_grant(resort["id"], band["id"], {"amount_cents": 100}, front_desk_headers),
        201,
    )
    assert granted["grant_status"] == "SUCCEEDED"
    denied = api.post_arcade_grant(
        resort["id"], band["id"], {"amount_cents": 100}, gate_attendant_headers
    )
    validate_error(denied, ApiErrorId.ERR_FORBIDDEN.value)


def test_a_day_pass_band_has_no_room_charge_privilege(api, anonymous_headers):
    """PRD §3.3: "In every other case — a day-pass or group-member band, or a
    reservation guest whose booking has not yet checked in — the band is issued
    with `room_charge_enabled` false and `arcade_credit_limit_cents` set to 0."

    Design: Corner/errors/room_charge_disabled_on_day_pass_band
    """
    resort, _day_pass, _room_type, band = fx.setup_day_pass_with_band(units_requested=2)
    assert band["room_charge_enabled"] is False
    response = api.post_arcade_grant(
        resort["id"], band["id"], {"amount_cents": 100}, anonymous_headers
    )
    validate_error(response, ApiErrorId.ERR_ROOM_CHARGE_DISABLED.value)
    assert validate_success(
        api.get_wristband(resort["id"], band["id"], anonymous_headers)
    )["arcade_credit_spent_cents"] == 0


def test_acting_as_another_group_is_refused_on_a_cabana_hold(api, platform_ops_headers):
    """PRD §2.1: "Ownership checks on any resource that references a `GroupBooking`
    compare the resource's foreign-key field to `X-User-ID`; a `Group` caller whose
    `X-User-ID` differs from the `group_booking_id` it targets is refused with
    `ERR_GROUP_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/errors/group_ownership_mismatch_on_cabana_hold
    """
    resort = fx.create_resort(name="Wisconsin Dells")
    own_group = fx.create_group_booking(resort["id"], member_count=2, deposit_paid_cents=1000)
    other_group = fx.create_group_booking(
        resort["id"], group_kind="SCHOOL", member_count=2, deposit_paid_cents=1000
    )
    cabana = fx.create_cabana(resort["id"], cabana_label="CAB-12")
    response = api.create_cabana_booking(
        resort["id"],
        {
            "cabana_id": cabana["id"],
            "group_booking_id": own_group["id"],
            "service_date": "2026-09-03",
            "start_minute": 600,
            "end_minute": 720,
            "member_units": 2,
            "expected_cabana_version": cabana["version"],
        },
        fx.group_headers_for(other_group["id"]),
    )
    validate_error(response, ApiErrorId.ERR_GROUP_OWNERSHIP_MISMATCH.value)
    assert validate_success(
        api.get_cabana(resort["id"], cabana["id"], platform_ops_headers)
    )["cabana_status"] == "AVAILABLE"


def test_anonymous_is_not_permitted_on_the_capacity_ledger(api, anonymous_headers):
    """PRD §4: "GET | `/resorts/{resort_id}/capacity` | Capacity ledger for one
    service date | platform_ops, FrontDesk, AquaticsManager, GateAttendant, Group"

    Design: Corner/rbac/anonymous_cannot_read_capacity_ledger
    """
    resort = fx.create_resort(name="Sandusky")
    response = api.get_capacity(
        resort["id"], anonymous_headers, params={"service_date": "2026-09-03"}
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN.value)


def test_the_gate_role_may_not_schedule_a_shift(api, aquatics_manager_headers,
                                                gate_attendant_headers):
    """PRD §3.6: "Starting a shift is an `AquaticsManager` action and it is where
    the certification rule bites."

    Design: Corner/rbac/gate_attendant_cannot_schedule_shifts
    """
    resort = fx.create_resort(name="Mason")
    attraction = fx.create_attraction(resort["id"])
    response = api.create_lifeguard_shift(
        resort["id"],
        {
            "attraction_id": attraction["id"],
            "staffer_name": "Bea",
            "certification_code": "LIFEGUARD",
            "shift_date": "2026-09-03",
            "start_minute": 540,
            "end_minute": 660,
            "rotation_minutes": 60,
        },
        gate_attendant_headers,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN.value)


def test_the_aquatics_manager_holds_both_closure_and_scheduling_authority(api,
                                                                         aquatics_manager_headers,
                                                                         platform_ops_headers):
    """PRD §2.1: "Everything a role may do is enumerated operation by operation in
    §4."

    Design: Corner/rbac/aquatics_manager_may_supersede_and_schedule
    """
    resort = fx.create_resort(name="Fitchburg")
    fx.add_manager(resort["id"], "Dana")
    attraction = fx.create_attraction(resort["id"])
    standing_log = fx.create_water_quality_log(
        resort["id"], attraction["id"], sampled_at="2026-09-03T09:00:00Z", ph_reading=6.0
    )
    shift = validate_success(
        api.create_lifeguard_shift(
            resort["id"],
            {
                "attraction_id": attraction["id"],
                "staffer_name": "Dana",
                "certification_code": "LIFEGUARD",
                "shift_date": "2026-09-03",
                "start_minute": 540,
                "end_minute": 660,
                "rotation_minutes": 60,
            },
            aquatics_manager_headers,
        ),
        201,
    )
    assert shift["shift_status"] == "SCHEDULED"
    reopened = validate_success(
        api.supersede_water_quality_log(
            resort["id"],
            standing_log["id"],
            {
                "sampled_at": "2026-09-03T10:00:00Z",
                "ph_reading": 7.4,
                "free_chlorine_ppm": 2.0,
                "turbidity_ntu": 0.3,
            },
            aquatics_manager_headers,
        )
    )
    assert reopened["log_status"] == "PASS"
    assert validate_success(api.get_resort(resort["id"], platform_ops_headers))[
        "pool_posture"
    ] == "OPEN"
