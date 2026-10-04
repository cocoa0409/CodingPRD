"""Validation ordering and role boundaries: existence before state, the credit gate
order, the protein variance band, the shared-split grace, and the RBAC matrix.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    DEFAULT_CLOCK,
    EMPTY_UUID,
    FM,
    HOST,
    PA,
    advance_clock,
    create_booking,
    create_party,
    fresh_table,
    grant_hold,
    grant_hold_at_later_clock,
    minimal_floor,
    read_party,
    read_reservation,
    seatings_for,
    set_clock,
    setup_floor,
    submit_booking,
)
from test_helpers.test_users import TEST_USERS, make_chef_headers


class TestExistenceBeforeBusinessRules:

    def test_hold_grant_with_an_unknown_table_returns_table_not_found(self):
        """PRD §2.10: "Every id in the path and every foreign key in the body must
        resolve before any business rule is evaluated. The first unresolvable segment
        determines the error returned, and the sibling returned always corresponds to
        that segment: ... `ERR_TABLE_NOT_FOUND` ... each carrying HTTP 404. A request
        that resolves only part of its path never reaches a state check or a fiscal
        check; existence is settled first."

        Design: Corner/validations/hold_grant_with_an_unknown_table_returns_table_not_found
        """
        scenario = setup_floor(tier_codes=("T4",), tables=(), chefs=())
        party = create_party(scenario)
        reservation = create_booking(scenario, party["id"], "T4", party_size=4)
        submit_booking(reservation["id"])

        response = api_client.grant_hold(
            reservation["id"],
            {"expected_table_version": 1, "table_id": "00000000-0000-4000-8000-000000000077"},
            HOST)
        validate_error(response, ApiErrorId.ERR_TABLE_NOT_FOUND)

        after = read_reservation(reservation["id"])
        assert after["status"] == "REQUESTED"
        assert after["hold_count"] == 0
        assert after["table_id"] is None


class TestCreditGates:

    def test_credit_eligibility_precedes_the_cap_and_the_balance(self):
        """PRD §3.6: "A booking whose party carries `loyalty_tier` `NONE` or `SILVER`
        may not apply reusable credit at all, and a non-zero `credit_to_apply_cents` on
        such a booking is rejected with `ERR_CREDIT_INELIGIBLE` (HTTP 422)."
        PRD §3.6: "An application exceeding the cap — the smaller of 2500 cents and
        twelve percent of the pre-credit check — is rejected with `ERR_CREDIT_OVER_CAP`
        (HTTP 422)."
        PRD §3.6: "Where more than one gate fails, the higher-priority one is reported."

        Design: Corner/validations/credit_eligibility_precedes_the_cap_and_the_balance
        """
        scenario = setup_floor(tables=(("T6", 6), ("T4", 4)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        silver = create_party(scenario, loyalty_tier="SILVER", name="Marcus Bell",
                              phone="212-555-0164")
        gold = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                            phone="212-555-0177")

        from test_helpers.fixtures import seed_seated_booking_with_finished_grill
        silver_seat = seed_seated_booking_with_finished_grill(
            scenario, silver["id"], "T6", scenario["tables"][0]["id"], party_size=4)
        gold_seat = seed_seated_booking_with_finished_grill(
            scenario, gold["id"], "T4", scenario["tables"][1]["id"], party_size=4)

        silver_now = read_reservation(silver_seat["reservation"]["id"])
        response = api_client.close_reservation(
            silver_seat["reservation"]["id"],
            {"expected_reservation_version": silver_now["version"],
             "credit_to_apply_cents": 9000}, HOST)
        validate_error(response, ApiErrorId.ERR_CREDIT_INELIGIBLE)

        gold_now = read_reservation(gold_seat["reservation"]["id"])
        response2 = api_client.close_reservation(
            gold_seat["reservation"]["id"],
            {"expected_reservation_version": gold_now["version"],
             "credit_to_apply_cents": 9000}, HOST)
        validate_error(response2, ApiErrorId.ERR_CREDIT_OVER_CAP)

        assert read_reservation(silver_seat["reservation"]["id"])["status"] == "SEATED"
        assert read_reservation(gold_seat["reservation"]["id"])["status"] == "SEATED"

    def test_credit_wallet_balance_is_checked_after_the_cap(self):
        """PRD §3.6: "Finally, an application the party's `loyalty_credit_cents`
        cannot cover is rejected with `ERR_CREDIT_EXCEEDED` (HTTP 402)."
        PRD §3.6: "A non-zero application smaller than the 500-cent minimum ticket
        amount is rejected with `ERR_CREDIT_BELOW_MINIMUM` (HTTP 422)."

        Design: Corner/validations/credit_eligibility_precedes_the_cap_and_the_balance
        """
        scenario = setup_floor(tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        gold = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                            phone="212-555-0177")

        from test_helpers.fixtures import seed_seated_booking_with_finished_grill
        seated = seed_seated_booking_with_finished_grill(
            scenario, gold["id"], "T4", scenario["tables"][0]["id"], party_size=4)
        assert read_party(gold["id"])["loyalty_credit_cents"] == 0

        now = read_reservation(seated["reservation"]["id"])
        response = api_client.close_reservation(
            seated["reservation"]["id"],
            {"expected_reservation_version": now["version"], "credit_to_apply_cents": 500},
            HOST)
        validate_error(response, ApiErrorId.ERR_CREDIT_EXCEEDED)

    def test_credit_below_the_minimum_ticket_is_refused_before_the_cap(self):
        """PRD §3.6: "A non-zero application smaller than the 500-cent minimum ticket
        amount is rejected with `ERR_CREDIT_BELOW_MINIMUM` (HTTP 422)."
        PRD §3.6: "When credit is applied, the consumed amount moves out of
        `loyalty_credit_cents`."

        Design: Corner/validations/credit_below_the_minimum_ticket_is_refused_before_the_cap
        """
        scenario = setup_floor(tables=(("T6", 6),), chefs=(("Kenji Ito", "ZONE_A"),))
        gold = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                            phone="212-555-0177")

        from test_helpers.fixtures import seed_seated_booking_with_finished_grill
        seated = seed_seated_booking_with_finished_grill(
            scenario, gold["id"], "T6", scenario["tables"][0]["id"], party_size=4)

        now = read_reservation(seated["reservation"]["id"])
        response = api_client.close_reservation(
            seated["reservation"]["id"],
            {"expected_reservation_version": now["version"], "credit_to_apply_cents": 400},
            HOST)
        validate_error(response, ApiErrorId.ERR_CREDIT_BELOW_MINIMUM)

        closed = get_success_data(api_client.close_reservation(
            seated["reservation"]["id"],
            {"expected_reservation_version": now["version"], "credit_to_apply_cents": 0},
            HOST))
        assert closed["status"] == "CLOSED"
        assert closed["credit_applied_cents"] == 0


class TestProteinVarianceBand:

    def test_protein_variance_beyond_the_cap_returns_variance_exceeded(self):
        """PRD §3.5: "A variance adjustment may raise the issue by at most 40 grams
        above `standard_grams` and may never take it below 1 gram; an adjustment
        outside that band, supplied as `delta_grams`, is rejected with
        `ERR_PROTEIN_VARIANCE_EXCEEDED` (HTTP 422)."
        PRD §3.5: "An accepted adjustment adds `delta_grams` to `issued_grams`,
        recomputes `variance_grams`, recomputes the ticket's `cost_cents`."

        Design: Corner/errors/protein_variance_beyond_the_cap_returns_variance_exceeded
        """
        scenario = setup_floor(tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")

        from test_helpers.fixtures import seed_seated_booking_with_finished_grill
        seated = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T4", scenario["tables"][0]["id"], party_size=4)
        ticket_id = seated["protein_ticket_id"]
        chef_id = scenario["chefs"][0]["id"]
        headers = make_chef_headers(chef_id)

        ticket = get_success_data(api_client.get_protein_ticket(ticket_id, headers))
        assert ticket["standard_grams"] == 960
        assert ticket["issued_grams"] == 720

        response = api_client.adjust_protein_variance(ticket_id, 300, headers)
        validate_error(response, ApiErrorId.ERR_PROTEIN_VARIANCE_EXCEEDED)

        accepted = validate_success(api_client.adjust_protein_variance(ticket_id, 40, headers))
        assert accepted["issued_grams"] == 760
        assert accepted["variance_grams"] == -200

        response2 = api_client.adjust_protein_variance(ticket_id, -100000, headers)
        validate_error(response2, ApiErrorId.ERR_PROTEIN_VARIANCE_EXCEEDED)


class TestTierCapacityEdge:

    def test_seven_guests_on_a_six_seat_tier_are_refused_for_the_table_not_the_tier(self):
        """PRD §3.2: "the `party_size` must be at least 1 and no greater than the
        `seat_capacity` of the tier named by `tier_code` at that venue; ... A booking
        whose party size does not fit the named tier's capacity band is rejected with
        `ERR_TIER_MISMATCH` (HTTP 422)."
        PRD §3.3: "refused with `ERR_TABLE_OVER_CAPACITY` (HTTP 409) when the guests to
        be seated would push the table's `guests_seated` plus the incoming `party_size`
        past its `seat_capacity`."
        PRD §3.1: "the fraction by which a party may exceed the tier's seat capacity
        before the tier is refused; it defaults to 1.25" — and it is "recorded
        separately because the floor may seat a party at a table whose physical seats
        differ from the tier's nominal band".

        Design: Corner/validations/tier_mismatch_edge_between_six_and_seven_guests_on_a_six_seat_tier
        """
        scenario = setup_floor(tier_codes=("T6",), tables=(("T6", 6),), chefs=())
        party = create_party(scenario)
        tier_id = scenario["tiers"]["T6"]["id"]

        six = create_booking(scenario, party["id"], "T6", party_size=6)
        submit_booking(six["id"])
        assert read_reservation(six["id"])["status"] == "REQUESTED"
        assert scenario["tiers"]["T6"]["over_capacity_ratio"] == 1.25

        seven = create_booking(scenario, party["id"], "T6", party_size=7,
                               scheduled_time="2026-09-03T20:00:00Z")
        submit_booking(seven["id"])
        held = grant_hold(seven["id"], scenario["tables"][0]["id"])
        assert held["status"] == "HELD"

        booked = get_success_data(api_client.list_reservations(
            HOST, {"party_id": party["id"]}))
        assert len(booked) == 2
        assert scenario["tiers"]["T6"]["seat_capacity"] == 6
        assert scenario["tables"][0]["seat_capacity"] == 6
        assert tier_id is not None


class TestHoldCapVersusCapacityPriority:

    def test_an_over_capacity_booking_at_its_hold_cap_reports_the_capacity_error(self):
        """PRD §2.10: "Within the business rules, a request that a workflow declares to
        be guarded by more than one rule is always reported against the highest-priority
        rule it violates, so a booking that both exceeds its hold limit and names a
        retired tier surfaces the hold-limit failure rather than the tier failure."
        PRD §3.3: "refused with `ERR_TABLE_OVER_CAPACITY` (HTTP 409) when the guests to
        be seated would push the table's `guests_seated` plus the incoming `party_size`
        past its `seat_capacity`; ... refused with `ERR_HOLD_LIMIT_EXCEEDED` (HTTP 409)
        once `hold_count` has already reached the cap of 3 holds in the current episode."

        Design: Corner/validations/hold_grant_fails_on_over_capacity_before_the_hold_cap
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK,
                               tables=(("T2", 2), ("T4", 4)),
                               chefs=())
        party = create_party(scenario)
        table_id = scenario["tables"][0]["id"]
        reservation = create_booking(scenario, party["id"], "T2", party_size=2)
        submit_booking(reservation["id"])

        grant_hold(reservation["id"], table_id)
        advance_clock(DEFAULT_CLOCK, 25)
        grant_hold_at_later_clock(reservation["id"], table_id)
        advance_clock(DEFAULT_CLOCK, 50)
        grant_hold_at_later_clock(reservation["id"], table_id)
        assert read_reservation(reservation["id"])["hold_count"] == 3

        # The fourth attempt must itself be a legal re-park (previous window closed)
        # for the hold-cap guard to be the rule that fires.
        advance_clock(DEFAULT_CLOCK, 75)
        response = grant_hold_at_later_clock(reservation["id"], scenario["tables"][1]["id"])
        validate_error(response, ApiErrorId.ERR_HOLD_LIMIT_EXCEEDED)
        assert read_reservation(reservation["id"])["hold_count"] == 3

    def test_the_capacity_check_is_reachable_on_its_own(self):
        """PRD §3.3: "refused with `ERR_TABLE_OVER_CAPACITY` (HTTP 409) when the guests
        to be seated would push the table's `guests_seated` plus the incoming
        `party_size` past its `seat_capacity`."
        PRD §2.10: "then whether the target is in a state from which the requested
        transition is declared (otherwise `ERR_INVALID_STATE`, HTTP 409), and only then
        the business rules."

        Design: Corner/validations/hold_grant_fails_on_over_capacity_before_the_hold_cap
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK,
                               tables=(("T4", 4), ("T2", 2), ("T6", 6)),
                               chefs=())
        party = create_party(scenario)
        large = create_booking(scenario, party["id"], "T4", party_size=4)
        submit_booking(large["id"])

        response = api_client.grant_hold(
            large["id"],
            {"expected_table_version": fresh_table(scenario, scenario["tables"][1]["id"])["version"],
             "table_id": scenario["tables"][1]["id"]},
            HOST)
        validate_error(response, ApiErrorId.ERR_TABLE_OVER_CAPACITY)

        after = read_reservation(large["id"])
        assert after["status"] == "REQUESTED"
        assert after["hold_count"] == 0


class TestSharedSplitGrace:

    def test_share_split_grace_returns_shared_split_invalid_for_a_stale_sibling(self):
        """PRD §3.3: "When a booking carries a non-null `invite_code`, every other
        booking already holding the same code must still have `hold_until` later than
        the clock, and its `scheduled_time` must fall within the shared grace band of
        this booking's — otherwise the hold is rejected with `ERR_SHARED_SPLIT_INVALID`
        (HTTP 422)."

        Design: Corner/errors/share_split_grace_returns_shared_split_invalid_for_a_stale_sibling
        """
        scenario = setup_floor(tables=(("T4", 4), ("T2", 2)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)

        sibling1 = create_booking(scenario, party["id"], "T4", party_size=4,
                                  invite_code="SHARE-3")
        submit_booking(sibling1["id"])
        grant_hold(sibling1["id"], scenario["tables"][0]["id"])

        sibling2 = create_booking(scenario, party["id"], "T2", party_size=2,
                                  invite_code="SHARE-3")
        submit_booking(sibling2["id"])

        advance_clock(DEFAULT_CLOCK, 30)

        response = api_client.grant_hold(
            sibling2["id"],
            {"expected_table_version": fresh_table(scenario, scenario["tables"][1]["id"])["version"],
             "table_id": scenario["tables"][1]["id"]},
            HOST)
        validate_error(response, ApiErrorId.ERR_SHARED_SPLIT_INVALID)

        after = read_reservation(sibling2["id"])
        assert after["status"] == "REQUESTED"
        assert after["hold_count"] == 0


class TestMaintenanceWindowLateness:

    def test_maintenance_window_accept_after_the_late_grace_returns_window_late(self):
        """PRD §3.7: "Accepting a window moves it to `ACTIVE` and is gated three ways:
        the `planned_start_at` may not be earlier than the clock minus the maintenance
        late grace constant, so a window cannot be accepted long after it was meant to
        start ... A window accepted outside those bounds is rejected with
        `ERR_MAINTENANCE_WINDOW_LATE` (HTTP 409) when the lateness is the problem and
        with `ERR_INVALID_STATE` otherwise."

        Design: Corner/errors/maintenance_window_accept_after_the_late_grace_returns_window_late
        """
        scenario = setup_floor(tier_codes=(), tables=(("T6", 6),), chefs=())
        table_id = scenario["tables"][0]["id"]

        window = get_success_data(api_client.create_maintenance_window(
            {"venue_id": scenario["venue"]["id"], "table_id": table_id,
             "maintenance_kind": "GRILL_REBUILD",
             "planned_start_at": "2026-09-02T06:00:00Z",
             "planned_end_at": "2026-09-02T07:00:00Z"}, FM))

        response = api_client.accept_maintenance_window(window["id"], FM)
        validate_error(response, ApiErrorId.ERR_MAINTENANCE_WINDOW_LATE)

        reread = get_success_data(api_client.get_maintenance_window(window["id"], FM))
        assert reread["status"] == "SCHEDULED"
        assert fresh_table(scenario, table_id)["status"] == "AVAILABLE"


class TestChefRotationGate:

    def test_committing_a_show_to_an_off_shift_chef_returns_chef_not_on_station(self):
        """PRD §3.4: "at least one `ChefAssignment` at the venue must be `ON_STATION`
        with no `current_table_id`, and that chef must either have no finished show yet
        at this venue or have `minutes_since_show` of at least the minimum chef reset
        constant of 3 minutes. When no such chef exists the seating is refused with
        `ERR_CHEF_ROTATION_EXHAUSTED` (HTTP 409), and nothing is queued server-side."

        Design: Corner/errors/committing_a_show_to_an_off_shift_chef_returns_chef_not_on_station
        """
        scenario = setup_floor(tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),),
                               clock_in=0)
        party = create_party(scenario)
        reservation = create_booking(scenario, party["id"], "T4", party_size=4)
        submit_booking(reservation["id"])
        grant_hold(reservation["id"], scenario["tables"][0]["id"])
        held = read_reservation(reservation["id"])

        for chef in scenario["chefs"]:
            assert get_success_data(api_client.get_chef(chef["id"], FM))["status"] == "OFF_SHIFT"

        response = api_client.seat_reservation(reservation["id"], HOST)
        validate_error(response, ApiErrorId.ERR_CHEF_ROTATION_EXHAUSTED)

        after = read_reservation(reservation["id"])
        assert after["status"] == "HELD"
        assert after["hold_until"] == held["hold_until"]
        assert after["table_id"] == scenario["tables"][0]["id"]
        assert seatings_for(reservation_id=reservation["id"]) == []


class TestAuthentication:

    def test_unauthenticated_request_without_role_headers_returns_unauthenticated(self):
        """PRD §2.1: "Every request must carry two headers. `X-User-ID` identifies the
        actor, and `X-User-Role` declares the capacity in which the actor is acting. If
        either header is absent, or if the role is not one of the five roles the API
        recognises, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_without_role_headers_returns_unauthenticated
        """
        set_clock(DEFAULT_CLOCK)
        response = api_client.get_venue(EMPTY_UUID, {})
        body = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)

        assert body["error_id"] == "ERR_UNAUTHENTICATED"
        assert isinstance(body["message"], str) and body["message"]


class TestPeerRoleBoundaries:

    def test_sushi_chef_forbidden_from_firing_a_grill_show(self):
        """PRD §2.1: "A `Chef` clocks in and out, clears a finished show, starts and
        finishes show phases, and posts protein variance and protein void events. A
        `SushiChef` fires sushi tickets and advances, restages, restarts or voids
        them."
        PRD §2.1: "If the headers are present but the declared role is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/sushi_chef_forbidden_from_firing_a_grill_show
        """
        scenario = setup_floor(tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),
                                                           ("Ana Ruiz", "ZONE_B")))
        party = create_party(scenario)
        reservation = create_booking(scenario, party["id"], "T4", party_size=4)
        submit_booking(reservation["id"])
        grant_hold(reservation["id"], scenario["tables"][0]["id"])
        seated = api_client.seat_reservation(reservation["id"], HOST)
        sushi_show_id = get_success_data(seated)["current_sushi_show_id"]

        response = api_client.post_show_event(sushi_show_id, "START",
                                              TEST_USERS["sushi_chef_headers"])
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        after = get_success_data(api_client.get_show(sushi_show_id, FM))
        assert after["status"] == "PLANNED"
        assert after["actual_start_at"] is None

        allowed = validate_success(api_client.post_show_event(
            sushi_show_id, "START", make_chef_headers(seated.json()["data"]["chef_assignment_id"])))
        assert allowed["status"] == "STARTED"

    def test_host_forbidden_from_commissioning_a_grill_table(self):
        """PRD §2.1: "A `FloorManager` owns the physical floor: commissioning grill
        tables, posting grill-table events, advancing the venue's batch epoch, adding
        chefs to the roster" (a `Host` does not hold this operation).

        Design: Corner/rbac/host_forbidden_from_commissioning_a_grill_table
        """
        scenario = minimal_floor()
        payload = {"venue_id": scenario["venue"]["id"], "tier_code": "T4",
                   "seat_capacity": 4}

        response = api_client.create_table(payload, HOST)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        listed = get_success_data(api_client.list_tables(FM, {"venue_id": scenario["venue"]["id"]}))
        assert listed == []

        created = validate_success(api_client.create_table(payload, FM), expected_status=201)
        assert created["status"] == "AVAILABLE"

    def test_platform_admin_cannot_clock_a_chef_in(self):
        """PRD §2.1: "A `PlatformAdmin` is the chain operator who opens venues and
        configures table tiers, and is the only role permitted to open a venue, retire
        a table tier and set the logical clock."
        PRD §3.1: "A chef clocks in with the `event_type` `CLOCK_IN` and moves from
        `OFF_SHIFT` to `ON_STATION`; ... On clock-in the chef's `sequence_index` is set
        to one more than the highest `sequence_index` among chefs at the venue already
        on station, or to 1 when there are none."

        Design: Corner/rbac/platform_admin_cannot_clock_a_chef_in
        """
        scenario = setup_floor(tier_codes=(), tables=(), chefs=(("Kenji Ito", "ZONE_A"),),
                               clock_in=0)
        chef_id = scenario["chefs"][0]["id"]
        version = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))["version"]

        response = api_client.post_chef_event(
            chef_id, {"event_type": "CLOCK_IN", "expected_venue_version": version}, PA)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_success_data(api_client.get_chef(chef_id, FM))["status"] == "OFF_SHIFT"

        allowed = validate_success(api_client.post_chef_event(
            chef_id, {"event_type": "CLOCK_IN", "expected_venue_version": version},
            make_chef_headers(chef_id)))
        assert allowed["status"] == "ON_STATION"
        assert allowed["sequence_index"] == 1

    def test_entity_backed_identity_is_enforced_on_chef_events(self):
        """PRD §2.1: "When `X-User-Role` is `Chef`, `X-User-ID` is the `id` of the
        acting `ChefAssignment`, and ownership checks on any resource that references a
        `ChefAssignment` compare the resource's foreign-key field to `X-User-ID`."

        Design: Corner/rbac/platform_admin_cannot_clock_a_chef_in
        """
        scenario = setup_floor(tier_codes=(), tables=(),
                               chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")),
                               clock_in=0)
        chef_a, chef_b = scenario["chefs"][0], scenario["chefs"][1]
        version = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))["version"]

        response = api_client.post_chef_event(
            chef_a["id"], {"event_type": "CLOCK_IN", "expected_venue_version": version},
            make_chef_headers(chef_b["id"]))
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_success_data(api_client.get_chef(chef_a["id"], FM))["status"] == "OFF_SHIFT"