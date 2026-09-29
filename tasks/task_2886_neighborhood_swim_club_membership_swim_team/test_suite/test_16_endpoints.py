"""Endpoint shapes: one projection per resource, computed reads, and actions.

The reads here are compared against each other rather than against a single
expectation, because a leaner list row or a detail-only computed field is the
defect these tests exist to catch.
"""

from test_helpers import (
    MISSING_UUID,
    AccessStatus,
    ApiErrorId,
    CertType,
    CertificationStatus,
    DuesStatus,
    EmploymentStatus,
    GuardShiftStatus,
    JobCode,
    MembershipPaymentAllocation,
    RegistrationStatus,
    ReservationStatus,
    SeasonStatus,
    ShiftRole,
    Squad,
    WaitlistStatus,
    Zone,
    assertions as a,
    canonical_instant,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import transition_payload, write_off_payload
from test_helpers.test_users import (
    BOARD_PRESIDENT,
    HEALTH_INSPECTOR,
    MEMBERSHIP_CHAIR,
    POOL_MANAGER,
    SWIM_TEAM_COACH,
    TREASURER,
    make_member_headers,
)

DECK_CLOCK = "2027-07-01T09:00:00Z"


def _three_guards_one_of_them_certified(api):
    """A season-independent registry of three guards, one with a live card."""
    fx.set_clock(api, DECK_CLOCK)
    first = fx.create_lifeguard(api, full_name="Amara Vale",
                                hire_date="2026-05-01")
    second = fx.create_lifeguard(api, full_name="Bo Ferrante",
                                 hire_date="2026-05-02")
    third = fx.create_lifeguard(api, full_name="Cleo Nakamura",
                                hire_date="2026-05-03")
    return {"first": first, "second": second, "third": third}


def _guards_page(api, params):
    return validate_paginated(api.list_lifeguards(POOL_MANAGER, params))


class TestLifeguardCreateReadAndListShareOneProjection:
    """Three views of one guard, including the two derived flags."""

    def test_a_new_guard_carries_exactly_the_declared_defaults(self, api):
        """Hiring is the simplest write and it stamps four defaults.

        PRD §3.8: "The `PoolManager` records a `full_name` and a `hire_date`, and
        the new guard starts with `employment_status` `ACTIVE`, `scheduled_hours`
        at 0, and both derived certification flags — `has_valid_lifeguard_cert`
        and `has_valid_cpr_cert` — false."

        PRD §2.4: "`version`, an integer that begins at 1 when the row is created
        and increases by exactly 1 on every mutation of that row"

        Design: Corner/endpoints/standard_crud_lifeguard_create_read_and_list_share_one_projection
        """
        ctx = _three_guards_one_of_them_certified(api)

        guard = ctx["first"]
        a.assert_lifeguard(guard, EmploymentStatus.ACTIVE)
        assert guard["full_name"] == "Amara Vale"
        assert guard["hire_date"] == "2026-05-01"
        assert guard["scheduled_hours"] == 0
        assert guard["has_valid_lifeguard_cert"] is False
        assert guard["has_valid_cpr_cert"] is False
        assert guard["version"] == 1

    def test_the_detail_read_repeats_the_create_response(self, api):
        """The same row read back by id agrees field for field.

        PRD §2.10: "A successful create or modify returns the created or updated
        resource in the `data` field"

        PRD §2.4: "`version`, an integer that begins at 1 when the row is created
        and increases by exactly 1 on every mutation of that row"

        Design: Corner/endpoints/standard_crud_lifeguard_create_read_and_list_share_one_projection
        """
        ctx = _three_guards_one_of_them_certified(api)

        detail = fx.read_lifeguard(api, ctx["first"]["id"])
        assert set(detail.keys()) == set(ctx["first"].keys())
        for field in ("full_name", "hire_date", "employment_status",
                      "scheduled_hours", "has_valid_lifeguard_cert",
                      "has_valid_cpr_cert", "version"):
            assert detail[field] == ctx["first"][field]

    def test_a_certification_write_moves_the_flag_on_every_projection(self, api):
        """The list row is not a leaner projection than the detail read.

        PRD §3.8: "`has_valid_lifeguard_cert` is true when at least one of the
        guard's certifications has `cert_type` `LIFEGUARD` and `status` `VALID`"

        Design: Corner/endpoints/standard_crud_lifeguard_create_read_and_list_share_one_projection
        """
        ctx = _three_guards_one_of_them_certified(api)
        fx.certify(api, ctx["first"]["id"], CertType.LIFEGUARD,
                   issued_on="2026-06-01", expires_on="2028-05-31")

        detail = fx.read_lifeguard(api, ctx["first"]["id"])
        assert detail["has_valid_lifeguard_cert"] is True
        assert detail["has_valid_cpr_cert"] is False
        assert detail["version"] == ctx["first"]["version"] + 1

        rows, _ = _guards_page(api, {"limit": 100})
        listed = [row for row in rows if row["id"] == ctx["first"]["id"]]
        assert len(listed) == 1
        assert set(listed[0].keys()) == set(detail.keys())
        assert listed[0]["has_valid_lifeguard_cert"] is True
        assert listed[0]["has_valid_cpr_cert"] is False

    def test_the_pages_partition_the_registry(self, api):
        """total_count counts the matched set, not the page.

        PRD §2.3: "`total_count` (the number of rows matching the request's
        filters before the page window is applied) and `has_more` (true when rows
        remain beyond the current page)"

        Design: Corner/endpoints/standard_crud_lifeguard_create_read_and_list_share_one_projection
        """
        ctx = _three_guards_one_of_them_certified(api)

        first_rows, first_meta = _guards_page(api, {"limit": 2, "offset": 0})
        second_rows, second_meta = _guards_page(api, {"limit": 2, "offset": 2})

        assert len(first_rows) == 2
        assert len(second_rows) == 1
        assert first_meta["total_count"] == 3
        assert second_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert second_meta["has_more"] is False
        assert {row["id"] for row in first_rows + second_rows} == {
            ctx["first"]["id"], ctx["second"]["id"], ctx["third"]["id"]
        }

    def test_the_two_list_filters_are_anded(self, api):
        """Active but uncertified guards drop out of the deployable list.

        PRD §2.3: "Filters supplied to a list endpoint narrow the matched set
        before pagination is applied, and filters combine conjunctively"

        PRD §3.8: "Guards are listed and filtered by `employment_status` and by
        `has_valid_lifeguard_cert`, which is how the manager finds who is legally
        deployable."

        Design: Corner/endpoints/standard_crud_lifeguard_create_read_and_list_share_one_projection
        """
        ctx = _three_guards_one_of_them_certified(api)
        fx.certify(api, ctx["first"]["id"], CertType.LIFEGUARD,
                   issued_on="2026-06-01", expires_on="2028-05-31")

        rows, meta = _guards_page(api, {
            "employment_status": EmploymentStatus.ACTIVE,
            "has_valid_lifeguard_cert": True,
        })
        assert [row["id"] for row in rows] == [ctx["first"]["id"]]
        assert meta["total_count"] == 1

    def test_a_well_formed_id_naming_no_guard_is_a_typed_404(self, api):
        """The 404 names the entity family that was looked up.

        PRD §2.9: "**Existence**, for every resource addressed in the path or
        referenced by a foreign key in the payload, each with its own code"

        Design: Corner/endpoints/standard_crud_lifeguard_create_read_and_list_share_one_projection
        """
        _three_guards_one_of_them_certified(api)

        validate_error(api.get_lifeguard(MISSING_UUID, POOL_MANAGER),
                       ApiErrorId.LIFEGUARD_NOT_FOUND, 404)


WINDOW_PARTY_START = "2027-07-15T14:00:00Z"
WINDOW_PARTY_END = "2027-07-15T20:00:00Z"
WINDOW_SHIFT_START = "2027-07-15T13:00:00Z"
WINDOW_SHIFT_END = "2027-07-15T21:00:00Z"
BEFORE_THE_PARTY = "2027-07-15T13:59:00Z"
LAST_COVERED_MINUTE = "2027-07-15T19:59:00Z"
HANDOVER_INSTANT = "2027-07-15T21:00:00Z"


def _one_party_and_three_shifts_of_which_one_counts(api):
    """A 26-bather party with a single counting, confirmed guard on the deck.

    The SUPERVISOR shift is confirmed but never counts, and the SECONDARY shift
    counts but is never confirmed, so coverage at the party's instants is 1.
    """
    fx.set_clock(api, DECK_CLOCK)
    category = fx.create_couple_category(api, party_privileges=True)
    season = fx.setup_open_season(api, baseline_bather_load=0,
                                 bather_load_capacity=120)
    household = fx.create_household(
        api, primary_contact_name="Window Household",
        address_line="291 Cedar Court", member_count=2, prior_member=False,
    )
    membership = fx.setup_membership(api, household["id"], category["id"],
                                    season["id"], join_date="2027-06-01")
    fx.invoice_membership(api, membership["id"])
    reservation = fx.request_party(
        api, membership["id"], zone=Zone.PAVILION,
        start_iso=WINDOW_PARTY_START, end_iso=WINDOW_PARTY_END,
        guest_count=12, host_party_size=14,
    )

    primary = fx.setup_certified_guard(api, full_name="Primary Guard",
                                      hire_date="2026-05-01")
    supervisor = fx.setup_certified_guard(api, full_name="Supervisor Guard",
                                         hire_date="2026-05-02")
    unconfirmed = fx.setup_certified_guard(api, full_name="Unconfirmed Guard",
                                          hire_date="2026-05-03")

    primary_shift = fx.schedule_shift(
        api, primary["lifeguard"]["id"], season["id"], WINDOW_SHIFT_START,
        WINDOW_SHIFT_END, ShiftRole.PRIMARY,
    )
    supervisor_shift = fx.schedule_shift(
        api, supervisor["lifeguard"]["id"], season["id"], WINDOW_SHIFT_START,
        WINDOW_SHIFT_END, ShiftRole.SUPERVISOR,
    )
    secondary_shift = fx.schedule_shift(
        api, unconfirmed["lifeguard"]["id"], season["id"], WINDOW_SHIFT_START,
        WINDOW_SHIFT_END, ShiftRole.SECONDARY,
    )
    confirmed_primary = fx.transition_shift(api, primary_shift["id"],
                                           GuardShiftStatus.CONFIRMED)
    confirmed_supervisor = fx.transition_shift(api, supervisor_shift["id"],
                                              GuardShiftStatus.CONFIRMED)
    return {
        "season": season,
        "reservation": reservation,
        "primary_shift": confirmed_primary,
        "supervisor_shift": confirmed_supervisor,
        "secondary_shift": secondary_shift,
    }


def _window_at(api, season_id, at_iso, headers=POOL_MANAGER):
    return validate_success(
        api.get_staffing_window(season_id, headers, {"at_iso": at_iso}), 200
    )


class TestTheStaffingWindowIsAPureProjectionAtOneInstant:
    """Five reads of one unchanged season that disagree with each other."""

    def test_the_reservation_pins_the_load_and_the_requirement(self, api):
        """Twelve guests and fourteen hosts demand two guards.

        PRD §3.7: "First, `projected_bather_load` is the reservation's
        `guest_count` plus its `host_party_size`."

        PRD §3.7: "Second, `required_guard_count` is derived from that load:
        divide the load by the twenty-five bathers each guard may cover and round
        up to the next whole number, take the larger of that figure and the
        standing minimum of one guard whenever the facility is open"

        Design: Corner/endpoints/computed_read_the_staffing_window_is_a_pure_projection_at_one_instant
        """
        ctx = _one_party_and_three_shifts_of_which_one_counts(api)

        assert ctx["reservation"]["projected_bather_load"] == 26
        assert ctx["reservation"]["required_guard_count"] == 2
        assert ctx["reservation"]["status"] == ReservationStatus.REQUESTED

    def test_the_supervisor_never_counts_and_the_unconfirmed_guard_is_not_there(
            self, api):
        """Two of the three shifts are excluded, for two different reasons.

        PRD §3.8: "`counts_toward_ratio`, true when the `shift_role` is
        `PRIMARY` or `SECONDARY` and false for `SUPERVISOR`"

        PRD §3.8: "Shifts merely `SCHEDULED` do not count toward coverage,
        because an unconfirmed guard may not show, and `SUPERVISOR` shifts never
        count at all."

        Design: Corner/endpoints/computed_read_the_staffing_window_is_a_pure_projection_at_one_instant
        """
        ctx = _one_party_and_three_shifts_of_which_one_counts(api)

        assert ctx["primary_shift"]["counts_toward_ratio"] is True
        assert ctx["primary_shift"]["status"] == GuardShiftStatus.CONFIRMED
        assert ctx["supervisor_shift"]["counts_toward_ratio"] is False
        assert ctx["supervisor_shift"]["status"] == GuardShiftStatus.CONFIRMED
        assert ctx["secondary_shift"]["counts_toward_ratio"] is True
        assert ctx["secondary_shift"]["status"] == GuardShiftStatus.SCHEDULED

    def test_the_party_load_lands_only_inside_its_half_open_window(self, api):
        """One minute before the party the deck is legally quiet.

        PRD §3.8: "The load is the sum of `guest_count` plus `host_party_size`
        over the season's reservations in `REQUESTED` or `CONFIRMED` whose window
        contains the instant, where a reservation's window is half-open: it
        includes `start_iso` and excludes `end_iso`"

        PRD §3.8: "The requirement is that load divided by the twenty-five
        bathers one guard may cover, rounded up to the next whole number, taken
        against the standing minimum of one guard, whichever is larger"

        Design: Corner/endpoints/computed_read_the_staffing_window_is_a_pure_projection_at_one_instant
        """
        ctx = _one_party_and_three_shifts_of_which_one_counts(api)
        season_id = ctx["season"]["id"]

        before = _window_at(api, season_id, BEFORE_THE_PARTY)
        a.assert_staffing_window(before, 0, 1, 1, True)

        at_start = _window_at(api, season_id, WINDOW_PARTY_START)
        a.assert_staffing_window(at_start, 26, 2, 1, False)

        last_minute = _window_at(api, season_id, LAST_COVERED_MINUTE)
        a.assert_staffing_window(last_minute, 26, 2, 1, False)

        at_end = _window_at(api, season_id, WINDOW_PARTY_END, BOARD_PRESIDENT)
        a.assert_staffing_window(at_end, 0, 1, 1, True)

    def test_the_shift_interval_is_closed_at_the_handover(self, api):
        """The guard standing at the exact end instant is still counted.

        PRD §3.8: "Coverage counts the distinct `lifeguard_id` values over the
        season's shifts that are in `CONFIRMED`, that have `counts_toward_ratio`
        true, and whose interval contains the instant, where a shift's interval
        is **closed**: it includes both `start_iso` and `end_iso`, so a guard
        standing at the exact instant of handover is counted."

        Design: Corner/endpoints/computed_read_the_staffing_window_is_a_pure_projection_at_one_instant
        """
        ctx = _one_party_and_three_shifts_of_which_one_counts(api)

        handover = _window_at(api, ctx["season"]["id"], HANDOVER_INSTANT,
                              HEALTH_INSPECTOR)
        a.assert_staffing_window(handover, 0, 1, 1, True)

    def test_every_answer_echoes_the_question_it_was_asked(self, api):
        """The read is not a stored entity and carries no pagination meta.

        PRD §3.8: "a computed read that takes an `at_iso` instant and returns an
        object rather than a stored entity: the `season_id` and `at_iso` it was
        asked about, the `bather_load` it found, the `required_guard_count` that
        load demands, the `scheduled_guard_count` actually covering the instant,
        and the boolean `compliant` verdict"

        Design: Corner/endpoints/computed_read_the_staffing_window_is_a_pure_projection_at_one_instant
        """
        ctx = _one_party_and_three_shifts_of_which_one_counts(api)
        season_id = ctx["season"]["id"]

        for at_iso in (BEFORE_THE_PARTY, WINDOW_PARTY_START, WINDOW_PARTY_END,
                       HANDOVER_INSTANT):
            window = _window_at(api, season_id, at_iso)
            assert window["season_id"] == season_id
            assert canonical_instant(window["at_iso"]) == \
                canonical_instant(at_iso)
            assert {"season_id", "at_iso", "bather_load",
                    "required_guard_count", "scheduled_guard_count",
                    "compliant"} <= set(window.keys())
            for stored_entity_field in ("id", "created_at", "updated_at",
                                        "version"):
                assert stored_entity_field not in window

    def test_asking_twice_changes_nothing(self, api):
        """A computed read is not a write dressed up as one.

        PRD §2.10: "the staffing-window read returns a computed object rather
        than a stored entity"

        PRD §3.7: "A new reservation is born `REQUESTED` with `refunded_cents`
        at 0"

        Design: Corner/endpoints/computed_read_the_staffing_window_is_a_pure_projection_at_one_instant
        """
        ctx = _one_party_and_three_shifts_of_which_one_counts(api)
        season_id = ctx["season"]["id"]

        first = _window_at(api, season_id, WINDOW_PARTY_START)
        for at_iso in (BEFORE_THE_PARTY, HANDOVER_INSTANT):
            _window_at(api, season_id, at_iso)
        second = _window_at(api, season_id, WINDOW_PARTY_START)
        assert second == first

        reservation = fx.read_reservation(api, ctx["reservation"]["id"])
        assert reservation["status"] == ReservationStatus.REQUESTED
        assert reservation["version"] == ctx["reservation"]["version"]


LINK_SHIFT_START = "2027-07-15T13:00:00Z"
LINK_SHIFT_END = "2027-07-15T19:00:00Z"


def _two_parents_of_every_kind(api):
    """Two guards, two households, two swimmers and two meets.

    Every hop below therefore has a wrong answer available: an implementation
    that ignores the filter returns both parents' children.
    """
    fx.set_clock(api, DECK_CLOCK)
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api)

    first_guard = fx.setup_certified_guard(api, full_name="Link Guard One",
                                         hire_date="2026-05-01")
    second_guard = fx.setup_certified_guard(api, full_name="Link Guard Two",
                                          hire_date="2026-05-02")
    first_shift = fx.schedule_shift(api, first_guard["lifeguard"]["id"],
                                   season["id"], LINK_SHIFT_START,
                                   LINK_SHIFT_END, ShiftRole.PRIMARY)
    second_shift = fx.schedule_shift(api, second_guard["lifeguard"]["id"],
                                    season["id"], LINK_SHIFT_START,
                                    LINK_SHIFT_END, ShiftRole.SECONDARY)

    households = []
    memberships = []
    registrations = []
    for name, address, swimmer, birthdate in (
        ("Link Household One", "301 Cedar Court", "Link Swimmer One",
         "2016-02-02"),
        ("Link Household Two", "302 Cedar Court", "Link Swimmer Two",
         "2016-03-03"),
    ):
        household = fx.create_household(
            api, primary_contact_name=name, address_line=address,
            member_count=2, prior_member=False,
        )
        membership = fx.setup_membership(api, household["id"], category["id"],
                                       season["id"], join_date="2027-06-01")
        fx.invoice_membership(api, membership["id"])
        registration = fx.register_swimmer(
            api, membership["id"], season["id"], swimmer_name=swimmer,
            swimmer_birthdate=birthdate, squad=Squad.MINI,
        )
        households.append(household)
        memberships.append(membership)
        registrations.append(registration)

    first_meet = fx.create_meet(api, season["id"], name="Link Meet One",
                               start_iso="2027-07-17T13:00:00Z",
                               end_iso="2027-07-17T18:00:00Z",
                               expected_swimmers=30,
                               volunteer_slots_required=6)
    second_meet = fx.create_meet(api, season["id"], name="Link Meet Two",
                                start_iso="2027-07-24T13:00:00Z",
                                end_iso="2027-07-24T18:00:00Z",
                                expected_swimmers=30,
                                volunteer_slots_required=6)
    shared = fx.assign_volunteer(api, first_meet["id"], registrations[0]["id"],
                                JobCode.TIMER)
    meet_only = fx.assign_volunteer(api, first_meet["id"],
                                   registrations[1]["id"], JobCode.MARSHAL)
    swimmer_only = fx.assign_volunteer(api, second_meet["id"],
                                      registrations[0]["id"],
                                      JobCode.CONCESSIONS)
    return {
        "season": season,
        "first_guard": first_guard,
        "second_guard": second_guard,
        "first_shift": first_shift,
        "second_shift": second_shift,
        "households": households,
        "memberships": memberships,
        "registrations": registrations,
        "first_meet": first_meet,
        "second_meet": second_meet,
        "shared_assignment": shared,
        "meet_only_assignment": meet_only,
        "swimmer_only_assignment": swimmer_only,
    }


def _ids(rows):
    return {row["id"] for row in rows}


class TestEveryChildCollectionIsReachableFromItsParent:
    """The API has no nested routes, so each hop is a filtered list."""

    def test_the_certification_hop_composes_with_the_type_filter(self, api):
        """Guard one's wall is two rows and never four.

        PRD §3.8: "Certifications are listed and filtered by `lifeguard_id`,
        `cert_type` and `status`, which is how a guard's certification wall is
        discovered"

        PRD §2.3: "Filters supplied to a list endpoint narrow the matched set
        before pagination is applied, and filters combine conjunctively"

        Design: Corner/endpoints/cross_reference_link_every_child_collection_is_reachable_from_its_parent
        """
        ctx = _two_parents_of_every_kind(api)
        guard_id = ctx["first_guard"]["lifeguard"]["id"]

        rows, meta = validate_paginated(
            api.list_certifications(POOL_MANAGER, {"lifeguard_id": guard_id})
        )
        assert meta["total_count"] == 2
        assert _ids(rows) == {ctx["first_guard"]["lifeguard_cert"]["id"],
                              ctx["first_guard"]["cpr_cert"]["id"]}
        assert all(row["lifeguard_id"] == guard_id for row in rows)

        narrowed, narrowed_meta = validate_paginated(
            api.list_certifications(POOL_MANAGER, {
                "lifeguard_id": guard_id, "cert_type": CertType.CPR_AED,
            })
        )
        assert narrowed_meta["total_count"] == 1
        assert _ids(narrowed) == {ctx["first_guard"]["cpr_cert"]["id"]}

    def test_the_shift_hop_returns_only_the_addressed_guards_watch(self, api):
        """Two shifts exist over the same hours; one guard owns one of them.

        PRD §3.8: "Shifts are listed and filtered by `lifeguard_id`,
        `season_id`, `status` and `shift_role`."

        Design: Corner/endpoints/cross_reference_link_every_child_collection_is_reachable_from_its_parent
        """
        ctx = _two_parents_of_every_kind(api)
        guard_id = ctx["second_guard"]["lifeguard"]["id"]

        rows, meta = validate_paginated(
            api.list_guard_shifts(POOL_MANAGER, {"lifeguard_id": guard_id})
        )
        assert meta["total_count"] == 1
        assert _ids(rows) == {ctx["second_shift"]["id"]}
        assert rows[0]["lifeguard_id"] == guard_id
        assert ctx["first_shift"]["id"] not in _ids(rows)

    def test_the_household_and_membership_hops_each_return_one_row(self, api):
        """Household to membership, then membership to registration.

        PRD §3.3: "memberships by `household_id`, `membership_category_id`,
        `season_id`, `dues_status` and `access_status`"

        PRD §3.6: "Registrations are listed and filtered by `membership_id`,
        `season_id`, `squad` and `status`."

        Design: Corner/endpoints/cross_reference_link_every_child_collection_is_reachable_from_its_parent
        """
        ctx = _two_parents_of_every_kind(api)
        household_id = ctx["households"][0]["id"]
        membership_id = ctx["memberships"][1]["id"]

        membership_rows, membership_meta = validate_paginated(
            api.list_memberships(TREASURER, {"household_id": household_id})
        )
        assert membership_meta["total_count"] == 1
        assert _ids(membership_rows) == {ctx["memberships"][0]["id"]}
        assert membership_rows[0]["household_id"] == household_id

        registration_rows, registration_meta = validate_paginated(
            api.list_registrations(SWIM_TEAM_COACH,
                                  {"membership_id": membership_id})
        )
        assert registration_meta["total_count"] == 1
        assert _ids(registration_rows) == {ctx["registrations"][1]["id"]}
        assert registration_rows[0]["membership_id"] == membership_id

    def test_the_junction_is_walked_from_both_of_its_sides(self, api):
        """One swimmer works two meets and one meet has two workers.

        PRD §3.6: "Assignments are listed and filtered by `meet_id`,
        `swim_team_registration_id`, `job_code` and `status`."

        Design: Corner/endpoints/cross_reference_link_every_child_collection_is_reachable_from_its_parent
        """
        ctx = _two_parents_of_every_kind(api)
        meet_id = ctx["first_meet"]["id"]
        registration_id = ctx["registrations"][0]["id"]

        by_meet, by_meet_meta = validate_paginated(
            api.list_volunteer_assignments(SWIM_TEAM_COACH,
                                           {"meet_id": meet_id})
        )
        assert by_meet_meta["total_count"] == 2
        assert _ids(by_meet) == {ctx["shared_assignment"]["id"],
                                 ctx["meet_only_assignment"]["id"]}
        assert all(row["meet_id"] == meet_id for row in by_meet)

        by_swimmer, by_swimmer_meta = validate_paginated(
            api.list_volunteer_assignments(
                SWIM_TEAM_COACH,
                {"swim_team_registration_id": registration_id},
            )
        )
        assert by_swimmer_meta["total_count"] == 2
        assert _ids(by_swimmer) == {ctx["shared_assignment"]["id"],
                                    ctx["swimmer_only_assignment"]["id"]}
        assert all(row["swim_team_registration_id"] == registration_id
                   for row in by_swimmer)

        assert _ids(by_meet) & _ids(by_swimmer) == {
            ctx["shared_assignment"]["id"]
        }


BILLING_SETUP_CLOCK = "2027-06-01T09:00:00Z"
BILLING_RUN_CLOCK = "2027-07-01T09:00:00Z"
FIRST_OFFER_EXPIRY = "2027-06-15T09:00:00Z"
SECOND_OFFER_EXPIRY = "2027-07-15T09:00:00Z"
BILLING_INVOICE_TOTAL = 31050


def _three_families_waiting_to_be_aged(api):
    """A stale offer, an overdue invoice and a lapsing certification.

    The three share nothing but the season, and the clock is then moved past all
    three deadlines without ageing anything: only the checkpoint ages rows.
    """
    couple = fx.create_couple_category(api)
    family = fx.create_family_category(api, waitlist_required=True)
    season = fx.setup_open_season(api, clock_iso=BILLING_SETUP_CLOCK)

    payer = fx.create_household(
        api, primary_contact_name="Billing Household HM",
        address_line="311 Cedar Court", member_count=2, prior_member=False,
    )
    membership = fx.setup_membership(api, payer["id"], couple["id"],
                                    season["id"], join_date="2027-05-22")
    invoiced = fx.invoice_membership(api, membership["id"])

    first_waiting = fx.create_household(
        api, primary_contact_name="Waitlist Household HA",
        address_line="312 Cedar Court", member_count=5, prior_member=False,
    )
    second_waiting = fx.create_household(
        api, primary_contact_name="Waitlist Household HB",
        address_line="313 Cedar Court", member_count=5, prior_member=False,
    )
    first_entry = fx.join_waitlist(api, first_waiting["id"], family["id"])
    second_entry = fx.join_waitlist(api, second_waiting["id"], family["id"])
    offered = fx.extend_next_offer(api, family["id"])

    guard = fx.create_lifeguard(api, full_name="Lapsing Guard",
                                hire_date="2026-05-01")
    lapsing_cert = fx.certify(api, guard["id"], CertType.LIFEGUARD,
                              issued_on="2026-06-01", expires_on="2027-06-20")
    cpr_cert = fx.certify(api, guard["id"], CertType.CPR_AED,
                          issued_on="2026-06-01", expires_on="2028-05-31")

    fx.set_clock(api, BILLING_RUN_CLOCK)
    return {
        "family": family,
        "season": season,
        "membership": invoiced,
        "first_entry": first_entry,
        "second_entry": second_entry,
        "offered": offered,
        "guard": guard,
        "lapsing_cert": lapsing_cert,
        "cpr_cert": cpr_cert,
    }


class TestOneBillingRunAgesThreeUnrelatedEntityFamilies:
    """Four ordered steps behind one POST with an empty body."""

    def test_nothing_has_aged_before_the_checkpoint_is_run(self, api):
        """The clock has passed all three deadlines and moved nothing.

        PRD §3.1: "Time in this system does not age anything by itself; a
        `Treasurer` runs an explicit checkpoint against the season to age it"

        PRD §3.2: "The winning entry moves `WAITING → OFFERED`, `offered_at` is
        stamped with the logical clock, and `offer_expires_at` is set to fourteen
        days after that instant."

        Design: Corner/endpoints/bulk_action_one_billing_run_ages_three_unrelated_entity_families
        """
        ctx = _three_families_waiting_to_be_aged(api)

        assert ctx["offered"]["id"] == ctx["first_entry"]["id"]
        assert ctx["first_entry"]["status"] == WaitlistStatus.WAITING
        assert ctx["second_entry"]["status"] == WaitlistStatus.WAITING
        assert ctx["offered"]["status"] == WaitlistStatus.OFFERED
        assert canonical_instant(ctx["offered"]["offered_at"]) == \
            canonical_instant(BILLING_SETUP_CLOCK)
        assert canonical_instant(ctx["offered"]["offer_expires_at"]) == \
            canonical_instant(FIRST_OFFER_EXPIRY)

        assert ctx["membership"]["dues_status"] == DuesStatus.INVOICED
        assert ctx["membership"]["balance_due_cents"] == BILLING_INVOICE_TOTAL
        assert ctx["lapsing_cert"]["status"] == CertificationStatus.VALID
        assert ctx["cpr_cert"]["status"] == CertificationStatus.VALID
        assert fx.read_waitlist_entry(api, ctx["first_entry"]["id"])["status"] \
            == WaitlistStatus.OFFERED

    def test_the_checkpoint_returns_the_season_and_leaves_its_status_alone(
            self, api):
        """A billing run is an accounting sweep, not a lifecycle move.

        PRD §3.1: "The checkpoint advances the season's `version` and returns the
        season."

        Design: Corner/endpoints/bulk_action_one_billing_run_ages_three_unrelated_entity_families
        """
        ctx = _three_families_waiting_to_be_aged(api)

        season = fx.run_billing_run(api, ctx["season"]["id"])
        a.assert_common_fields(season, ctx["season"]["version"] + 1)
        assert season["status"] == SeasonStatus.OPEN
        assert season["id"] == ctx["season"]["id"]

    def test_one_call_both_expires_an_offer_and_extends_the_next(self, api):
        """Step three refills exactly the slot step two vacated.

        PRD §3.1: "Step two expires stale waitlist offers: every entry in
        `OFFERED` whose `offer_expires_at` is earlier than the logical clock
        moves to `EXPIRED`. Step three refills each slot vacated in step two by
        re-running the offer selector for that entry's `membership_category_id`,
        so a lapsed offer is immediately passed down the queue."

        Design: Corner/endpoints/bulk_action_one_billing_run_ages_three_unrelated_entity_families
        """
        ctx = _three_families_waiting_to_be_aged(api)
        fx.run_billing_run(api, ctx["season"]["id"])

        lapsed = fx.read_waitlist_entry(api, ctx["first_entry"]["id"])
        assert lapsed["status"] == WaitlistStatus.EXPIRED

        promoted = fx.read_waitlist_entry(api, ctx["second_entry"]["id"])
        assert promoted["status"] == WaitlistStatus.OFFERED
        assert canonical_instant(promoted["offered_at"]) == \
            canonical_instant(BILLING_RUN_CLOCK)
        assert canonical_instant(promoted["offer_expires_at"]) == \
            canonical_instant(SECOND_OFFER_EXPIRY)

    def test_ageing_the_dues_dimension_leaves_the_access_dimension_alone(
            self, api):
        """The gate stays open while the money goes delinquent.

        PRD §3.1: "Step four ages the money: every membership whose
        `dues_status` is `INVOICED`, whose `balance_due_cents` is greater than 0,
        and whose season's `dues_due_date` is strictly earlier than the effective
        date moves `dues_status` to `DELINQUENT`"

        Design: Corner/endpoints/bulk_action_one_billing_run_ages_three_unrelated_entity_families
        """
        ctx = _three_families_waiting_to_be_aged(api)
        fx.run_billing_run(api, ctx["season"]["id"])

        aged = fx.read_membership(api, ctx["membership"]["id"])
        assert aged["dues_status"] == DuesStatus.DELINQUENT
        assert aged["balance_due_cents"] == BILLING_INVOICE_TOTAL
        assert aged["access_status"] == AccessStatus.ACTIVE
        assert aged["version"] == ctx["membership"]["version"] + 1

    def test_the_expiring_certification_drags_its_guard_inactive(self, api):
        """Only the lifeguard card lapses, and it was the guard's last one.

        PRD §3.1: "Step one expires certifications: every certification in
        `VALID` whose `expires_on` is strictly earlier than the effective date
        moves to `EXPIRED`, which recomputes its guard's certification flags and
        can drive that guard inactive."

        PRD §3.8: "Expiry itself is never spontaneous — it happens only in step
        one of the billing checkpoint described in §3.1, which moves every
        `VALID` certification whose `expires_on` is strictly earlier than the
        effective date to `EXPIRED` and recomputes the affected guard's flags,
        and which can therefore drive a guard `ACTIVE → INACTIVE` by the same
        last-lifeguard-certification rule."

        Design: Corner/endpoints/bulk_action_one_billing_run_ages_three_unrelated_entity_families
        """
        ctx = _three_families_waiting_to_be_aged(api)
        fx.run_billing_run(api, ctx["season"]["id"])

        assert fx.read_certification(api, ctx["lapsing_cert"]["id"])["status"] \
            == CertificationStatus.EXPIRED
        assert fx.read_certification(api, ctx["cpr_cert"]["id"])["status"] \
            == CertificationStatus.VALID

        guard = fx.read_lifeguard(api, ctx["guard"]["id"])
        assert guard["has_valid_lifeguard_cert"] is False
        assert guard["has_valid_cpr_cert"] is True
        assert guard["employment_status"] == EmploymentStatus.INACTIVE

    def test_a_second_checkpoint_ages_nothing_a_second_time(self, api):
        """The sweep is idempotent on every family it has already aged.

        PRD §3.1: "The checkpoint advances the season's `version` and returns the
        season."

        PRD §2.4: "Rows that a cascade inspects but does not change do not
        advance."

        Design: Corner/endpoints/bulk_action_one_billing_run_ages_three_unrelated_entity_families
        """
        ctx = _three_families_waiting_to_be_aged(api)
        first_run = fx.run_billing_run(api, ctx["season"]["id"])
        aged_membership = fx.read_membership(api, ctx["membership"]["id"])
        live_offer = fx.read_waitlist_entry(api, ctx["second_entry"]["id"])

        second_run = fx.run_billing_run(api, ctx["season"]["id"])
        assert second_run["version"] == first_run["version"] + 1

        still_offered = fx.read_waitlist_entry(api, ctx["second_entry"]["id"])
        assert still_offered["status"] == WaitlistStatus.OFFERED
        assert canonical_instant(still_offered["offered_at"]) == \
            canonical_instant(live_offer["offered_at"])
        assert still_offered["version"] == live_offer["version"]

        untouched = fx.read_membership(api, ctx["membership"]["id"])
        assert untouched["dues_status"] == DuesStatus.DELINQUENT
        assert untouched["version"] == aged_membership["version"]

        rows, meta = validate_paginated(api.list_waitlist_entries(
            MEMBERSHIP_CHAIR,
            {"membership_category_id": ctx["family"]["id"],
             "status": WaitlistStatus.OFFERED},
        ))
        assert meta["total_count"] == 1
        assert _ids(rows) == {ctx["second_entry"]["id"]}


WRITE_OFF_PARTY_START = "2027-07-15T14:00:00Z"
WRITE_OFF_PARTY_END = "2027-07-15T18:00:00Z"
WRITE_OFF_SHIFT_START = "2027-07-15T13:00:00Z"
WRITE_OFF_SHIFT_END = "2027-07-15T19:00:00Z"
WRITE_OFF_PARTY_TOTAL = 16200
WRITE_OFF_HALF_REFUND = 8100
RESERVE_CONTRIBUTION = 100000


def _a_delinquent_membership_with_a_child_of_each_kind(api):
    """A DELINQUENT membership above a confirmed swimmer and a future party.

    The registration is created before the party because outstanding party
    charges would themselves make the household delinquent (PRD §3.4).
    """
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api, clock_iso=BILLING_SETUP_CLOCK)
    fx.contribute_reserve(api, season["id"], RESERVE_CONTRIBUTION,
                          note="Resurfacing assessment")

    household = fx.create_household(
        api, primary_contact_name="Write Off Household",
        address_line="321 Cedar Court", member_count=2, prior_member=False,
    )
    membership = fx.setup_membership(api, household["id"], category["id"],
                                    season["id"], join_date="2027-05-22")
    invoiced = fx.invoice_membership(api, membership["id"])

    registration = fx.register_swimmer(
        api, membership["id"], season["id"], swimmer_name="Nadia Writeoff",
        swimmer_birthdate="2016-06-06", squad=Squad.MINI,
    )
    confirmed_registration = fx.transition_registration(
        api, registration["id"], RegistrationStatus.CONFIRMED)

    coverage = fx.setup_confirmed_shift(api, season["id"],
                                        WRITE_OFF_SHIFT_START,
                                        WRITE_OFF_SHIFT_END,
                                        full_name="Cascade Guard")
    reservation = fx.request_party(api, membership["id"], zone=Zone.PAVILION,
                                   start_iso=WRITE_OFF_PARTY_START,
                                   end_iso=WRITE_OFF_PARTY_END,
                                   guest_count=12, host_party_size=8)
    confirmed_party = fx.transition_party(api, reservation["id"],
                                          ReservationStatus.CONFIRMED)

    fx.set_clock(api, BILLING_RUN_CLOCK)
    fx.run_billing_run(api, season["id"])
    return {
        "season": fx.read_season(api, season["id"]),
        "household": fx.read_household(api, household["id"]),
        "membership": fx.read_membership(api, membership["id"]),
        "invoiced": invoiced,
        "registration": confirmed_registration,
        "shift": coverage["shift"],
        "reservation": confirmed_party,
    }


class TestWriteOffSettlesOneDimensionAndCascadesTheOther:
    """One action endpoint moves both membership dimensions at once."""

    def test_the_ledger_before_the_write_off(self, api):
        """A delinquent balance, a confirmed swimmer and a future party.

        PRD §3.1: "Step four ages the money: every membership whose
        `dues_status` is `INVOICED`, whose `balance_due_cents` is greater than 0,
        and whose season's `dues_due_date` is strictly earlier than the effective
        date moves `dues_status` to `DELINQUENT`"

        PRD §3.7: "A new reservation is born `REQUESTED` with `refunded_cents`
        at 0, and its `total_charge_cents` is booked onto the household
        immediately: `party_charges_owed_cents` rises by that amount"

        Design: Corner/endpoints/action_endpoint_write_off_settles_one_dimension_and_cascades_the_other
        """
        ctx = _a_delinquent_membership_with_a_child_of_each_kind(api)

        assert ctx["invoiced"]["invoice_total_cents"] == BILLING_INVOICE_TOTAL
        assert ctx["invoiced"]["access_status"] == AccessStatus.ACTIVE
        assert ctx["registration"]["status"] == RegistrationStatus.CONFIRMED
        assert ctx["reservation"]["total_charge_cents"] == WRITE_OFF_PARTY_TOTAL
        assert ctx["reservation"]["refunded_cents"] == 0
        assert ctx["reservation"]["status"] == ReservationStatus.CONFIRMED
        assert ctx["shift"]["status"] == GuardShiftStatus.CONFIRMED

        assert ctx["membership"]["dues_status"] == DuesStatus.DELINQUENT
        assert ctx["membership"]["balance_due_cents"] == BILLING_INVOICE_TOTAL
        assert ctx["household"]["party_charges_owed_cents"] == \
            WRITE_OFF_PARTY_TOTAL
        assert ctx["household"]["account_credit_cents"] == 0

    def test_one_request_moves_both_membership_dimensions(self, api):
        """The dues dimension goes terminal and the gate closes with it.

        PRD §3.4: "Writing off is available only from `DELINQUENT`, requires a
        `reason`, sets `balance_due_cents` to 0, and moves `dues_status` to the
        terminal `WRITTEN_OFF`. In the same request the access dimension moves
        `ACTIVE → SUSPENDED` when it was `ACTIVE`"

        PRD §3.3: "`assessed_dues_cents` is stamped exactly once, while the
        membership is still `UNBILLED`, and is never re-derived. A later invoice,
        payment, write-off or season close leaves that stamped figure frozen."

        Design: Corner/endpoints/action_endpoint_write_off_settles_one_dimension_and_cascades_the_other
        """
        ctx = _a_delinquent_membership_with_a_child_of_each_kind(api)

        written_off = fx.write_off_membership(
            api, ctx["membership"]["id"],
            reason="Household moved out of district mid-season; "
                   "balance uncollectible.",
        )
        assert written_off["dues_status"] == DuesStatus.WRITTEN_OFF
        assert written_off["access_status"] == AccessStatus.SUSPENDED
        assert written_off["balance_due_cents"] == 0
        assert written_off["amount_paid_cents"] == 0
        assert written_off["invoice_total_cents"] == BILLING_INVOICE_TOTAL
        assert written_off["version"] == ctx["membership"]["version"] + 1

    def test_the_cascade_follows_the_access_dimension(self, api):
        """The swimmer and the future party are collateral, not targets.

        PRD §3.4: "which drags the full suspension cascade of §3.9 behind it:
        every swim-team registration of that membership in `PENDING`,
        `CONFIRMED` or `WAITLISTED` is revoked and every future confirmed
        reservation is cancelled as `CANCELLED_BY_SUSPENSION`"

        PRD §3.7: "A suspension-driven cancellation, which the conduct cascade of
        §3.9 produces for every `CONFIRMED` reservation whose `start_iso` is
        still in the future, always refunds half the `total_charge_cents`,
        rounded half up, because the member caused it."

        Design: Corner/endpoints/action_endpoint_write_off_settles_one_dimension_and_cascades_the_other
        """
        ctx = _a_delinquent_membership_with_a_child_of_each_kind(api)
        fx.write_off_membership(api, ctx["membership"]["id"])

        registration = fx.read_registration(api, ctx["registration"]["id"])
        assert registration["status"] == RegistrationStatus.REVOKED

        reservation = fx.read_reservation(api, ctx["reservation"]["id"])
        assert reservation["status"] == \
            ReservationStatus.CANCELLED_BY_SUSPENSION
        assert reservation["refunded_cents"] == WRITE_OFF_HALF_REFUND

    def test_the_refund_credit_stays_on_the_household(self, api):
        """The auto-apply rule is skipped on the suspension edge.

        PRD §3.7: "`party_charges_owed_cents` falls by `refunded_cents` and
        `account_credit_cents` rises by the same amount"

        PRD §3.7: "On a suspension cancellation the auto-apply rule does **not**
        run, because a suspended household may not settle its dues out of a
        refund its own conduct produced."

        Design: Corner/endpoints/action_endpoint_write_off_settles_one_dimension_and_cascades_the_other
        """
        ctx = _a_delinquent_membership_with_a_child_of_each_kind(api)
        fx.write_off_membership(api, ctx["membership"]["id"])

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["party_charges_owed_cents"] == \
            WRITE_OFF_PARTY_TOTAL - WRITE_OFF_HALF_REFUND
        assert household["account_credit_cents"] == WRITE_OFF_HALF_REFUND

        membership = fx.read_membership(api, ctx["membership"]["id"])
        assert membership["balance_due_cents"] == 0
        assert membership["amount_paid_cents"] == 0

    def test_neither_the_reserve_nor_the_club_s_own_shift_is_touched(self, api):
        """The cascade stops at the household's own rows.

        PRD §3.4: "The season's `reserve_contributions_cents` is **not** reduced
        by a write-off — an already-booked contribution is never clawed back."

        PRD §3.9: "Each membership also takes every party reservation beneath it
        that is in `REQUESTED` or `CONFIRMED` and whose `start_iso` is strictly
        later than the logical clock to `CANCELLED_BY_SUSPENSION`"

        Design: Corner/endpoints/action_endpoint_write_off_settles_one_dimension_and_cascades_the_other
        """
        ctx = _a_delinquent_membership_with_a_child_of_each_kind(api)
        fx.write_off_membership(api, ctx["membership"]["id"])

        season = fx.read_season(api, ctx["season"]["id"])
        a.assert_reserve_counters(season, RESERVE_CONTRIBUTION,
                                  RESERVE_CONTRIBUTION)

        shift = fx.read_shift(api, ctx["shift"]["id"])
        assert shift["status"] == GuardShiftStatus.CONFIRMED

    def test_a_second_write_off_is_refused_as_terminal(self, api):
        """WRITTEN_OFF is a declared terminal state of the dues dimension.

        PRD §2.9: "the resource is not already in a terminal state
        (`ERR_ALREADY_TERMINAL`, 409)"

        PRD §3.4: "moves `dues_status` to the terminal `WRITTEN_OFF`"

        Design: Corner/endpoints/action_endpoint_write_off_settles_one_dimension_and_cascades_the_other
        """
        ctx = _a_delinquent_membership_with_a_child_of_each_kind(api)
        written_off = fx.write_off_membership(api, ctx["membership"]["id"])

        validate_error(
            api.write_off_membership(
                ctx["membership"]["id"],
                write_off_payload(reason="Duplicate write-off attempt."),
                TREASURER,
            ),
            ApiErrorId.ALREADY_TERMINAL, 409,
        )
        assert fx.read_membership(api, ctx["membership"]["id"])["version"] == \
            written_off["version"]


REFUND_CLOCK = "2027-07-01T09:00:00Z"
SHORT_NOTICE_CLOCK = "2027-07-12T14:00:00Z"
EXACT_SEVEN_DAYS_CLOCK = "2027-07-15T14:00:00Z"
PARTY_A_START = "2027-07-15T14:00:00Z"
PARTY_A_END = "2027-07-15T18:00:00Z"
PARTY_B_START = "2027-07-22T14:00:00Z"
PARTY_B_END = "2027-07-22T18:00:00Z"
SHIFT_A_START = "2027-07-15T13:00:00Z"
SHIFT_A_END = "2027-07-15T19:00:00Z"
SHIFT_B_START = "2027-07-22T13:00:00Z"
SHIFT_B_END = "2027-07-22T19:00:00Z"
REFUND_PARTY_TOTAL = 16200
REFUND_HALF = 8100
PART_PAYMENT = 25000
REMAINING_BALANCE = 6050


def _two_households_each_holding_a_confirmed_party(api):
    """Two identical parties a week apart, over two very different balances.

    Household A owes its whole invoice; household B has already paid all but
    6050 cents of it, which is what makes the auto-apply rule fire for one and
    not the other.
    """
    category = fx.create_couple_category(api)
    season = fx.setup_open_season(api, clock_iso=REFUND_CLOCK)

    guard = fx.setup_certified_guard(api, full_name="Refund Day Guard")
    for start_iso, end_iso in ((SHIFT_A_START, SHIFT_A_END),
                               (SHIFT_B_START, SHIFT_B_END)):
        shift = fx.schedule_shift(api, guard["lifeguard"]["id"], season["id"],
                                  start_iso, end_iso, ShiftRole.PRIMARY)
        confirmed = fx.transition_shift(api, shift["id"],
                                        GuardShiftStatus.CONFIRMED)
        assert confirmed["status"] == GuardShiftStatus.CONFIRMED

    parties = []
    for name, address, start_iso, end_iso, part_payment in (
        ("Refund Household A", "331 Cedar Court", PARTY_A_START, PARTY_A_END,
         0),
        ("Refund Household B", "332 Cedar Court", PARTY_B_START, PARTY_B_END,
         PART_PAYMENT),
    ):
        household = fx.create_household(
            api, primary_contact_name=name, address_line=address,
            member_count=2, prior_member=False,
        )
        membership = fx.setup_membership(api, household["id"], category["id"],
                                        season["id"], join_date="2027-05-22")
        invoiced = fx.invoice_membership(api, membership["id"])
        part_paid = None
        if part_payment:
            part_paid = fx.pay_membership(api, membership["id"], part_payment,
                                          MembershipPaymentAllocation.DUES)
        reservation = fx.request_party(api, membership["id"],
                                      zone=Zone.PAVILION, start_iso=start_iso,
                                      end_iso=end_iso, guest_count=12,
                                      host_party_size=8)
        confirmed = fx.transition_party(api, reservation["id"],
                                        ReservationStatus.CONFIRMED)
        parties.append({
            "household": household,
            "membership": membership,
            "invoiced": invoiced,
            "part_paid": part_paid,
            "reservation": confirmed,
        })
    return {"season": season, "a": parties[0], "b": parties[1]}


def _cancel_as_host(api, entry):
    return fx.transition_party(
        api, entry["reservation"]["id"], ReservationStatus.CANCELLED_BY_HOST,
        make_member_headers(entry["household"]["id"]),
    )


class TestTheCancellationRefundTurnsOnTheLeadTime:
    """One `to_status`, two refund rules, and one conditional auto-apply."""

    def test_both_parties_are_priced_and_confirmed_identically(self, api):
        """The two cases differ in lead time and balance, not in price.

        PRD §3.4: "a payment strictly smaller than the balance leaves
        `dues_status` exactly where it was"

        PRD §3.7: "Confirmation moves no money, because the charge was booked
        when the party was requested."

        Design: Corner/endpoints/conditional_action_the_cancellation_refund_turns_on_the_lead_time
        """
        ctx = _two_households_each_holding_a_confirmed_party(api)

        assert ctx["a"]["invoiced"]["balance_due_cents"] == \
            BILLING_INVOICE_TOTAL
        assert ctx["a"]["invoiced"]["dues_status"] == DuesStatus.INVOICED
        assert ctx["b"]["invoiced"]["balance_due_cents"] == \
            BILLING_INVOICE_TOTAL
        assert ctx["b"]["part_paid"]["amount_paid_cents"] == PART_PAYMENT
        assert ctx["b"]["part_paid"]["balance_due_cents"] == REMAINING_BALANCE
        assert ctx["b"]["part_paid"]["dues_status"] == DuesStatus.INVOICED

        for entry in (ctx["a"], ctx["b"]):
            assert entry["reservation"]["total_charge_cents"] == \
                REFUND_PARTY_TOTAL
            assert entry["reservation"]["status"] == ReservationStatus.CONFIRMED

    def test_cancelling_three_days_out_refunds_half(self, api):
        """Short notice halves the refund, rounded half up.

        PRD §3.7: "Cancelling at least seven days ahead of `start_iso` refunds
        the whole `total_charge_cents`; cancelling later than that refunds half
        the `total_charge_cents`, rounded half up to a whole cent."

        Design: Corner/endpoints/conditional_action_the_cancellation_refund_turns_on_the_lead_time
        """
        ctx = _two_households_each_holding_a_confirmed_party(api)
        fx.set_clock(api, SHORT_NOTICE_CLOCK)

        cancelled = _cancel_as_host(api, ctx["a"])
        assert cancelled["status"] == ReservationStatus.CANCELLED_BY_HOST
        assert cancelled["refunded_cents"] == REFUND_HALF

        household = fx.read_household(api, ctx["a"]["household"]["id"])
        assert household["party_charges_owed_cents"] == \
            REFUND_PARTY_TOTAL - REFUND_HALF
        assert household["account_credit_cents"] == REFUND_HALF

    def test_a_credit_below_the_balance_settles_nothing(self, api):
        """The auto-apply rule is all-or-nothing, so 8100 buys nothing.

        PRD §3.4: "A credit smaller than the balance is left sitting on the
        household account and applies nothing; the rule is all-or-nothing."

        Design: Corner/endpoints/conditional_action_the_cancellation_refund_turns_on_the_lead_time
        """
        ctx = _two_households_each_holding_a_confirmed_party(api)
        fx.set_clock(api, SHORT_NOTICE_CLOCK)
        _cancel_as_host(api, ctx["a"])

        membership = fx.read_membership(api, ctx["a"]["membership"]["id"])
        assert membership["dues_status"] == DuesStatus.INVOICED
        assert membership["balance_due_cents"] == BILLING_INVOICE_TOTAL
        assert membership["amount_paid_cents"] == 0

    def test_cancelling_exactly_seven_days_out_refunds_in_full(self, api):
        """The lead-time comparison is inclusive at the boundary.

        PRD §3.7: "Cancelling at least seven days ahead of `start_iso` refunds
        the whole `total_charge_cents`"

        Design: Corner/endpoints/conditional_action_the_cancellation_refund_turns_on_the_lead_time
        """
        ctx = _two_households_each_holding_a_confirmed_party(api)
        fx.set_clock(api, EXACT_SEVEN_DAYS_CLOCK)

        cancelled = _cancel_as_host(api, ctx["b"])
        assert cancelled["status"] == ReservationStatus.CANCELLED_BY_HOST
        assert cancelled["refunded_cents"] == REFUND_PARTY_TOTAL

    def test_a_credit_above_the_balance_settles_it_inside_the_request(self, api):
        """The whole balance clears and the remainder stays as credit.

        PRD §3.4: "if the household holds a membership in that reservation's
        season whose `dues_status` is `INVOICED` or `DELINQUENT`, and
        `account_credit_cents` is greater than or equal to that membership's
        `balance_due_cents`, then the whole balance is settled from the credit —
        `amount_paid_cents` rises by the balance, `dues_status` moves to `PAID`,
        `account_credit_cents` falls by the amount applied"

        Design: Corner/endpoints/conditional_action_the_cancellation_refund_turns_on_the_lead_time
        """
        ctx = _two_households_each_holding_a_confirmed_party(api)
        fx.set_clock(api, EXACT_SEVEN_DAYS_CLOCK)
        _cancel_as_host(api, ctx["b"])

        membership = fx.read_membership(api, ctx["b"]["membership"]["id"])
        assert membership["dues_status"] == DuesStatus.PAID
        assert membership["balance_due_cents"] == 0
        assert membership["amount_paid_cents"] == BILLING_INVOICE_TOTAL

        household = fx.read_household(api, ctx["b"]["household"]["id"])
        assert household["party_charges_owed_cents"] == 0
        assert household["account_credit_cents"] == \
            REFUND_PARTY_TOTAL - REMAINING_BALANCE

    def test_a_cancelled_party_cannot_be_refunded_twice(self, api):
        """CANCELLED_BY_HOST is terminal, so the money moves once.

        PRD §3.7: "`COMPLETED`, `REJECTED`, `CANCELLED_BY_HOST`,
        `CANCELLED_BY_CLOSURE` and `CANCELLED_BY_SUSPENSION` are all terminal."

        PRD §2.9: "the resource is not already in a terminal state
        (`ERR_ALREADY_TERMINAL`, 409)"

        Design: Corner/endpoints/conditional_action_the_cancellation_refund_turns_on_the_lead_time
        """
        ctx = _two_households_each_holding_a_confirmed_party(api)
        fx.set_clock(api, EXACT_SEVEN_DAYS_CLOCK)
        cancelled = _cancel_as_host(api, ctx["b"])

        validate_error(
            api.transition_party_reservation(
                ctx["b"]["reservation"]["id"],
                transition_payload(ReservationStatus.CANCELLED_BY_HOST),
                make_member_headers(ctx["b"]["household"]["id"]),
            ),
            ApiErrorId.ALREADY_TERMINAL, 409,
        )
        reservation = fx.read_reservation(api, ctx["b"]["reservation"]["id"])
        assert reservation["refunded_cents"] == cancelled["refunded_cents"]
        assert reservation["version"] == cancelled["version"]
