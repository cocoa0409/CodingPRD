"""Guard rules, their error ids and the fixed order in which they are reported.

Each case here drives one declared gate from §2.8 with an otherwise legal body,
then confirms the refusal changed nothing: the log keeps its row count, the row
keeps its state, and the money keeps its value.
"""

from test_helpers import (
    AUGUST_MONTH,
    BOOTSTRAP_CLOCK,
    DELIVERY_OUT_AT,
    ERR_ACTING_RAILROAD_UNKNOWN,
    ERR_CAR_BAD_ORDER_NOT_INTERCHANGEABLE,
    ERR_CAR_NOT_BAD_ORDERED,
    ERR_CAR_NOT_FOUND,
    ERR_CAR_TYPE_NOT_FOUND,
    ERR_CORRECTION_CONFIRM_NOT_COUNTERPARTY,
    ERR_CORRECTION_CONFIRM_WINDOW_EXPIRED,
    ERR_CORRECTION_NOT_CONFIRMED,
    ERR_CORRECTION_REQUEST_NOT_FOUND,
    ERR_CORRECTION_TARGET_NOT_VOIDABLE,
    ERR_COUNTER_AMOUNT_OUT_OF_RANGE,
    ERR_CYCLE_ARCHIVED_IMMUTABLE,
    ERR_CYCLE_NOT_EXCHANGED,
    ERR_DELIVERING_ROAD_NOT_IN_CUSTODY,
    ERR_DISPUTE_NOT_FOUND,
    ERR_DISPUTE_SUBJECT_AMBIGUOUS,
    ERR_DISPUTE_WINDOW_EXPIRED,
    ERR_DUPLICATE_RESOURCE,
    ERR_EMBARGO_DOES_NOT_COVER_WINDOW,
    ERR_EMBARGO_ORDER_NOT_FOUND,
    ERR_EMBARGO_SELF_ISSUED,
    ERR_INTERCHANGE_EVENT_NOT_FOUND,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_STATE_TRANSITION,
    ERR_JUNCTION_CLOSED,
    ERR_JUNCTION_NOT_FOUND,
    ERR_LEDGER_ENTRY_NOT_FOUND,
    ERR_MOVEMENT_NOT_FOUND,
    ERR_NOT_A_PARTY_TO_RESOURCE,
    ERR_NO_CUSTODY_AT_DEFECT_TIME,
    ERR_PER_DIEM_CREDIT_LIMIT_EXCEEDED,
    ERR_RAILROAD_NOT_FOUND,
    ERR_RAILROAD_SUSPENDED,
    ERR_RECLAIM_CLAIM_NOT_FOUND,
    ERR_RECLAIM_EVIDENCE_MISSING,
    ERR_RECLAIM_FILING_WINDOW_EXPIRED,
    ERR_RECLAIM_WINDOW_TOO_SHORT,
    ERR_REOPEN_WINDOW_EXPIRED,
    ERR_REOPEN_WINDOW_STILL_OPEN,
    ERR_REPAIR_AMOUNT_INVALID,
    ERR_REPAIR_BILL_NOT_FOUND,
    ERR_REPAIR_BILL_NOT_SUBMITTED,
    ERR_REPAIR_PREAUTH_REQUIRED,
    ERR_ROADS_NOT_CONNECTED_AT_JUNCTION,
    ERR_SETTLEMENT_CYCLE_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNKNOWN_ROLE,
    RETURN_AT_11464,
    ROLE_FLEET_OWNER,
    ApiClient,
    World,
    admin_headers,
    assert_error_envelope,
    assert_hours,
    assert_instant_equals,
    assert_money,
    bad_order_band_world,
    bad_order_on_bn_world,
    capture_delivery,
    closed_movement_of,
    closed_segment_world,
    computed_cycle,
    deliver_out,
    draft_repair_bill,
    exchanged_cycle,
    file_dispute,
    file_reclaim,
    headers_missing_role,
    headers_with_empty_role,
    headers_with_unknown_railroad,
    headers_with_unknown_role,
    issue_embargo,
    open_cycle,
    read_cycle,
    read_movement,
    register_car,
    register_car_type,
    register_junction,
    register_railroad,
    set_clock,
    settled_cycle,
    standard_world,
    submitted_repair_bill,
    validate_paginated,
    validate_success,
)
import test_helpers.factories as f

UNUSED_RAILROAD_ID = "11111111-1111-4111-8111-111111111111"
UNUSED_CAR_TYPE_ID = "22222222-2222-4222-8222-222222222222"
UNUSED_JUNCTION_ID = "33333333-3333-4333-8333-333333333333"
UNUSED_CAR_ID = "44444444-4444-4444-8444-444444444444"
UNUSED_EVENT_ID = "55555555-5555-4555-8555-555555555555"
UNUSED_MOVEMENT_ID = "66666666-6666-4666-8666-666666666666"
UNUSED_CLAIM_ID = "77777777-7777-4777-8777-777777777777"
UNUSED_EMBARGO_ID = "88888888-8888-4888-8888-888888888888"
UNUSED_BILL_ID = "99999999-9999-4999-8999-999999999999"
UNUSED_CYCLE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNUSED_DISPUTE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UNUSED_CORRECTION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
UNUSED_LEDGER_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


class TestAuthenticationHeaderGates:
    """The three header failures are distinct and precede the path lookup."""

    def test_an_absent_or_empty_role_header_is_unauthenticated(self, api: ApiClient):
        """Both the missing header and the empty string report 401 ERR_UNAUTHENTICATED.

        PRD: "`X-User-Role` present and non-empty — otherwise `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_or_unknown_auth_headers_return_unauthenticated
        """
        world = standard_world(api)

        absent = api.get_car(world.car, headers_missing_role())
        assert_error_envelope(absent, ERR_UNAUTHENTICATED, 401)

        empty = api.get_car(world.car, headers_with_empty_role(world.cx))
        assert_error_envelope(empty, ERR_UNAUTHENTICATED, 401)

    def test_a_well_formed_but_unlisted_role_is_unknown(self, api: ApiClient):
        """A role outside the five declared names is 401 ERR_UNKNOWN_ROLE.

        PRD: "`X-User-Role` names one of the five roles — otherwise `ERR_UNKNOWN_ROLE`."

        Design: Corner/validations/missing_or_unknown_auth_headers_return_unauthenticated
        """
        world = standard_world(api)

        refused = api.get_car(world.car, headers_with_unknown_role(world.cx))
        assert_error_envelope(refused, ERR_UNKNOWN_ROLE, 401)

    def test_an_unknown_acting_railroad_is_reported_before_the_path_lookup(self, api: ApiClient):
        """A bogus acting road on a bogus car reports the header error, not the car error.

        PRD: "They run in one fixed ascending order, and the **first** rule that fails determines the response — later violations are never reported even when several hold simultaneously."

        Design: Corner/validations/missing_or_unknown_auth_headers_return_unauthenticated
        """
        world = standard_world(api)

        refused = api.get_car(
            UNUSED_CAR_ID,
            headers_with_unknown_railroad(ROLE_FLEET_OWNER, UNUSED_RAILROAD_ID),
        )
        assert_error_envelope(refused, ERR_ACTING_RAILROAD_UNKNOWN, 403)

        allowed = validate_success(api.get_car(world.car, world.owner(world.cx)))
        assert allowed["id"] == world.car


class TestPathLookupNamesTheEntity:
    """One unused identifier yields thirteen different not-found error ids."""

    def test_every_by_id_read_names_its_own_entity(self, api: ApiClient):
        """Thirteen 404s with thirteen distinct error ids, never one generic id.

        PRD: "Every identifier in the URL path resolves to an existing row of its entity, checked left to right, the error naming the entity that failed: `ERR_RAILROAD_NOT_FOUND`, `ERR_JUNCTION_NOT_FOUND`, `ERR_CAR_TYPE_NOT_FOUND`, `ERR_CAR_NOT_FOUND`, `ERR_INTERCHANGE_EVENT_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_RECLAIM_CLAIM_NOT_FOUND`, `ERR_EMBARGO_ORDER_NOT_FOUND`, `ERR_REPAIR_BILL_NOT_FOUND`, `ERR_SETTLEMENT_CYCLE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CORRECTION_REQUEST_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`."

        Design: Corner/validations/every_path_segment_probe_returns_not_found
        """
        headers = admin_headers()
        probes = [
            (api.get_railroad(UNUSED_RAILROAD_ID, headers), ERR_RAILROAD_NOT_FOUND),
            (api.get_junction(UNUSED_JUNCTION_ID, headers), ERR_JUNCTION_NOT_FOUND),
            (api.get_car_type(UNUSED_CAR_TYPE_ID, headers), ERR_CAR_TYPE_NOT_FOUND),
            (api.get_car(UNUSED_CAR_ID, headers), ERR_CAR_NOT_FOUND),
            (api.get_interchange_event(UNUSED_EVENT_ID, headers),
             ERR_INTERCHANGE_EVENT_NOT_FOUND),
            (api.get_movement(UNUSED_MOVEMENT_ID, headers), ERR_MOVEMENT_NOT_FOUND),
            (api.get_reclaim_claim(UNUSED_CLAIM_ID, headers), ERR_RECLAIM_CLAIM_NOT_FOUND),
            (api.get_embargo_order(UNUSED_EMBARGO_ID, headers),
             ERR_EMBARGO_ORDER_NOT_FOUND),
            (api.get_repair_bill(UNUSED_BILL_ID, headers), ERR_REPAIR_BILL_NOT_FOUND),
            (api.get_settlement_cycle(UNUSED_CYCLE_ID, headers),
             ERR_SETTLEMENT_CYCLE_NOT_FOUND),
            (api.get_dispute(UNUSED_DISPUTE_ID, headers), ERR_DISPUTE_NOT_FOUND),
            (api.get_correction_request(UNUSED_CORRECTION_ID, headers),
             ERR_CORRECTION_REQUEST_NOT_FOUND),
            (api.get_ledger_entry(UNUSED_LEDGER_ID, headers), ERR_LEDGER_ENTRY_NOT_FOUND),
        ]

        seen = []
        for response, expected in probes:
            body = assert_error_envelope(response, expected, 404)
            seen.append(body["error_id"])
        assert len(set(seen)) == 13


AT_THE_CLOCK = "2026-08-26T00:00:00Z"


def _return_exactly_at_the_clock(api):
    """A 48-hour trip whose closing handoff is stamped at the logical clock."""
    world = standard_world(api)
    set_clock(api, DELIVERY_OUT_AT, world)
    capture_delivery(api, world.car, world.jct, world.cx, world.bn, DELIVERY_OUT_AT,
                     1000, "LOADED", world=world)
    set_clock(api, AT_THE_CLOCK, world)
    event = capture_delivery(api, world.car, world.jct, world.bn, world.cx,
                             AT_THE_CLOCK, 1000, "LOADED", world=world)
    return world, event


class TestBoundaryInstantsAreAccepted:
    """An instant equal to the clock, and an unchanged odometer, are both legal."""

    def test_an_instant_exactly_at_the_clock_is_not_in_the_future(self, api: ApiClient):
        """The handoff is recorded and closes the segment at that same instant.

        PRD: "No supplied instant may lie after the logical clock, otherwise `ERR_EVENT_IN_FUTURE`."

        Design: Corner/validations/event_recorded_exactly_at_the_clock_is_accepted
        """
        world, event = _return_exactly_at_the_clock(api)

        assert event["status"] == "RECORDED"
        assert_instant_equals(event["interchange_at"], AT_THE_CLOCK, "interchange_at")

        movement = closed_movement_of(api, world.car, world.bn,
                                    world.accountant(world.bn))
        assert_instant_equals(movement["end_at"], AT_THE_CLOCK, "end_at")
        assert_hours(movement["chargeable_hours"], 44.00, "chargeable_hours")

    def test_an_unchanged_odometer_is_legal_and_bills_no_mileage(self, api: ApiClient):
        """1000 miles in and 1000 miles out give 0 billable miles and 4700 of hire.

        PRD: "`mileage_component_cents` is billable miles multiplied by `mileage_rate_millicents_per_mile`, divided by 1000 to convert millicents to cents, and rounded half up — **once per segment**."

        Design: Corner/validations/event_recorded_exactly_at_the_clock_is_accepted
        """
        world, event = _return_exactly_at_the_clock(api)
        movement = closed_movement_of(api, world.car, world.bn,
                                    world.accountant(world.bn))

        assert movement["end_odometer_miles"] == movement["start_odometer_miles"]
        assert_money(movement["mileage_component_cents"], 0, "mileage_component_cents")
        assert movement["chargeable_days"] == 2
        assert_money(movement["time_component_cents"], 4700, "time_component_cents")
        assert_money(movement["gross_hire_cents"], 4700, "gross_hire_cents")


def _capture_guard_world(api):
    """The car sits on BN, with a suspended road, a closed junction and a spare pair."""
    world = standard_world(api)
    register_railroad(api, "NS", world, status="SUSPENDED")
    register_junction(api, "JCT-KC", world.bn, world.ns, world)
    register_junction(api, "JCT-STL", world.cx, world.bn, world, status="CLOSED")
    set_clock(api, DELIVERY_OUT_AT, world)
    capture_delivery(api, world.car, world.jct, world.cx, world.bn, DELIVERY_OUT_AT,
                     1000, "LOADED", world=world)
    return world


class TestInterchangeCaptureBusinessGuards:
    """Six independent facts guard one endpoint, each with its own error id."""

    def test_a_suspended_receiving_road_may_not_take_the_car(self, api: ApiClient):
        """NS is a legal road of JCT-KC yet cannot receive while SUSPENDED.

        PRD: "Every railroad named on a write — the acting road, the delivering road, the receiving road, the payer, the payee, the owner — has `status` `ACTIVE` — otherwise `ERR_RAILROAD_SUSPENDED`."

        Design: Corner/validations/interchange_capture_business_guards_rejected
        """
        world = _capture_guard_world(api)
        junction = world.junctions["JCT-KC"]

        refused = api.create_interchange_event(
            f.delivery_event_payload(world.car, junction, world.bn, world.ns,
                                     DELIVERY_OUT_AT, 1100, "LOADED"),
            world.clerk(world.bn))
        assert_error_envelope(refused, ERR_RAILROAD_SUSPENDED, 422)

        car = validate_success(api.get_car(world.car, world.owner(world.cx)))
        assert car["current_handling_road_id"] == world.bn

    def test_a_closed_junction_refuses_the_handoff(self, api: ApiClient):
        """JCT-STL connects the right pair but is CLOSED, so nothing may cross it.

        PRD: "Interchange capture and the issuing of an empty-routing obligation both require the referenced junction to have `status` `OPEN` — otherwise `ERR_JUNCTION_CLOSED`."

        Design: Corner/validations/interchange_capture_business_guards_rejected
        """
        world = _capture_guard_world(api)
        junction = world.junctions["JCT-STL"]

        refused = api.create_interchange_event(
            f.delivery_event_payload(world.car, junction, world.bn, world.cx,
                                     DELIVERY_OUT_AT, 1100, "LOADED"),
            world.clerk(world.bn))
        assert_error_envelope(refused, ERR_JUNCTION_CLOSED, 422)

    def test_the_two_roads_must_be_the_junctions_own_pair(self, api: ApiClient):
        """CX is not a road of JCT-KC, so the handoff cannot have happened there.

        PRD: "On interchange capture, `delivering_road_id` and `receiving_road_id` are exactly the two distinct roads of the junction, in either order — otherwise `ERR_ROADS_NOT_CONNECTED_AT_JUNCTION`."

        Design: Corner/validations/interchange_capture_business_guards_rejected
        """
        world = _capture_guard_world(api)
        junction = world.junctions["JCT-KC"]

        refused = api.create_interchange_event(
            f.delivery_event_payload(world.car, junction, world.bn, world.cx,
                                     DELIVERY_OUT_AT, 1100, "LOADED"),
            world.clerk(world.bn))
        assert_error_envelope(refused, ERR_ROADS_NOT_CONNECTED_AT_JUNCTION, 422)

    def test_only_the_road_holding_the_car_may_deliver_it(self, api: ApiClient):
        """CX handed the car over already, so CX can no longer deliver it.

        PRD: "On interchange capture, `delivering_road_id` equals the car's `current_handling_road_id` — otherwise `ERR_DELIVERING_ROAD_NOT_IN_CUSTODY`."

        Design: Corner/validations/interchange_capture_business_guards_rejected
        """
        world = _capture_guard_world(api)

        refused = api.create_interchange_event(
            f.delivery_event_payload(world.car, world.jct, world.cx, world.bn,
                                     DELIVERY_OUT_AT, 1100, "LOADED"),
            world.clerk(world.cx))
        assert_error_envelope(refused, ERR_DELIVERING_ROAD_NOT_IN_CUSTODY, 422)

    def test_a_bad_ordered_car_cannot_be_interchanged_at_all(self, api: ApiClient):
        """With the defect open the delivery is refused and the log keeps its one row.

        PRD: "An interchange delivery requires the car's `mechanical_status` to be neither `BAD_ORDER` nor `UNDER_REPAIR` — otherwise `ERR_CAR_BAD_ORDER_NOT_INTERCHANGEABLE`."

        Design: Corner/validations/interchange_capture_business_guards_rejected
        """
        world = _capture_guard_world(api)
        set_clock(api, "2026-08-25T00:00:00Z", world)
        validate_success(api.report_bad_order(
            world.car, f.bad_order_payload("2026-08-25T00:00:00Z"),
            world.clerk(world.bn)))

        refused = api.create_interchange_event(
            f.delivery_event_payload(world.car, world.jct, world.bn, world.cx,
                                     "2026-08-25T00:00:00Z", 1100, "LOADED"),
            world.clerk(world.bn))
        assert_error_envelope(refused, ERR_CAR_BAD_ORDER_NOT_INTERCHANGEABLE, 422)

        rows = validate_success(api.list_interchange_events(
            world.clerk(world.bn), params={"car_id": world.car}))
        rows = rows if isinstance(rows, list) else rows["items"]
        assert len(rows) == 1
        car = validate_success(api.get_car(world.car, world.owner(world.cx)))
        assert car["current_handling_road_id"] == world.bn
        assert car["mechanical_status"] == "BAD_ORDER"


BAND_FROM = "2026-08-25T00:00:00Z"
BAND_TO = "2026-08-26T00:00:00Z"
TWENTY_HOURS_ON = "2026-08-25T20:00:00Z"
EMBARGO_FROM = "2026-08-01T00:00:00Z"
EMBARGO_TO = "2026-08-02T00:00:00Z"
SIXTY_DAYS_AND_ONE_SECOND = "2026-10-27T00:00:01Z"


def _claims_on(api, world, movement_id):
    """Every reclaim claim standing against one segment."""
    rows = validate_success(api.list_reclaim_claims(
        world.accountant(world.bn), params={"movement_id": movement_id}))
    return rows if isinstance(rows, list) else rows["items"]


class TestReclaimFilingGuards:
    """The window, its evidence and the filing deadline are each policed apart."""

    def test_a_window_running_backwards_is_not_an_interval(self, api: ApiClient):
        """window_from after window_to is 422 ERR_INVALID_INTERVAL and files nothing.

        PRD: "Every supplied interval is strictly ordered — `window_from` strictly before `window_to`, `effective_from` strictly before `effective_to`, `issued_at` strictly before `due_at` — otherwise `ERR_INVALID_INTERVAL`."

        Design: Corner/validations/reclaim_filing_guard_rules_rejected
        """
        world, movement = bad_order_band_world(api)
        assert_instant_equals(movement["bad_order_from"], BAND_FROM, "bad_order_from")

        refused = api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], "BAD_ORDER", BAND_TO, BAND_FROM,
                              movement["version"]),
            world.accountant(world.bn))
        assert_error_envelope(refused, ERR_INVALID_INTERVAL, 422)

        assert _claims_on(api, world, movement["id"]) == []
        assert read_movement(api, world, movement["id"])["version"] == movement["version"]

    def test_twenty_claimed_hours_are_below_the_industry_minimum(self, api: ApiClient):
        """A 20.00-hour window is refused while the 24.00-hour window is filed.

        PRD: "`claimed_hours` must be at least 24 — exactly 24 hours is claimable, one minute less is `ERR_RECLAIM_WINDOW_TOO_SHORT`."

        Design: Corner/validations/reclaim_filing_guard_rules_rejected
        """
        world, movement = bad_order_band_world(api)

        refused = api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], "BAD_ORDER", BAND_FROM, TWENTY_HOURS_ON,
                              movement["version"]),
            world.accountant(world.bn))
        assert_error_envelope(refused, ERR_RECLAIM_WINDOW_TOO_SHORT, 422)
        assert _claims_on(api, world, movement["id"]) == []

        filed = file_reclaim(api, world, movement, "BAD_ORDER", BAND_FROM, BAND_TO)
        assert filed["status"] == "FILED"
        assert_hours(filed["claimed_hours"], 24.00, "claimed_hours")

    def test_each_ground_demands_the_evidence_that_belongs_to_it(self, api: ApiClient):
        """Three legal windows without their own evidence all report the same 422.

        PRD: "A reclaim filing is evidenced: `reason` `BAD_ORDER` requires the parent segment's `bad_order_from` to be non-null; `reason` `EMBARGO` requires `supporting_embargo_id`; `reason` `CUSTOMER_DETENTION` requires `detention_notified_at`."

        Design: Corner/validations/reclaim_filing_guard_rules_rejected
        """
        world, movement = closed_segment_world(api)
        assert movement["bad_order_from"] is None
        assert_money(movement["net_hire_cents"], 11464, "net_hire_cents")

        for reason in ("BAD_ORDER", "CUSTOMER_DETENTION", "EMBARGO"):
            refused = api.create_reclaim_claim(
                f.reclaim_payload(movement["id"], reason, BAND_FROM, BAND_TO,
                                  movement["version"]),
                world.accountant(world.bn))
            assert_error_envelope(refused, ERR_RECLAIM_EVIDENCE_MISSING, 422)

        assert _claims_on(api, world, movement["id"]) == []
        after = read_movement(api, world, movement["id"])
        assert_money(after["net_hire_cents"], 11464, "net_hire_cents")
        assert_money(after["reclaim_credit_cents"], 0, "reclaim_credit_cents")

    def test_an_embargo_that_expired_weeks_earlier_covers_no_window(self, api: ApiClient):
        """A cited order effective 08-01 to 08-02 cannot support a window in 08-25.

        PRD: "An embargo-grounded claim additionally requires the cited order to genuinely cover the claim: the order's `car_type_id` must equal the car's `car_type_id`, its `junction_id` must be the junction of either the event that opened the segment or the event that closed it, and the claimed window must lie inside the order's effective coverage as described above; failure is `ERR_EMBARGO_DOES_NOT_COVER_WINDOW`."

        Design: Corner/validations/reclaim_filing_guard_rules_rejected
        """
        world, movement = closed_segment_world(api)
        order = issue_embargo(api, world, world.bn, world.jct, EMBARGO_FROM,
                              EMBARGO_TO, car_type_id=world.xm)
        assert order["status"] == "ACTIVE"

        refused = api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], "EMBARGO", BAND_FROM, BAND_TO,
                              movement["version"], supporting_embargo_id=order["id"]),
            world.accountant(world.bn))
        assert_error_envelope(refused, ERR_EMBARGO_DOES_NOT_COVER_WINDOW, 422)
        assert _claims_on(api, world, movement["id"]) == []

    def test_one_second_past_sixty_days_closes_the_filing_window(self, api: ApiClient):
        """The same evidenced claim is refused once the clock passes end_at plus 60 days.

        PRD: "The claim must be filed within 60 days of the segment's `end_at`, measured against the logical clock and inclusive of the boundary, otherwise `ERR_RECLAIM_FILING_WINDOW_EXPIRED`."

        Design: Corner/validations/reclaim_filing_guard_rules_rejected
        """
        world, movement = bad_order_band_world(api)
        assert_instant_equals(movement["end_at"], RETURN_AT_11464, "end_at")

        set_clock(api, SIXTY_DAYS_AND_ONE_SECOND, world)
        refused = api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], "BAD_ORDER", BAND_FROM, BAND_TO,
                              movement["version"]),
            world.accountant(world.bn))
        assert_error_envelope(refused, ERR_RECLAIM_FILING_WINDOW_EXPIRED, 422)
        assert _claims_on(api, world, movement["id"]) == []


DEFECT_AT = "2026-08-25T00:00:00Z"
BEFORE_EVERY_SEGMENT = "2026-07-15T00:00:00Z"
PREAUTH_REFERENCE = "PA-2026-000714"


def _bills_on(api, world, car_id):
    """Every repair bill drafted against one car."""
    rows = validate_success(api.list_repair_bills(
        world.repair(world.bn), params={"car_id": car_id}))
    return rows if isinstance(rows, list) else rows["items"]


class TestRepairBillingGuards:
    """Two of these gates read a field of the bill rather than its state."""

    def test_a_serviceable_car_has_nothing_to_repair(self, api: ApiClient):
        """A bill drafted against a SERVICEABLE car is 422 and nothing is drafted.

        PRD: "Drafting a repair bill requires the car to be `BAD_ORDER`; releasing a car to service requires it to be `BAD_ORDER` or `UNDER_REPAIR` — otherwise `ERR_CAR_NOT_BAD_ORDERED`."

        Design: Corner/validations/repair_billing_guard_rules_rejected
        """
        world, car = bad_order_on_bn_world(api)
        serviceable = register_car(api, "CX 100002", world.xm, world.cx, world=world)

        refused = api.create_repair_bill(
            f.repair_bill_payload(serviceable, world.bn, "R-114", "NORMAL_WEAR",
                                  DEFECT_AT, 2.0, 1000),
            world.repair(world.bn))
        assert_error_envelope(refused, ERR_CAR_NOT_BAD_ORDERED, 422)

        assert _bills_on(api, world, serviceable) == []
        untouched = validate_success(api.get_car(serviceable, world.owner(world.cx)))
        assert untouched["mechanical_status"] == "SERVICEABLE"

    def test_a_handling_damage_defect_outside_every_segment_names_no_road(self, api: ApiClient):
        """An instant before the car's first segment refuses the submission at 422.

        PRD: "If no segment covers the instant, the handling-line rule has no road to name and the submission is refused with `ERR_NO_CUSTODY_AT_DEFECT_TIME`."

        Design: Corner/validations/repair_billing_guard_rules_rejected
        """
        world, car = bad_order_on_bn_world(api)
        draft = draft_repair_bill(api, world, world.car, world.bn, "HANDLING_DAMAGE",
                                  BEFORE_EVERY_SEGMENT, 2.0, 1000)
        assert draft["status"] == "DRAFT"
        assert draft["responsible_road_id"] is None

        refused = api.submit_repair_bill(draft["id"], {}, world.repair(world.bn))
        assert_error_envelope(refused, ERR_NO_CUSTODY_AT_DEFECT_TIME, 422)

        stored = validate_success(api.get_repair_bill(draft["id"],
                                                     world.repair(world.bn)))
        assert stored["status"] == "DRAFT"
        assert stored["responsible_road_id"] is None
        assert stored["responsibility_rule_applied"] is None
        assert stored["total_cents"] is None

    def test_accepting_a_draft_reports_the_dedicated_repair_gate(self, api: ApiClient):
        """Accept on a DRAFT bill is 409 ERR_REPAIR_BILL_NOT_SUBMITTED, not the generic gate.

        PRD: "Repair-bill accept and counter-bill require the bill to be `SUBMITTED` — otherwise `ERR_REPAIR_BILL_NOT_SUBMITTED`."

        Design: Corner/validations/repair_billing_guard_rules_rejected
        """
        world, car = bad_order_on_bn_world(api)
        draft = draft_repair_bill(api, world, world.car, world.bn, "NORMAL_WEAR",
                                  DEFECT_AT, 2.0, 1000)

        refused = api.accept_repair_bill(draft["id"], {}, world.repair(world.bn))
        body = assert_error_envelope(refused, ERR_REPAIR_BILL_NOT_SUBMITTED, 409)
        assert body["error_id"] != ERR_INVALID_STATE_TRANSITION

        stored = validate_success(api.get_repair_bill(draft["id"],
                                                     world.repair(world.bn)))
        assert stored["status"] == "DRAFT"
        assert stored["accepted_at"] is None

    def test_the_preauthorisation_gate_reads_the_fee_inclusive_total(self, api: ApiClient):
        """A subtotal of 145000 still needs pre-authorisation because the total is 155875.

        PRD: "The gate reads the fee-inclusive total, so a bill can cross the threshold on the handling fee alone."

        Design: Corner/validations/repair_billing_guard_rules_rejected
        """
        world, car = bad_order_on_bn_world(api)
        bare = draft_repair_bill(api, world, world.car, world.bn, "NORMAL_WEAR",
                                 DEFECT_AT, 14.0, 12000, defect_code="R-220")

        refused = api.submit_repair_bill(bare["id"], {}, world.repair(world.bn))
        assert_error_envelope(refused, ERR_REPAIR_PREAUTH_REQUIRED, 422)
        still_draft = validate_success(api.get_repair_bill(bare["id"],
                                                          world.repair(world.bn)))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["submitted_at"] is None

        _, priced = submitted_repair_bill(
            api, world, world.car, world.bn, "NORMAL_WEAR", DEFECT_AT, 14.0, 12000,
            pre_authorization_reference=PREAUTH_REFERENCE)
        assert priced["responsible_road_id"] == world.cx
        assert_money(priced["labor_cents"], 133000, "labor_cents")
        assert_money(priced["subtotal_cents"], 145000, "subtotal_cents")
        assert priced["subtotal_cents"] < 150000
        assert_money(priced["handling_fee_cents"], 10875, "handling_fee_cents")
        assert_money(priced["total_cents"], 155875, "total_cents")
        assert priced["total_cents"] > 150000

    def test_a_counter_at_zero_or_at_the_standing_total_is_no_counter(self, api: ApiClient):
        """Both 0 and the standing 48644 are refused and the round counter stays at 0.

        PRD: "The counter must satisfy `0 < counter_total_cents < total_cents` as the bill currently stands — an absent, zero, negative, or at-or-above-standing-total figure is not a counter-offer at all and is `ERR_REPAIR_AMOUNT_INVALID` — and `counter_bill_round` must be strictly less than 2, so the second counter is the last one accepted and a third attempt is `ERR_COUNTER_BILL_ROUNDS_EXHAUSTED`."

        Design: Corner/validations/repair_billing_guard_rules_rejected
        """
        world, car = bad_order_on_bn_world(api)
        _, bill = submitted_repair_bill(api, world, world.car, world.bn, "NORMAL_WEAR",
                                        DEFECT_AT, 3.5, 12000)
        assert_money(bill["total_cents"], 48644, "total_cents")
        assert bill["counter_bill_round"] == 0

        for amount in (48644, 0):
            refused = api.counter_repair_bill(
                bill["id"], {"counter_total_cents": amount,
                             "counter_note": "Not a counter-offer at all"},
                world.repair(world.cx))
            assert_error_envelope(refused, ERR_REPAIR_AMOUNT_INVALID, 422)

        stored = validate_success(api.get_repair_bill(bill["id"],
                                                      world.repair(world.bn)))
        assert stored["counter_bill_round"] == 0
        assert_money(stored["total_cents"], 48644, "total_cents")
        assert stored["last_counter_at"] is None


DISPUTE_DEADLINE = "2026-10-01T00:00:00Z"
PAST_THE_DISPUTE_DEADLINE = "2026-10-01T00:00:01Z"


def _disputes_on(api, world, cycle_id):
    """Every dispute standing against one cycle."""
    rows = validate_success(api.list_disputes(
        world.accountant(world.bn), params={"settlement_cycle_id": cycle_id}))
    return rows if isinstance(rows, list) else rows["items"]


class TestDisputeFilingGuards:
    """The subject, the cycle state and the deadline are three separate gates."""

    def test_a_merely_computed_cycle_has_not_been_served_yet(self, api: ApiClient):
        """Filing before the exchange is 409, and the identical filing after it is 201.

        PRD: "Filing a dispute requires the parent cycle to be `EXCHANGED` — otherwise `ERR_CYCLE_NOT_EXCHANGED`."

        Design: Corner/validations/dispute_filing_guard_rules_rejected
        """
        world, movement = closed_segment_world(api)
        cycle, computed = computed_cycle(api, world)
        assert computed["status"] == "COMPUTED"

        refused = api.create_dispute(
            f.dispute_payload(cycle["id"], "MILEAGE_DISCREPANCY", 5000,
                              computed["version"], movement_id=movement["id"]),
            world.accountant(world.bn))
        assert_error_envelope(refused, ERR_CYCLE_NOT_EXCHANGED, 409)
        assert _disputes_on(api, world, cycle["id"]) == []

        exchanged = validate_success(api.exchange_settlement_cycle(
            cycle["id"], {}, world.accountant(world.cx)))
        filed = validate_success(api.create_dispute(
            f.dispute_payload(cycle["id"], "MILEAGE_DISCREPANCY", 5000,
                              exchanged["version"], movement_id=movement["id"]),
            world.accountant(world.bn)), 201)

        assert filed["status"] == "OPEN"
        assert filed["round_number"] == 0
        assert_money(filed["subject_net_at_filing_cents"], 11464,
                     "subject_net_at_filing_cents")
        assert filed["filed_by_road_id"] == world.bn
        assert filed["respondent_road_id"] == world.cx

    def test_a_filing_that_names_no_subject_leaves_it_ambiguous(self, api: ApiClient):
        """Omitting both subject keys is 422 ERR_DISPUTE_SUBJECT_AMBIGUOUS.

        PRD: "A dispute filing supplies exactly one of `movement_id` and `repair_bill_id` — supplying both, or neither, is `ERR_DISPUTE_SUBJECT_AMBIGUOUS`."

        Design: Corner/validations/dispute_filing_guard_rules_rejected
        """
        world, movement = closed_segment_world(api)
        cycle, computed, exchanged = exchanged_cycle(api, world)

        refused = api.create_dispute(
            f.dispute_payload(cycle["id"], "MILEAGE_DISCREPANCY", 5000,
                              exchanged["version"]),
            world.accountant(world.bn))
        assert_error_envelope(refused, ERR_DISPUTE_SUBJECT_AMBIGUOUS, 422)

        assert _disputes_on(api, world, cycle["id"]) == []
        assert read_cycle(api, world, cycle["id"])["version"] == exchanged["version"]

    def test_a_counter_above_the_disputed_amount_is_out_of_range(self, api: ApiClient):
        """The respondent offering 6000 against a 5000 dispute is 422 and moves nothing.

        PRD: "The permitted range depends on the direction of the move: from `OPEN`, `counter_amount_cents` must be at least 0 and at most `disputed_amount_cents`; from `COUNTERED`, it must be at least the standing `counter_amount_cents` and at most `disputed_amount_cents`, so the filer may only walk the offer up, never back down."

        Design: Corner/validations/dispute_filing_guard_rules_rejected
        """
        world, movement = closed_segment_world(api)
        cycle, computed, exchanged = exchanged_cycle(api, world)
        dispute = file_dispute(api, world, exchanged, "MILEAGE_DISCREPANCY", 5000,
                               movement_id=movement["id"])

        refused = api.counter_dispute(dispute["id"], {"counter_amount_cents": 6000},
                                     world.accountant(world.cx))
        assert_error_envelope(refused, ERR_COUNTER_AMOUNT_OUT_OF_RANGE, 422)

        stored = validate_success(api.get_dispute(dispute["id"],
                                                 world.accountant(world.bn)))
        assert stored["status"] == "OPEN"
        assert stored["round_number"] == 0
        assert stored["counter_amount_cents"] is None

    def test_one_second_past_the_deadline_closes_the_dispute_window(self, api: ApiClient):
        """The late filing reports the window, never the duplicate it would also be.

        PRD: "The filing must arrive at or before `dispute_deadline_at`, inclusive, otherwise `ERR_DISPUTE_WINDOW_EXPIRED`."

        Design: Corner/validations/dispute_filing_guard_rules_rejected
        """
        world, movement = closed_segment_world(api)
        cycle, computed, exchanged = exchanged_cycle(api, world)
        assert_instant_equals(exchanged["dispute_deadline_at"], DISPUTE_DEADLINE,
                              "dispute_deadline_at")
        standing = file_dispute(api, world, exchanged, "MILEAGE_DISCREPANCY", 5000,
                               movement_id=movement["id"])
        assert standing["status"] == "OPEN"

        set_clock(api, PAST_THE_DISPUTE_DEADLINE, world)
        fresh = read_cycle(api, world, cycle["id"])
        refused = api.create_dispute(
            f.dispute_payload(cycle["id"], "HIRE_RATE_MISAPPLIED", 1000,
                              fresh["version"], movement_id=movement["id"]),
            world.accountant(world.bn))
        body = assert_error_envelope(refused, ERR_DISPUTE_WINDOW_EXPIRED, 422)
        assert body["error_id"] != ERR_DUPLICATE_RESOURCE
        assert len(_disputes_on(api, world, cycle["id"])) == 1


CONFIRM_DEADLINE = "2026-08-27T00:00:00Z"
PAST_THE_CONFIRM_DEADLINE = "2026-08-27T00:00:01Z"
MISSED_EVENT_AT = "2026-08-25T00:00:00Z"


def _one_delivery_world(api):
    """A CX-owned car handed to BN at JCT-CHI on 08-24, the clock left there."""
    world = standard_world(api)
    event = deliver_out(api, world, world.car, DELIVERY_OUT_AT, 1000)
    return world, event


class TestCorrectionRequestGuards:
    """The type-target pairing, the confirming road and the window are all policed."""

    def test_a_delivery_event_is_not_voidable_this_way(self, api: ApiClient):
        """ERRONEOUS_EVENT_VOID against a delivery is 422 and files nothing.

        PRD: "An `ERRONEOUS_EVENT_VOID` erases a rejection and requires a `target_event_id` naming a `RECORDED` event whose `event_type` is `INTERCHANGE_REJECTION` — no other event type is voidable this way."

        Design: Corner/validations/correction_request_guard_rules_rejected
        """
        world, event = _one_delivery_world(api)
        assert event["event_type"] == "INTERCHANGE_DELIVERY"

        refused = api.create_correction_request(
            f.erroneous_void_payload(world.car, world.jct, world.cx, event["id"]),
            world.clerk(world.bn))
        assert_error_envelope(refused, ERR_CORRECTION_TARGET_NOT_VOIDABLE, 422)

        rows = validate_success(api.list_correction_requests(
            world.clerk(world.bn), params={"car_id": world.car}))
        rows = rows if isinstance(rows, list) else rows["items"]
        assert rows == []

    def test_the_filing_road_can_never_confirm_its_own_request(self, api: ApiClient):
        """BN confirming the request BN filed is 403 and leaves it FILED.

        PRD: "Only the `counterparty_road_id` may respond; the road that filed a correction can never confirm or reject its own filing, which is `ERR_CORRECTION_CONFIRM_NOT_COUNTERPARTY`."

        Design: Corner/validations/correction_request_guard_rules_rejected
        """
        world, event = _one_delivery_world(api)
        filed = validate_success(api.create_correction_request(
            f.missed_event_payload(world.car, world.jct, world.cx, "FILER_DELIVERS",
                                   MISSED_EVENT_AT, 1100,
                                   filing_note="Handoff at Chicago never keyed"),
            world.clerk(world.bn)), 201)
        assert filed["status"] == "FILED"
        assert filed["filed_by_road_id"] == world.bn
        assert_instant_equals(filed["confirm_deadline_at"], CONFIRM_DEADLINE,
                              "confirm_deadline_at")

        refused = api.confirm_correction_request(filed["id"], {},
                                                world.clerk(world.bn))
        assert_error_envelope(refused, ERR_CORRECTION_CONFIRM_NOT_COUNTERPARTY, 403)

        stored = validate_success(api.get_correction_request(filed["id"],
                                                            world.clerk(world.bn)))
        assert stored["status"] == "FILED"
        assert stored["confirmed_at"] is None

    def test_applying_a_filed_request_reports_the_dedicated_gate(self, api: ApiClient):
        """Apply before any confirmation is 409 ERR_CORRECTION_NOT_CONFIRMED.

        PRD: "Correction apply requires the request to be `CONFIRMED` — otherwise `ERR_CORRECTION_NOT_CONFIRMED`."

        Design: Corner/validations/correction_request_guard_rules_rejected
        """
        world, event = _one_delivery_world(api)
        filed = validate_success(api.create_correction_request(
            f.missed_event_payload(world.car, world.jct, world.cx, "FILER_DELIVERS",
                                   MISSED_EVENT_AT, 1100),
            world.clerk(world.bn)), 201)

        refused = api.apply_correction_request(filed["id"], {}, admin_headers())
        body = assert_error_envelope(refused, ERR_CORRECTION_NOT_CONFIRMED, 409)
        assert body["error_id"] != ERR_INVALID_STATE_TRANSITION

        stored = validate_success(api.get_correction_request(filed["id"],
                                                            world.clerk(world.bn)))
        assert stored["status"] == "FILED"
        assert stored["resulting_event_id"] is None
        rows = validate_success(api.list_interchange_events(
            world.clerk(world.bn), params={"car_id": world.car}))
        rows = rows if isinstance(rows, list) else rows["items"]
        assert len(rows) == 1

    def test_the_lapsed_window_outranks_the_question_of_who_may_confirm(self, api: ApiClient):
        """One second late even the correct counterparty is told the window closed.

        PRD: "Confirming takes the request `FILED → CONFIRMED`, stamps `confirmed_at` and may carry a `confirm_note`; it must arrive at or before `confirm_deadline_at`, and a confirmation at exactly that instant is still accepted while one instant later is `ERR_CORRECTION_CONFIRM_WINDOW_EXPIRED`."

        Design: Corner/validations/correction_request_guard_rules_rejected
        """
        world, event = _one_delivery_world(api)
        filed = validate_success(api.create_correction_request(
            f.missed_event_payload(world.car, world.jct, world.cx, "FILER_DELIVERS",
                                   MISSED_EVENT_AT, 1100),
            world.clerk(world.bn)), 201)
        assert_instant_equals(filed["confirm_deadline_at"], CONFIRM_DEADLINE,
                              "confirm_deadline_at")

        set_clock(api, PAST_THE_CONFIRM_DEADLINE, world)
        refused = api.confirm_correction_request(filed["id"], {},
                                                world.clerk(world.cx))
        body = assert_error_envelope(refused, ERR_CORRECTION_CONFIRM_WINDOW_EXPIRED, 422)
        assert body["error_id"] != ERR_CORRECTION_CONFIRM_NOT_COUNTERPARTY

        stored = validate_success(api.get_correction_request(filed["id"],
                                                            world.clerk(world.bn)))
        assert stored["status"] == "FILED"
        assert stored["confirmed_at"] is None


REOPEN_DEADLINE = "2026-10-01T00:00:00Z"
INSIDE_THE_REOPEN_WINDOW = "2026-09-15T00:00:00Z"
PAST_THE_REOPEN_DEADLINE = "2026-10-01T00:00:01Z"


class TestSettlementReopenAndArchiveWindows:
    """Reopen and archive are gated on opposite sides of one instant."""

    def test_archiving_while_the_cycle_can_still_be_reopened_is_refused(self, api: ApiClient):
        """An archive two weeks before the deadline is 422 and the cycle stays SETTLED.

        PRD: "Finally the admin archives a settled cycle, `SETTLED → ARCHIVED`, once the reopen window has *fully* elapsed — the logical clock must be strictly after `reopen_deadline_at`, and archiving while the cycle can still be reopened is `ERR_REOPEN_WINDOW_STILL_OPEN`."

        Design: Corner/validations/settlement_reopen_and_archive_window_guards_rejected
        """
        world, movement = closed_segment_world(api)
        cycle, computed, exchanged, settled = settled_cycle(api, world)
        assert_instant_equals(settled["reopen_deadline_at"], REOPEN_DEADLINE,
                              "reopen_deadline_at")

        set_clock(api, INSIDE_THE_REOPEN_WINDOW, world)
        refused = api.archive_settlement_cycle(cycle["id"], {}, admin_headers())
        assert_error_envelope(refused, ERR_REOPEN_WINDOW_STILL_OPEN, 422)

        stored = read_cycle(api, world, cycle["id"])
        assert stored["status"] == "SETTLED"
        assert stored["archived_at"] is None

    def test_reopening_one_second_after_the_deadline_is_refused(self, api: ApiClient):
        """A reopen at deadline plus one second is 422 and no reopen is counted.

        PRD: "A `ClearinghouseAdmin` may reopen a settled cycle at or before `reopen_deadline_at`, taking it `SETTLED → REOPENED` with a supplied `reopen_reason`, stamping `reopened_at`, incrementing `reopen_count`, reversing the `SETTLEMENT_PAYMENT` with a `CORRECTION_ADJUSTMENT` entry of the opposite amount and restoring the payer's exposure; after the deadline it is `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Corner/validations/settlement_reopen_and_archive_window_guards_rejected
        """
        world, movement = closed_segment_world(api)
        cycle, computed, exchanged, settled = settled_cycle(api, world)

        set_clock(api, PAST_THE_REOPEN_DEADLINE, world)
        refused = api.reopen_settlement_cycle(
            cycle["id"], {"reopen_reason": "Late mileage correction from the owner road"},
            admin_headers())
        assert_error_envelope(refused, ERR_REOPEN_WINDOW_EXPIRED, 422)

        stored = read_cycle(api, world, cycle["id"])
        assert stored["status"] == "SETTLED"
        assert stored["reopen_count"] == 0
        assert stored["reopened_at"] is None

    def test_the_archived_freeze_reaches_the_member_segment(self, api: ApiClient):
        """A fully evidenced reclaim on an archived cycle's member line is 409.

        PRD: "Archiving stamps `archived_at` and freezes everything: every later write touching a member segment, reclaim, repair bill or ledger entry is refused with `ERR_CYCLE_ARCHIVED_IMMUTABLE`."

        Design: Corner/validations/settlement_reopen_and_archive_window_guards_rejected
        """
        world, movement = bad_order_band_world(api)
        cycle, computed, exchanged, settled = settled_cycle(api, world)
        assert_money(settled["net_settlement_cents"], 11407, "net_settlement_cents")

        set_clock(api, PAST_THE_REOPEN_DEADLINE, world)
        archived = validate_success(api.archive_settlement_cycle(cycle["id"], {},
                                                                admin_headers()))
        assert archived["status"] == "ARCHIVED"
        assert_instant_equals(archived["archived_at"], PAST_THE_REOPEN_DEADLINE,
                              "archived_at")

        member = read_movement(api, world, movement["id"])
        assert member["settlement_cycle_id"] == cycle["id"]
        assert member["status"] == "CLOSED"
        assert member["reclaim_locked"] is False

        refused = api.create_reclaim_claim(
            f.reclaim_payload(member["id"], "BAD_ORDER", BAND_FROM, BAND_TO,
                              member["version"]),
            world.accountant(world.bn))
        body = assert_error_envelope(refused, ERR_CYCLE_ARCHIVED_IMMUTABLE, 409)
        assert body["error_id"] != ERR_RECLAIM_FILING_WINDOW_EXPIRED

        assert _claims_on(api, world, member["id"]) == []
        assert_money(read_movement(api, world, member["id"])["net_hire_cents"], 11464,
                     "net_hire_cents")
        assert_money(read_cycle(api, world, cycle["id"])["net_settlement_cents"], 11407,
                     "net_settlement_cents")


class TestDeclaredUniquenessKeys:
    """Four keys are single-column and global; the cycle's key is an ordered triple."""

    def test_each_single_column_key_refuses_its_second_row(self, api: ApiClient):
        """A repeated mark, type code, junction code and car mark are all 409.

        PRD: "Declared uniqueness holds — otherwise `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/validations/duplicate_uniqueness_keys_rejected
        """
        world = standard_world(api)

        mark = api.create_railroad(
            f.railroad_payload("BN", "Bear Northern Railway Company"), admin_headers())
        assert_error_envelope(mark, ERR_DUPLICATE_RESOURCE, 409)

        code = api.create_car_type(f.car_type_payload(description="Box car, cushioned"),
                                  admin_headers())
        assert_error_envelope(code, ERR_DUPLICATE_RESOURCE, 409)

        junction = api.create_junction(
            f.junction_payload("JCT-CHI", world.bn, world.cx,
                               name="Chicago Interchange South"), admin_headers())
        assert_error_envelope(junction, ERR_DUPLICATE_RESOURCE, 409)

        car = api.create_car(f.car_payload("CX 100001", world.xm, world.cx),
                            world.owner(world.cx))
        assert_error_envelope(car, ERR_DUPLICATE_RESOURCE, 409)

        rows, meta = validate_paginated(api.list_railroads(admin_headers(),
                                                         params={"reporting_mark": "BN"}))
        assert meta["total_count"] == 1
        assert len(rows) == 1

    def test_the_cycle_key_is_the_ordered_payer_payee_month_triple(self, api: ApiClient):
        """A second BN-pays-CX August cycle is 409 while CX-pays-BN August is a new row.

        PRD: "The unique keys are a railroad's `reporting_mark`, a car type's `car_type_code`, a junction's `junction_code`, a car's `car_mark`, the triple of `payer_road_id`, `payee_road_id` and `period_month` on a settlement cycle, and at most one non-terminal dispute per cycle-and-subject pair."

        Design: Corner/validations/duplicate_uniqueness_keys_rejected
        """
        world = standard_world(api)
        first = open_cycle(api, world)

        duplicate = api.create_settlement_cycle(
            f.settlement_cycle_payload(world.bn, world.cx, AUGUST_MONTH),
            world.accountant(world.cx))
        assert_error_envelope(duplicate, ERR_DUPLICATE_RESOURCE, 409)

        reverse = validate_success(api.create_settlement_cycle(
            f.settlement_cycle_payload(world.cx, world.bn, AUGUST_MONTH),
            world.accountant(world.cx)), 201)
        assert reverse["id"] != first["id"]
        assert reverse["payer_road_id"] == world.cx
        assert reverse["payee_road_id"] == world.bn
        assert reverse["period_month"] == AUGUST_MONTH
        assert reverse["status"] == "OPEN"


class TestPartyScopingOnASegment:
    """The party set of a segment is its handling road and its owner road, plus the clearinghouse."""

    def test_a_third_road_is_refused_where_both_parties_and_the_admin_read(self, api: ApiClient):
        """NS gets 403 on the row BN, CX and the clearinghouse all read at 200.

        PRD: "A road is a party to a hire segment when it is that segment's `handling_road_id` or its `owner_road_id`; to a settlement cycle when it is the cycle's `payer_road_id` or `payee_road_id`; to a reclaim claim, a dispute, a repair bill or a correction request when it is one of the two railroads named on that row; to a car when it is the car's owner or its current handling road; and to a ledger entry when it is that entry's `debit_road_id` or `credit_road_id`."

        Design: Corner/validations/non_party_railroad_cannot_read_a_foreign_movement
        """
        world = standard_world(api, extra_roads=("NS",))
        world, movement = closed_segment_world(api, world=world)
        assert movement["handling_road_id"] == world.bn
        assert movement["owner_road_id"] == world.cx

        refused = api.get_movement(movement["id"], world.accountant(world.ns))
        body = assert_error_envelope(refused, ERR_NOT_A_PARTY_TO_RESOURCE, 403)
        assert body["error_id"] != ERR_MOVEMENT_NOT_FOUND

        for reader in (world.accountant(world.bn), world.accountant(world.cx),
                       admin_headers()):
            seen = validate_success(api.get_movement(movement["id"], reader))
            assert seen["id"] == movement["id"]
            assert_money(seen["gross_hire_cents"], 11464, "gross_hire_cents")


TIGHT_CREDIT_LIMIT_CENTS = 5000


def _tight_limit_world(api):
    """The standard two-road world with BN admitted on a 5000-cent credit limit."""
    world = World(api)
    set_clock(api, BOOTSTRAP_CLOCK, world)
    register_railroad(api, "BN", world,
                      per_diem_credit_limit_cents=TIGHT_CREDIT_LIMIT_CENTS)
    register_railroad(api, "CX", world)
    register_car_type(api, world, payload=f.car_type_payload())
    register_junction(api, "JCT-CHI", world.cx, world.bn, world)
    register_car(api, "CX 100001", world.xm, world.cx, world=world)
    return closed_segment_world(api, world=world)


class TestPayerCreditLimitGate:
    """The only 402 in the catalogue fires after the arithmetic and rolls it back."""

    def test_a_compute_that_would_drive_headroom_negative_is_refused(self, api: ApiClient):
        """An 11464 statement against a 5000 limit is 402 and stores nothing.

        PRD: "`credit_headroom_cents` is `per_diem_credit_limit_cents` minus the exposure, and a statement compute that would drive headroom negative is refused with `ERR_PER_DIEM_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/compute_breaching_the_payer_credit_limit_returns_402
        """
        world, movement = _tight_limit_world(api)
        assert_money(movement["net_hire_cents"], 11464, "net_hire_cents")
        cycle = open_cycle(api, world)
        assert cycle["status"] == "OPEN"

        refused = api.compute_settlement_cycle(cycle["id"], {},
                                              world.accountant(world.cx))
        assert_error_envelope(refused, ERR_PER_DIEM_CREDIT_LIMIT_EXCEEDED, 402)

        after = read_cycle(api, world, cycle["id"])
        assert after["status"] == "OPEN"
        assert after["movement_line_count"] == 0
        assert_money(after["gross_hire_cents"], 0, "gross_hire_cents")
        assert_money(after["pre_fee_net_cents"], 0, "pre_fee_net_cents")
        assert_money(after["net_settlement_cents"], 0, "net_settlement_cents")
        assert after["computed_at"] is None

        still_free = read_movement(api, world, movement["id"])
        assert still_free["settlement_cycle_id"] is None
        assert_money(still_free["net_hire_cents"], 11464, "net_hire_cents")


EMBARGO_WINDOW_FROM = "2026-08-20T00:00:00Z"
EMBARGO_WINDOW_TO = "2026-08-22T00:00:00Z"


class TestEmbargoIssuingRoad:
    """One rule fails two independent ways: the wrong name and the wrong junction."""

    def test_a_road_may_not_embargo_in_another_roads_name(self, api: ApiClient):
        """CX filing an order in BN's name is 422 and files nothing.

        PRD: "On an embargo filing, `issuing_road_id` equals the acting railroad **and** is one of the junction's two roads — otherwise `ERR_EMBARGO_SELF_ISSUED`."

        Design: Corner/validations/embargo_issued_in_another_roads_name_rejected
        """
        world = standard_world(api, extra_roads=("NS",))

        in_bns_name = api.create_embargo_order(
            f.embargo_payload(world.bn, world.jct, EMBARGO_WINDOW_FROM,
                              EMBARGO_WINDOW_TO, reason="Filed by CX in BN's name",
                              car_type_id=world.xm),
            world.clerk(world.cx))
        assert_error_envelope(in_bns_name, ERR_EMBARGO_SELF_ISSUED, 422)

        not_at_junction = api.create_embargo_order(
            f.embargo_payload(world.ns, world.jct, EMBARGO_WINDOW_FROM,
                              EMBARGO_WINDOW_TO, reason="NS has no standing at Chicago",
                              car_type_id=world.xm),
            world.clerk(world.ns))
        assert_error_envelope(not_at_junction, ERR_EMBARGO_SELF_ISSUED, 422)

        rows, meta = validate_paginated(api.list_embargo_orders(
            admin_headers(), params={"junction_id": world.jct}))
        assert rows == []
        assert meta["total_count"] == 0

    def test_the_interval_test_also_guards_the_embargo_endpoint(self, api: ApiClient):
        """A backwards effective interval is 422 ERR_INVALID_INTERVAL.

        PRD: "The interval must be strictly ordered, with `effective_from` before `effective_to`, otherwise `ERR_INVALID_INTERVAL`."

        Design: Corner/validations/embargo_issued_in_another_roads_name_rejected
        """
        world = standard_world(api)

        backwards = api.create_embargo_order(
            f.embargo_payload(world.cx, world.jct, EMBARGO_WINDOW_TO,
                              EMBARGO_WINDOW_FROM, reason="Backwards interval",
                              car_type_id=world.xm),
            world.clerk(world.cx))
        assert_error_envelope(backwards, ERR_INVALID_INTERVAL, 422)

        forwards = issue_embargo(api, world, world.cx, world.jct, EMBARGO_WINDOW_FROM,
                                 EMBARGO_WINDOW_TO, car_type_id=world.xm)
        assert forwards["status"] == "ACTIVE"
        assert forwards["issuing_road_id"] == world.cx

        rows, meta = validate_paginated(api.list_embargo_orders(
            admin_headers(), params={"junction_id": world.jct}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == forwards["id"]
