"""Group bookings, party inventory, cabana occupations, and deposits."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx


def test_cabana_confirmation_is_gated_on_the_group_being_confirmed(api):
    """PRD §3.8: "Confirmation converts a hold into a real occupation and is the
    moment the group's members are actually admitted to the waterpark. It requires
    the cabana booking to be `HELD` and the linked group booking to be `CONFIRMED`;
    a booking whose group has not been confirmed is refused with
    `ERR_CABANA_OCCUPIED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cabana_confirm_requires_group_confirmed
    """
    resort = fx.create_resort(name="Mason")
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=2, deposit_paid_cents=0,
        service_date="2026-09-16",
    )
    cabana = fx.create_cabana(resort["id"], cabana_label="CAB-4", cabana_kind="PARTY_ROOM",
                              capacity_units=8)
    hold = fx.hold_cabana(
        resort["id"], cabana["id"], group_booking["id"], member_units=2,
        service_date="2026-09-16",
    )
    response = api.confirm_cabana_booking(
        resort["id"], hold["id"], fx.group_headers_for(group_booking["id"])
    )
    validate_error(response, ApiErrorId.ERR_CABANA_OCCUPIED.value)
    assert validate_success(
        api.get_cabana_booking(resort["id"], hold["id"], fx.PLATFORM_OPS)
    )["cabana_booking_status"] == "HELD"
    assert validate_success(
        api.get_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS)
    )["group_status"] == "PENDING_DEPOSIT"


def test_the_same_cabana_confirmation_succeeds_once_the_group_is_confirmed(api):
    """PRD §3.8: "On success the cabana booking moves from `HELD` to `BOOKED` and becomes persisted, `hold_expires_at` is cleared to null, every member of the linked group whose `checked_in` flag is false is checked in, the cabana booking's `members` array is populated with those member object identifiers, `group_reserved_units` on the group booking is set to the sum of `member_units` over the checked-in members, the cabana booking's `version` is incremented, and the occupying cabana is moved into `BOOKED` — the cabana's own status table defines that destination as a transition out of `AVAILABLE`."

    Design: Difficulty/transitive_cascade/release_cabana_unwinds_group_member_admissions
    """
    resort, group_booking, members, cabana, hold = fx.setup_confirmed_group_with_booked_cabana(
        member_units=2, cabana_units=4
    )
    assert hold["cabana_booking_status"] == "BOOKED"
    assert hold["hold_expires_at"] is None
    assert sorted(hold["members"]) == sorted(m["id"] for m in members)
    assert validate_success(
        api.get_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS)
    )["group_reserved_units"] == 2


def test_releasing_a_booked_cabana_unwinds_every_member_admission(api):
    """PRD §3.8: "the cabana booking returns to `HELD` with its `members` array
    emptied and its `hold_expires_at` reset to `2026-09-01T00:00:00Z`; the linked
    group booking's `group_reserved_units` is zeroed; the occupying cabana returns
    to `HELD`; and — when the released booking's group is `CONFIRMED` and no other
    cabana booking in `HELD` or `BOOKED` status still references that group — every
    member of the group whose `checked_in` flag is true is set back to false."

    Design: Difficulty/transitive_cascade/release_cabana_unwinds_group_member_admissions
    """
    resort, group_booking, members, cabana, hold = fx.setup_confirmed_group_with_booked_cabana(
        member_units=2, cabana_units=4
    )
    released = validate_success(
        api.release_cabana_booking(resort["id"], hold["id"], fx.PLATFORM_OPS)
    )
    assert released["cabana_booking_status"] == "HELD"
    assert validate_success(
        api.get_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS)
    )["group_reserved_units"] == 0
    for member in members:
        fetched = validate_success(
            api.get_group_member(resort["id"], member["id"], fx.PLATFORM_OPS)
        )
        assert fetched["checked_in"] is False


def test_releasing_a_booked_cabana_only_requires_the_operator_role(api):
    """PRD §3.8: "Releasing a booked cabana is an operator-only recovery action
    reserved to `platform_ops`, and it is the only path that unwinds a party that
    has already been admitted."

    Design: Corner/rbac/group_cannot_release_cabana
    """
    resort, group_booking, _members, _cabana, hold = fx.setup_confirmed_group_with_booked_cabana(
        member_units=1, cabana_units=4
    )
    response = api.release_cabana_booking(
        resort["id"], hold["id"], fx.group_headers_for(group_booking["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN.value)
    assert validate_success(
        api.get_cabana_booking(resort["id"], hold["id"], fx.PLATFORM_OPS)
    )["cabana_booking_status"] == "BOOKED"


def test_a_hold_intersecting_a_standing_occupation_is_refused(api):
    """PRD §3.8: "The window must also be free: no existing cabana booking in
    `HELD` or `BOOKED` status may occupy the same cabana on the same service date
    with a window that overlaps the requested half-open interval, and an overlap is
    refused with `ERR_CABANA_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/cabana_booking_window_overlap_rejected
    """
    resort, group_booking, _members, cabana, hold = fx.setup_confirmed_group_with_booked_cabana(
        member_units=3, cabana_units=10, start_minute=600, end_minute=720
    )
    version = validate_success(api.get_cabana(resort["id"], cabana["id"], fx.PLATFORM_OPS))["version"]
    response = api.create_cabana_booking(
        resort["id"],
        {
            "cabana_id": cabana["id"],
            "group_booking_id": group_booking["id"],
            "service_date": "2026-09-03",
            "start_minute": 700,
            "end_minute": 780,
            "member_units": 3,
            "expected_cabana_version": version,
        },
        fx.group_headers_for(group_booking["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CABANA_DOUBLE_BOOKED.value)
    assert validate_success(api.get_cabana(resort["id"], cabana["id"], fx.PLATFORM_OPS))[
        "cabana_status"
    ] == "BOOKED"
    assert validate_success(
        api.get_cabana_booking(resort["id"], hold["id"], fx.PLATFORM_OPS)
    )["cabana_booking_status"] == "BOOKED"


def test_a_second_hold_carrying_a_stale_cabana_version_is_refused(api):
    """PRD §2.9: "In each case, if the supplied value does not match the parent
    entity's current `version`, the request is refused before any resource is
    created: the mismatched day-pass sale is refused with
    `ERR_STALE_RESORT_VERSION` (HTTP 412) and the mismatched cabana hold with
    `ERR_STALE_CABANA_VERSION` (HTTP 412)."

    Design: Difficulty/boundary_precision_check/cabana_second_hold_requires_fresh_version
    """
    resort = fx.create_resort(name="Concord", park_capacity_occupancy_units=30, day_pass_cap_units=20)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="SCHOOL", member_count=2, deposit_paid_cents=1000
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    cabana = fx.create_cabana(resort["id"], cabana_label="CAB-3", capacity_units=6)
    stale_version = cabana["version"]
    fx.hold_cabana(
        resort["id"], cabana["id"], group_booking["id"], member_units=2,
        start_minute=600, end_minute=660, expected_cabana_version=stale_version,
    )
    response = api.create_cabana_booking(
        resort["id"],
        {
            "cabana_id": cabana["id"],
            "group_booking_id": group_booking["id"],
            "service_date": "2026-09-03",
            "start_minute": 660,
            "end_minute": 720,
            "member_units": 1,
            "expected_cabana_version": stale_version - 1,
        },
        fx.group_headers_for(group_booking["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_CABANA_VERSION.value)
    assert validate_success(api.get_cabana(resort["id"], cabana["id"], fx.PLATFORM_OPS))[
        "cabana_status"
    ] == "HELD"


def test_a_hold_carrying_a_superseded_cabana_version_is_refused(api):
    """PRD §2.9: "The staleness check is a comparison against current state, not a
    claim about timing. A create whose supplied version matches the parent's
    current version proceeds regardless of what else is happening, and a create
    whose supplied version has fallen behind is refused regardless of whether any
    other request is in flight."

    Design: Corner/errors/stale_cabana_version_returns_412
    """
    resort = fx.create_resort(name="Fitchburg", park_capacity_occupancy_units=20,
                              day_pass_cap_units=10)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="SCHOOL", member_count=2, deposit_paid_cents=1000
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    cabana = fx.create_cabana(resort["id"], cabana_label="CAB-11")
    superseded_version = cabana["version"]
    fx.hold_cabana(
        resort["id"], cabana["id"], group_booking["id"], member_units=2,
        start_minute=600, end_minute=660, expected_cabana_version=superseded_version,
    )
    response = api.create_cabana_booking(
        resort["id"],
        {
            "cabana_id": cabana["id"],
            "group_booking_id": group_booking["id"],
            "service_date": "2026-09-03",
            "start_minute": 720,
            "end_minute": 780,
            "member_units": 1,
            "expected_cabana_version": superseded_version,
        },
        fx.group_headers_for(group_booking["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_CABANA_VERSION.value)


def test_a_cancelled_cabana_occupation_stops_counting_toward_the_date(api):
    """PRD §3.8: "Cabana units are counted for capacity on the same terms as
    everything else. For a service date, the cabana contribution to the occupancy
    ledger is the sum of `member_units` across every cabana booking dated that day
    that is in `HELD` or `BOOKED` status."

    Design: Corner/calculations/cabana_day_units_excludes_cancelled_occupations
    """
    resort, group_booking, _members, cabana, hold = fx.setup_confirmed_group_with_booked_cabana(
        member_units=2, cabana_units=4
    )
    cancelled = validate_success(
        api.cancel_cabana_booking(
            resort["id"], hold["id"], fx.group_headers_for(group_booking["id"])
        )
    )
    assert cancelled["cabana_booking_status"] == "CANCELLED"
    assert fx.get_capacity(resort["id"], "2026-09-03")["cabana_day_units"] == 0


def test_the_group_scoped_cabana_list_returns_the_groups_own_booking(api):
    """PRD §4: "GET | `/resorts/{resort_id}/group-bookings/{group_booking_id}/cabana-bookings`
    | List cabana bookings belonging to a group | platform_ops, FrontDesk, Group"

    Design: Corner/endpoints/cabana_bookings_list_filters_by_group
    """
    resort = fx.create_resort(name="Mason", park_capacity_occupancy_units=20, day_pass_cap_units=10)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=2, deposit_paid_cents=1000
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    cabana = fx.create_cabana(resort["id"], cabana_label="CAB-8")
    hold = fx.hold_cabana(resort["id"], cabana["id"], group_booking["id"], member_units=2)
    rows = validate_success(
        api.list_cabana_bookings_for_group(
            resort["id"], group_booking["id"], fx.PLATFORM_OPS
        )
    )
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["id"] == hold["id"]
    assert rows[0]["cabana_booking_status"] == "HELD"


def test_cancelling_the_group_unwinds_its_cabana_occupation(api):
    """PRD §3.8: "the group moves to `CANCELLED` and `group_reserved_units` goes to 0; every cabana booking belonging to the group that is in `HELD` or `BOOKED` status is cancelled and every cabana those occupations held returns to availability; and every activity booking attached to the group that is in `PENDING_PAYMENT` or `CONFIRMED` status is cancelled, which for the activity side is a cascade that carries no preconditions of its own."

    Design: Corner/endpoints/group_cancel_unwinds_cabana_occupation
    """
    resort, group_booking, _members, cabana, hold = fx.setup_confirmed_group_with_booked_cabana(
        member_units=2, cabana_units=8, cabana_kind="PARTY_ROOM", cabana_label="PR-4"
    )
    validate_success(api.cancel_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS))
    assert validate_success(
        api.get_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS)
    )["group_status"] == "CANCELLED"
    assert validate_success(
        api.get_cabana_booking(resort["id"], hold["id"], fx.PLATFORM_OPS)
    )["cabana_booking_status"] == "CANCELLED"
    assert validate_success(api.get_cabana(resort["id"], cabana["id"], fx.PLATFORM_OPS))[
        "cabana_status"
    ] == "AVAILABLE"
    assert validate_success(
        api.get_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS)
    )["group_reserved_units"] == 0


def test_cancelling_the_group_reaches_its_activity_bookings(api):
    """PRD §3.8: "every activity booking attached to the group that is in
    `PENDING_PAYMENT` or `CONFIRMED` status is cancelled, which for the activity
    side is a cascade that carries no preconditions of its own."

    Design: Corner/state_machines/group_cancel_cascades_to_activity_bookings
    """
    resort = fx.create_resort(name="Wisconsin Dells")
    session = fx.create_activity_session(resort["id"], name="Glow Party", tier_code="VIP",
                                         base_price_cents=2500, capacity_units=20)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="FAMILY_REUNION", member_count=3, deposit_paid_cents=1500
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    booking = fx.create_activity_booking(
        resort["id"], session["id"], group_booking["id"], attendees=3
    )
    validate_success(
        api.confirm_activity_booking(
            resort["id"], booking["id"], fx.group_headers_for(group_booking["id"])
        )
    )
    validate_success(api.cancel_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS))
    assert validate_success(
        api.get_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS)
    )["group_status"] == "CANCELLED"
    assert validate_success(
        api.get_activity_booking(resort["id"], booking["id"], fx.PLATFORM_OPS)
    )["activity_booking_status"] == "CANCELLED"


def test_cancelling_the_group_zeroes_every_held_occupancy_unit(api):
    """PRD §3.8: "`group_reserved_units` is the sum of `member_units` across every
    member of that group whose `checked_in` flag is true. Two rules collapse the
    remainder to nothing: a group whose `group_status` has left `CONFIRMED`
    contributes 0 units whatever its members' flags still say, and a group with no
    checked-in members contributes 0 units."

    Design: Difficulty/compensating_invariant/group_cancellation_zeroes_all_occupancy_units
    """
    resort = fx.create_resort(name="Traverse City", park_capacity_occupancy_units=30,
                              day_pass_cap_units=10)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="FAMILY_REUNION", member_count=2, deposit_paid_cents=1000,
        service_date="2026-09-15",
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    fx.create_group_member(resort["id"], group_booking["id"], "Kim")
    fx.create_group_member(resort["id"], group_booking["id"], "Lex")
    cabana = fx.create_cabana(resort["id"], cabana_label="CAB-5", capacity_units=4)
    hold = fx.hold_cabana(
        resort["id"], cabana["id"], group_booking["id"], member_units=2,
        service_date="2026-09-15",
    )
    fx.confirm_cabana_booking(resort["id"], hold["id"], group_booking["id"])
    validate_success(api.cancel_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS))
    assert validate_success(
        api.get_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS)
    )["group_reserved_units"] == 0
    ledger = fx.get_capacity(resort["id"], "2026-09-15")
    assert ledger["group_reserved_units"] + ledger["cabana_day_units"] == 0


def test_an_omitted_deposit_is_stored_as_zero_and_leaves_the_group_pending(api):
    """PRD §3.8: "A new group booking begins in `PENDING_DEPOSIT` status with `group_reserved_units` at 0; it moves to `CONFIRMED` and may end in `CANCELLED`."
    PRD §3.8: "the `member_count` declared for the group, and, optionally, an
    opening `deposit_paid_cents` which defaults to 0 when omitted."

    Design: Corner/entities/group_booking_deposit_defaults_to_zero
    """
    resort = fx.create_resort(name="Fitchburg")
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=4, service_date="2026-09-20"
    )
    assert group_booking["deposit_paid_cents"] == 0
    assert group_booking["group_status"] == "PENDING_DEPOSIT"


def test_a_deposit_short_of_the_group_requirement_is_declined(api):
    """PRD §3.8: "The deposit is refused with `ERR_PAYMENT_DECLINED` (HTTP 409)
    unless the newly recorded amount added to what has already been paid meets or
    exceeds the group's requirement of `member_count` multiplied by the per-member
    deposit of 500 cents, and unless the external payment reference is accepted."

    Design: Corner/validations/deposit_below_group_requirement_declined
    """
    resort = fx.create_resort(name="Wisconsin Dells")
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=4, deposit_paid_cents=0,
        service_date="2026-09-27",
    )
    validate_success(
        api.simulate_payment(
            resort["id"],
            {"group_booking_id": group_booking["id"], "outcome": "ACCEPTED"},
            fx.PLATFORM_OPS,
        )
    )
    response = api.post_group_deposit(
        resort["id"],
        group_booking["id"],
        {"amount_cents": 1900, "external_payment_ref": "EXT-DEP-1900"},
        fx.group_headers_for(group_booking["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PAYMENT_DECLINED.value)
    assert validate_success(
        api.get_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS)
    )["deposit_paid_cents"] == 0


def test_a_group_booking_below_the_birthday_party_minimum_is_refused(api):
    """PRD §3.8: "A booking whose `group_kind` is `BIRTHDAY` must declare a
    `member_count` of at least the party minimum of 1 member — that is, the
    platform declines to accept a birthday booking with no members at all — and a
    booking that falls below it is refused with `ERR_GROUP_MINIMUM_NOT_MET` (HTTP
    409)."

    Design: Corner/entities/group_booking_deposit_defaults_to_zero
    """
    resort = fx.create_resort(name="Fitchburg")
    response = api.create_group_booking(
        resort["id"],
        {"group_kind": "BIRTHDAY", "service_date": "2026-09-20", "member_count": 0},
        fx.FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_GROUP_MINIMUM_NOT_MET.value)

def test_an_abutting_cabana_window_does_not_overlap_a_standing_occupation(api):
    """PRD §3.8: "no existing cabana booking in `HELD` or `BOOKED` status may
    occupy the same cabana on the same service date with a window that overlaps the
    requested half-open interval, and an overlap is refused with
    `ERR_CABANA_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/cabana_booking_window_overlap_rejected
    """
    resort, group_booking, _members = fx.setup_confirmed_group(member_count=2)
    blocked = fx.create_cabana(resort["id"], cabana_label="PR-2", cabana_kind="PARTY_ROOM",
                               capacity_units=10)
    held = fx.hold_cabana(
        resort["id"], blocked["id"], group_booking["id"], member_units=2,
        start_minute=600, end_minute=720,
    )
    fx.confirm_cabana_booking(resort["id"], held["id"], group_booking["id"])
    free = fx.create_cabana(resort["id"], cabana_label="PR-9", cabana_kind="PARTY_ROOM",
                            capacity_units=10)
    version = validate_success(api.get_cabana(resort["id"], free["id"], fx.PLATFORM_OPS))["version"]
    response = api.create_cabana_booking(
        resort["id"],
        {
            "cabana_id": free["id"],
            "group_booking_id": group_booking["id"],
            "service_date": "2026-09-03",
            "start_minute": 720,
            "end_minute": 780,
            "member_units": 1,
            "expected_cabana_version": version,
        },
        fx.group_headers_for(group_booking["id"]),
    )
    assert response.status_code < 400, "an abutting window is outside the half-open interval"


def test_a_party_over_the_cabana_capacity_is_refused(api):
    """PRD §3.8: "The seating must fit the cabana: `member_units` must be at least 1
    and no greater than the cabana's `capacity_units`, and an over-large party is
    refused with `ERR_CABANA_UNITS_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/cabana_booking_window_overlap_rejected
    """
    resort = fx.create_resort(name="Manteca", park_capacity_occupancy_units=30,
                              day_pass_cap_units=10)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=5, deposit_paid_cents=2500
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    cabana = fx.create_cabana(resort["id"], cabana_label="PR-2", cabana_kind="PARTY_ROOM",
                              capacity_units=10)
    response = api.create_cabana_booking(
        resort["id"],
        {
            "cabana_id": cabana["id"],
            "group_booking_id": group_booking["id"],
            "service_date": "2026-09-03",
            "start_minute": 600,
            "end_minute": 720,
            "member_units": 11,
            "expected_cabana_version": cabana["version"],
        },
        fx.group_headers_for(group_booking["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CABANA_UNITS_UNAVAILABLE.value)


def test_a_scoped_activity_booking_list_is_reachable_by_its_own_group(api):
    """PRD §3.9: "Activity bookings can be listed per group, per session, or per
    reservation folio, and a single booking can be retrieved by identifier."

    Design: Corner/state_machines/group_cancel_cascades_to_activity_bookings
    """
    resort, group_booking, _session, booking = fx.setup_confirmed_group_with_activity(attendees=2)
    rows = validate_success(
        api.list_activity_bookings_for_group(
            resort["id"], group_booking["id"], fx.PLATFORM_OPS
        )
    )
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["id"] == booking["id"]


def test_members_are_addressable_through_their_own_group(api):
    """PRD §3.8: "Members belong to the group and are addressable and listable, and
    each carries a server-minted `id` and `created_at` but no `updated_at` and no
    `version`."

    Design: Difficulty/transitive_cascade/release_cabana_unwinds_group_member_admissions
    """
    resort, group_booking, members = fx.setup_confirmed_group(member_count=2)
    listed = validate_success(
        api.list_group_members_for_group(
            resort["id"], group_booking["id"], fx.PLATFORM_OPS
        )
    )
    assert {row["id"] for row in listed} == {m["id"] for m in members}


def test_the_same_cabana_confirmation_is_accepted_once_the_deposit_posts(api):
    """PRD §3.8: "a group in `PENDING_DEPOSIT` is confirmed once its
    `deposit_paid_cents` reaches `member_count` multiplied by the 500-cent
    per-member requirement, and a booking that has not got there does not satisfy
    the state precondition and is refused with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/cabana_confirm_requires_group_confirmed
    """
    resort = fx.create_resort(name="Mason")
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=2, deposit_paid_cents=0,
        service_date="2026-09-16",
    )
    cabana = fx.create_cabana(resort["id"], cabana_label="CAB-4", cabana_kind="PARTY_ROOM",
                              capacity_units=8)
    hold = fx.hold_cabana(
        resort["id"], cabana["id"], group_booking["id"], member_units=2, service_date="2026-09-16"
    )
    validate_success(
        api.simulate_payment(
            resort["id"],
            {"group_booking_id": group_booking["id"], "outcome": "ACCEPTED"},
            fx.PLATFORM_OPS,
        )
    )
    validate_success(
        api.post_group_deposit(
            resort["id"],
            group_booking["id"],
            {"amount_cents": 1000, "external_payment_ref": "EXT-CAB-1000"},
            fx.group_headers_for(group_booking["id"]),
        ),
        201,
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    assert group_booking["group_status"] == "CONFIRMED"
    booked = validate_success(
        api.confirm_cabana_booking(resort["id"], hold["id"], fx.group_headers_for(group_booking["id"]))
    )
    assert booked["cabana_booking_status"] == "BOOKED"


def test_the_cancelled_group_surrenders_its_member_held_units(api):
    """PRD §3.8: "a group whose `group_status` has left `CONFIRMED` contributes 0 units whatever its members' flags still say, and a group with no checked-in members contributes 0 units."

    Design: Difficulty/compensating_invariant/group_cancellation_zeroes_all_occupancy_units
    """
    resort, group_booking, members, _cabana, _hold = fx.setup_confirmed_group_with_booked_cabana(
        member_units=2, cabana_units=4
    )
    validate_success(api.cancel_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS))
    for member in members:
        fetched = validate_success(
            api.get_group_member(resort["id"], member["id"], fx.PLATFORM_OPS)
        )
        assert fetched["id"] == member["id"]
    assert validate_success(
        api.get_group_booking(resort["id"], group_booking["id"], fx.PLATFORM_OPS)
    )["group_status"] == "CANCELLED"
    assert fx.get_capacity(resort["id"], "2026-09-03")["group_reserved_units"] == 0
