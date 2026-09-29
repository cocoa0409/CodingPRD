"""Admission-ladder validations: ranges, occupancy, schedules, deadlines and postures."""

from test_helpers import (
    ANALYST_DRAFTER,
    PLATFORM_ADMIN,
    VALET_OPS_MANAGER,
    ApiErrorId,
    api_client,
    assert_instants_equal,
    factories,
    fixtures,
    make_property_manager_headers,
    make_valet_headers,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------
# Rung 19: the unit range is derived from unit_count and is closed
# --------------------------------------------------------------------------
def test_a_resident_above_the_derived_unit_range_is_out_of_bounds():
    """unit_count 4 means doors 101 through 104, so 105 does not exist.

    PRD 2.5: "**Unit numbers in range.** Any unit number must lie inside the
    property's closed unit range, which runs from 101 through 100 plus `unit_count`
    — otherwise `ERR_UNIT_RANGE_OUT_OF_BOUNDS` (422). This covers a resident's
    `unit_number` at resident creation and both ends of a route's range at
    route-assignment creation."

    Design: Corner/validations/resident_unit_number_above_the_property_range_is_rejected
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)

    response = api_client.create_resident(
        prop["id"],
        factories.resident_payload(105, full_name="Rue Five", move_in_date="2026-08-01"),
        PLATFORM_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_UNIT_RANGE_OUT_OF_BOUNDS.value, 422)
    assert fixtures.list_residents({"property_id": prop["id"]}) == []


def test_a_resident_on_the_inclusive_upper_door_is_accepted():
    """104 is the last door of a four-door community, not one past it.

    PRD 2.5: "**Unit numbers in range.** Any unit number must lie inside the
    property's closed unit range, which runs from 101 through 100 plus `unit_count`
    — otherwise `ERR_UNIT_RANGE_OUT_OF_BOUNDS` (422)."

    Design: Corner/validations/resident_unit_number_at_the_upper_bound_is_accepted
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)

    resident = validate_success(
        api_client.create_resident(
            prop["id"],
            factories.resident_payload(
                104, full_name="Rio Four", move_in_date="2026-08-01"
            ),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert resident["unit_number"] == 104
    assert resident["status"] == "ACTIVE"
    assert resident["collections_status"] == "CURRENT"
    assert resident["fines_outstanding_cents"] == 0
    assert resident["fines_assessed_this_period_cents"] == 0


# --------------------------------------------------------------------------
# Rung 20: two closed ranges that share one door intersect
# --------------------------------------------------------------------------
def test_a_second_route_sharing_one_door_with_a_live_route_overlaps():
    """102 belongs to both 101-102 and 102-104, so the second dispatch collides.

    PRD 2.5: "**Route range overlap.** The requested closed unit range must not
    intersect the range of any route assignment of the same night whose `status` is
    `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS` or `COMPLETED` — otherwise
    `ERR_UNIT_RANGE_OVERLAP` (409). Applies to route-assignment creation."

    Design: Corner/validations/route_range_overlapping_a_live_route_returns_range_overlap
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge", unit_count=4, resident_units=()
    )
    valet_b = fixtures.create_eligible_contractor(legal_name="Bea Ryu")
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    route_a = fixtures.assign_route(night["id"], world["contractor"]["id"], 101, 102)
    live = fixtures.read_night(night["id"])

    response = api_client.create_route_assignment(
        night["id"],
        factories.route_payload(valet_b["id"], 102, 104, live["version"]),
        VALET_OPS_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_UNIT_RANGE_OVERLAP.value, 409)
    untouched = fixtures.read_route(route_a["id"])
    assert untouched["status"] == "ASSIGNED"
    assert untouched["unit_from"] == 101
    assert untouched["unit_to"] == 102
    assert untouched["unit_coverage_count"] == 2
    after = fixtures.read_night(night["id"])
    assert after["assigned_unit_coverage_count"] == 2
    assert after["version"] == live["version"], "the rejected write bumped nothing"


# --------------------------------------------------------------------------
# Rung 21: one active resident per door
# --------------------------------------------------------------------------
def test_a_second_active_resident_on_the_same_door_is_refused():
    """The door is occupied, which is a conflict rather than a shape error.

    PRD 2.5: "**Unit vacancy.** No other resident of the property whose `status` is
    `ACTIVE` may already occupy the requested `unit_number` — otherwise
    `ERR_UNIT_ALREADY_OCCUPIED` (409). Applies to resident creation."

    Design: Corner/validations/resident_on_an_occupied_unit_returns_unit_already_occupied
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    sitting = fixtures.create_resident(
        prop["id"], 101, full_name="Rosa One", move_in_date="2026-08-01"
    )

    response = api_client.create_resident(
        prop["id"],
        factories.resident_payload(101, full_name="Ravi Two", move_in_date="2026-09-01"),
        PLATFORM_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_UNIT_ALREADY_OCCUPIED.value, 409)
    rows = fixtures.list_residents({"property_id": prop["id"]})
    assert len(rows) == 1
    assert rows[0]["id"] == sitting["id"]
    assert rows[0]["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Rung 22: the door must be inside the walked range
# --------------------------------------------------------------------------
def test_scanning_a_door_outside_the_walked_range_is_refused():
    """The resident is on the right property but on a door this route does not walk.

    PRD 2.5: "**Unit inside the walked range.** The scanned resident's
    `unit_number` must lie inside the route's closed range — otherwise
    `ERR_UNIT_NOT_IN_ROUTE` (409). Applies to scan recording."

    Design: Corner/validations/scan_of_a_resident_outside_the_route_range_returns_unit_not_in_route
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101, 103),
        resident_kwargs={
            101: {"move_in_date": "2026-08-01"},
            103: {"move_in_date": "2026-08-01"},
        },
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    route = fixtures.assign_and_accept_route(
        night["id"], world["contractor"]["id"], 101, 102
    )

    response = api_client.record_scan(
        route["id"],
        factories.scan_payload(world["residents"][103]["id"], "SERVICED", "TRASH_BIN"),
        make_valet_headers(world["contractor"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNIT_NOT_IN_ROUTE.value, 409)
    after_route = fixtures.read_route(route["id"])
    assert after_route["status"] == "ACCEPTED"
    assert after_route["scan_count"] == 0
    after_night = fixtures.read_night(night["id"])
    assert after_night["verification_status"] == "SCHEDULED"
    assert after_night["scanned_door_count"] == 0


# --------------------------------------------------------------------------
# Rung 23: one scan per (route, resident) pair
# --------------------------------------------------------------------------
def test_re_scanning_the_same_door_on_one_route_is_a_duplicate():
    """A different scan_result does not make it a different scan.

    PRD 2.5: "**Scan uniqueness.** No scan may already exist for this combination
    of route assignment and resident — otherwise `ERR_DUPLICATE_SCAN` (409).
    Applies to scan recording."

    Design: Corner/validations/second_scan_of_the_same_resident_on_one_route_returns_duplicate_scan
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        service_date="2026-09-01",
    )
    resident_id = world["residents"][101]["id"]
    first = fixtures.record_scan(
        world["route"]["id"], world["contractor"]["id"], resident_id
    )

    response = api_client.record_scan(
        world["route"]["id"],
        factories.scan_payload(
            resident_id,
            "TAGGED_NOT_SERVICED",
            "RECYCLING_BIN",
            "RECYCLING_CONTAMINATION",
        ),
        make_valet_headers(world["contractor"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_SCAN.value, 409)
    assert fixtures.read_route(world["route"]["id"])["scan_count"] == 1
    assert fixtures.read_scan(first["id"])["tag_status"] == "NONE"
    assert fixtures.list_fines({"resident_id": resident_id}) == [], (
        "the rejected scan never reached the automatic fine route"
    )
    assert fixtures.read_resident(resident_id)["fines_outstanding_cents"] == 0


# --------------------------------------------------------------------------
# Rung 16: the night must fall on a day the contract covers
# --------------------------------------------------------------------------
def test_a_night_on_a_weekday_the_contract_does_not_cover_is_refused():
    """2026-09-04 is a Friday, and the contract only runs SUN through THU.

    PRD 2.5: "**Service date on schedule.** The night's `service_date` must fall on
    a weekday listed in the contract's `service_night_days` and inside the
    contract's closed effective period — otherwise
    `ERR_SERVICE_DATE_NOT_SCHEDULED` (422). Applies to service-night creation. A
    makeup night created by a shift reschedule is exempt from the weekday half of
    this rule only."

    Design: Corner/validations/night_on_a_weekday_outside_the_service_schedule_is_rejected
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(),
        with_contractor=False,
        contract={"service_night_days": ["SUN", "MON", "TUE", "WED", "THU"]},
    )

    response = api_client.create_service_night(
        world["contract"]["id"],
        factories.service_night_payload("2026-09-04"),
        VALET_OPS_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_SERVICE_DATE_NOT_SCHEDULED.value, 422)
    assert fixtures.list_nights({"contract_id": world["contract"]["id"]}) == []


# --------------------------------------------------------------------------
# Rung 17: the makeup date is validated before the cancel is applied
# --------------------------------------------------------------------------
def test_a_makeup_date_beyond_the_fourteen_day_window_is_refused_atomically():
    """2026-09-20 is nineteen days out, and the refusal leaves the night scheduled.

    PRD 2.5: "**Makeup date validity.** On a shift reschedule,
    `makeup_service_date` must be present, strictly later than the original
    `service_date`, no more than fourteen days after it, inside the contract's
    closed effective period, and not already occupied by a non-cancelled night of
    the same contract — otherwise `ERR_INVALID_MAKEUP_DATE` (422). Applies to
    service-night rescheduling."

    Design: Corner/validations/shift_makeup_beyond_the_makeup_window_returns_invalid_makeup_date
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge", unit_count=4, resident_units=(), with_contractor=False
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")

    response = api_client.reschedule_service_night(
        night["id"],
        factories.reschedule_payload("SHIFT", "2026-09-20", "storm week"),
        VALET_OPS_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_MAKEUP_DATE.value, 422)
    unchanged = fixtures.read_night(night["id"])
    assert unchanged["verification_status"] == "SCHEDULED"
    assert unchanged["reschedule_action"] is None
    assert unchanged["version"] == night["version"]
    assert fixtures.find_makeup_night(night["id"]) is None


# --------------------------------------------------------------------------
# Rung 18: escalation waits for the acknowledgement deadline
# --------------------------------------------------------------------------
def test_escalating_an_hour_before_the_jam_deadline_is_refused():
    """A jam reported at midnight is escalatable at 04:00, not at 03:00.

    PRD 2.5: "**Escalation window elapsed.** Escalation must be attempted at or
    after the incident's `ack_deadline_at` on the logical clock — otherwise
    `ERR_ESCALATION_WINDOW_NOT_ELAPSED` (409). Applies to incident escalation."

    PRD 3.7: "The **acknowledgement deadline** is stamped at filing time as
    `ack_deadline_at`, computed as `reported_at` advanced by the window belonging to
    the incident's type: four hours for a `JAM`, and a full twenty-four hours for an
    `OVERFLOW`."

    Design: Corner/validations/escalating_before_the_ack_deadline_returns_window_not_elapsed
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    incident = fixtures.report_incident(
        prop["id"], "JAM", "ram jammed on a mattress"
    )
    fixtures.set_clock("2026-09-01T03:00:00Z")

    response = api_client.escalate_incident(incident["id"], VALET_OPS_MANAGER)

    validate_error(response, ApiErrorId.ERR_ESCALATION_WINDOW_NOT_ELAPSED.value, 409)
    still_reported = fixtures.read_incident(incident["id"])
    assert_instants_equal(
        still_reported["ack_deadline_at"], "2026-09-01T04:00:00.000Z", "ack_deadline_at"
    )
    assert still_reported["status"] == "REPORTED"
    assert still_reported["escalated_at"] is None
    after = fixtures.read_property(prop["id"])
    assert after["escalation_level"] == 0
    assert after["status"] == "ONBOARDING"


# --------------------------------------------------------------------------
# Rung 25: a settled period cannot be redrafted
# --------------------------------------------------------------------------
def test_redrafting_a_period_that_is_already_issued_is_refused():
    """A still-DRAFT period may be superseded; an ISSUED one may not.

    PRD 2.5: "**Period not yet invoiced.** No statement of this contract whose
    `status` is `ISSUED` may already cover the requested `billing_period` —
    otherwise `ERR_PERIOD_ALREADY_INVOICED` (409). Applies to statement drafting."

    Design: Corner/validations/drafting_a_statement_for_an_issued_period_returns_period_already_invoiced
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        with_contractor=False,
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    fixtures.close_night(night["id"])
    first = fixtures.draft_statement(world["contract"]["id"], "2026-09")
    issued = fixtures.issue_statement(first["id"])
    assert issued["status"] == "ISSUED"
    contract_after_issue = fixtures.read_contract(world["contract"]["id"])

    response = api_client.create_statement(
        world["contract"]["id"],
        factories.statement_payload("2026-09", contract_after_issue["version"]),
        ANALYST_DRAFTER,
    )

    validate_error(response, ApiErrorId.ERR_PERIOD_ALREADY_INVOICED.value, 409)
    settled = fixtures.read_statement(first["id"])
    assert settled["status"] == "ISSUED"
    assert settled["variant"] == "FINAL"
    assert settled["superseded_statement_id"] is None
    rows = fixtures.list_statements(
        {"contract_id": world["contract"]["id"], "billing_period": "2026-09"}
    )
    assert len(rows) == 1
    contract_after_refusal = fixtures.read_contract(world["contract"]["id"])
    assert contract_after_refusal["last_invoiced_period"] == "2026-09"
    assert contract_after_refusal["version"] == contract_after_issue["version"]


# --------------------------------------------------------------------------
# Rung 27: a resident outside pass-through cannot be fined
# --------------------------------------------------------------------------
def test_a_manual_fine_against_an_opted_out_resident_is_refused():
    """The tag is still recorded; only the money is refused.

    PRD 2.5: "**Pass-through eligibility.** The resident must have
    `fee_passthrough_enabled` set to true; a resident excluded from pass-through
    cannot be fined — otherwise `ERR_PASSTHROUGH_DISABLED` (409). Applies to manual
    fine assessment."

    Design: Corner/validations/fining_a_passthrough_disabled_resident_returns_passthrough_disabled
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={
            101: {"move_in_date": "2026-08-01", "fee_passthrough_enabled": False}
        },
        service_date="2026-09-01",
    )
    resident_id = world["residents"][101]["id"]
    property_id = world["property"]["id"]
    scan = fixtures.record_scan(
        world["route"]["id"],
        world["contractor"]["id"],
        resident_id,
        scan_result="TAGGED_NOT_SERVICED",
        container_type="LOOSE_BAG",
        non_compliance_type="EARLY_SET_OUT",
    )
    assert scan["tag_status"] == "OPEN"

    response = api_client.assess_fine(
        scan["id"],
        factories.manual_fine_payload("second notice posted on the door"),
        make_property_manager_headers(property_id),
    )

    validate_error(response, ApiErrorId.ERR_PASSTHROUGH_DISABLED.value, 409)
    assert fixtures.read_scan(scan["id"])["tag_status"] == "OPEN"
    assert fixtures.list_fines({"resident_id": resident_id}) == []
    assert fixtures.read_resident(resident_id)["fines_outstanding_cents"] == 0
    assert fixtures.read_property(property_id)["pending_fine_revenue_cents"] == 0


# --------------------------------------------------------------------------
# Rung 9: the property's posture gates the service-delivery writes
# --------------------------------------------------------------------------
def test_dispatching_onto_a_suspended_community_is_refused_by_posture():
    """The night is fresh and its version is current; the community is not.

    PRD 2.5: "**Property posture.** The owning property must not be `SUSPENDED` or
    `TERMINATED` — otherwise `ERR_PROPERTY_SUSPENDED` (409). This gate guards
    exactly four service-delivery writes: creating a route assignment on a night,
    accepting a route, completing a route, and recording a scan."

    Design: Corner/validations/route_creation_on_a_suspended_property_returns_property_suspended
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge", unit_count=4, resident_units=()
    )
    first = fixtures.report_incident(world["property"]["id"], "JAM", "tower A jammed")
    second = fixtures.report_incident(world["property"]["id"], "JAM", "tower B stalled")
    fixtures.set_clock("2026-09-01T05:00:00Z")
    fixtures.escalate_incident(first["id"])
    fixtures.escalate_incident(second["id"])
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-02")

    response = api_client.create_route_assignment(
        night["id"],
        factories.route_payload(
            world["contractor"]["id"], 101, 104, night["version"]
        ),
        VALET_OPS_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_PROPERTY_SUSPENDED.value, 409)
    prop = fixtures.read_property(world["property"]["id"])
    assert prop["status"] == "SUSPENDED"
    assert prop["escalation_level"] == 2
    after = fixtures.read_night(night["id"])
    assert after["verification_status"] == "SCHEDULED"
    assert after["assigned_unit_coverage_count"] == 0
    assert after["version"] == night["version"]
    assert fixtures.list_routes({"service_night_id": night["id"]}) == []
