"""Diagnostic surveillance: the four-hop barrier-downgrade cascade; and
welfare inspections: empty-findings close, day-slot uniqueness, segregation
of duties on verification, and the overdue-deadline facility-suspension
cascade driven by the clock sweep.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    SUSPENSION_REASON_OVERDUE_CORRECTIVE_ACTION,
    advance_clock,
    api_client,
    create_inspection_in_corrective_action,
    create_registered_facility,
    create_scheduled_health_screen,
    create_scheduled_inspection,
    create_screen_result_entry,
    create_finding,
    find_allocation_in_order,
    find_inspection_in_facility,
    find_screen_in_room,
    find_shipment_in_order,
    make_inspector_headers,
    read_cohort,
    read_facility,
    read_order,
    read_room,
    report_inspection_findings,
    result_health_screen,
    setup_allocated_order,
    setup_scheduled_order,
    validate_error,
    verify_inspection,
)

_VET = TEST_USERS["veterinarian_headers"]
_INSPECTOR = TEST_USERS["inspector_headers"]


def _allocated_vf_order():
    """ALLOCATED 10M/10F order with a VF health floor on a VF cohort."""
    return setup_allocated_order(
        quantity_male=10, quantity_female=10,
        order_overrides={"min_health_status": "VF"},
    )


def test_positive_screen_quarantines_and_downgrades_room_and_cohort():
    """PRD Section 3.5: "if at least one positive entry names an agent on the
    room's `excluded_agents` list, the screen flips to `RESULTED_POSITIVE`".
    PRD Section 3.5: "Hop one hits the room: it transitions to `QUARANTINED`
    with `quarantined_at` set to the current logical clock, and its
    `barrier_level` is downgraded exactly one rank".
    PRD Section 3.5: "Hop two hits the cohorts: every cohort of every colony
    in that room whose `health_status` rank now exceeds the room's downgraded
    rank is pulled down to the room's new `barrier_level`".

    Design: Difficulty/transitive_cascade/positive_screen_barrier_downgrade_release_chain
    """
    bundle = _allocated_vf_order()
    room = bundle["site"]["room"]
    cohort = bundle["cohorts"][0]

    screen = create_scheduled_health_screen(room["id"])
    result = result_health_screen(
        screen["id"],
        [
            create_screen_result_entry("MHV", True),
            create_screen_result_entry("PVM", False),
        ],
    )
    assert result["status"] == "RESULTED_POSITIVE"

    screen = find_screen_in_room(room["id"], screen["id"])
    assert screen["status"] == "RESULTED_POSITIVE"

    room = read_room(room["id"])
    assert room["status"] == "QUARANTINED"
    assert room["barrier_level"] == "MPF"  # one rank down from VF

    cohort = read_cohort(cohort["id"])
    assert cohort["health_status"] == "MPF"


def test_positive_screen_releases_allocations_and_reverts_order():
    """PRD Section 3.5: "Hop three hits the allocations: every allocation
    still in `RESERVED` on a downgraded cohort whose order's
    `min_health_status` rank exceeds the cohort's new `health_status` rank
    transitions to `RELEASED`".
    PRD Section 3.5: "for each order whose allocated totals now fall short of
    its requested quantities, an order in `ALLOCATED` reverts to `SOURCING`".

    Design: Difficulty/transitive_cascade/positive_screen_barrier_downgrade_release_chain
    """
    bundle = _allocated_vf_order()
    room = bundle["site"]["room"]
    cohort = bundle["cohorts"][0]
    order = bundle["order"]
    allocation = bundle["allocations"][0]

    screen = create_scheduled_health_screen(room["id"])
    result_health_screen(screen["id"], [create_screen_result_entry("MHV", True)])

    allocation = find_allocation_in_order(order["id"], allocation["id"])
    assert allocation["status"] == "RELEASED"

    cohort = read_cohort(cohort["id"])
    assert cohort["reserved_male"] == 0
    assert cohort["reserved_female"] == 0
    assert cohort["status"] == "HOLD"

    order = read_order(order["id"])
    assert order["allocated_male"] == 0
    assert order["allocated_female"] == 0
    assert order["status"] == "SOURCING"


def _suspended_facility_scenario():
    """SCHEDULED order with a PLANNED shipment plus an inspection resting in
    CORRECTIVE_ACTION past its deadline after the clock sweep."""
    bundle = setup_scheduled_order()
    facility = bundle["site"]["facility"]
    inspection = create_inspection_in_corrective_action(
        facility_id=facility["id"],
        findings=[create_finding("cage overcrowding", "SIGNIFICANT")],
        corrective_deadline="2026-09-10T00:00:00Z",
    )
    advance_clock("2026-09-11T00:00:00Z")
    return bundle, inspection


def test_overdue_inspection_escalates_and_suspends_facility():
    """PRD Section 3.9: "the clock sweep moves any `CORRECTIVE_ACTION`
    inspection whose `corrective_deadline` is strictly past to `ESCALATED`".
    PRD Section 3.9: "an escalated facility-site inspection flips that
    facility's `registration_status` to `SUSPENDED`, firing the full
    shipment-cancellation cascade of Section 3.1 with `suspension_reason` set
    to `OVERDUE_CORRECTIVE_ACTION`".

    Design: Difficulty/transitive_cascade/overdue_inspection_facility_suspension_cascade
    """
    bundle, inspection = _suspended_facility_scenario()
    facility = bundle["site"]["facility"]

    inspection = find_inspection_in_facility(facility["id"], inspection["id"])
    assert inspection["status"] == "ESCALATED"

    facility = read_facility(facility["id"])
    assert facility["registration_status"] == "SUSPENDED"
    assert facility["suspension_reason"] == SUSPENSION_REASON_OVERDUE_CORRECTIVE_ACTION


def test_facility_suspension_cancels_planned_shipment_order_recoverable():
    """PRD Section 3.1: "every shipment still in `PLANNED` or `LOADED` whose
    order draws any allocation from a cohort housed in this facility's rooms
    is cancelled, and each such cancelled shipment's order falls back from
    `SCHEDULED` to `ALLOCATED` with its allocations remaining `RESERVED`."

    Design: Difficulty/transitive_cascade/overdue_inspection_facility_suspension_cascade
    """
    bundle, _inspection = _suspended_facility_scenario()
    order = bundle["order"]
    shipment = bundle["shipment"]
    allocation = bundle["allocations"][0]

    shipment = find_shipment_in_order(order["id"], shipment["id"])
    assert shipment["status"] == "CANCELLED"

    order = read_order(order["id"])
    assert order["status"] == "ALLOCATED"

    allocation = find_allocation_in_order(order["id"], allocation["id"])
    assert allocation["status"] == "RESERVED"


def test_inspection_empty_findings_close_immediately():
    """PRD Section 3.9: "An empty `findings` array closes the inspection
    immediately as `CLOSED_VERIFIED` — no deficiencies, no corrective phase."

    Design: Corner/state_machines/inspection_empty_findings_close_immediately
    """
    facility = create_registered_facility()
    inspection = create_scheduled_inspection(facility_id=facility["id"])
    assert inspection["status"] == "SCHEDULED"

    reported = report_inspection_findings(inspection["id"], [])
    assert reported["status"] == "CLOSED_VERIFIED"

    # A clean report fires no cascade.
    assert read_facility(facility["id"])["registration_status"] == "REGISTERED"


def test_inspection_day_slot_conflict():
    """PRD Section 3.9: "Each site admits at most one open inspection per UTC
    calendar day: if another inspection of the same site in `SCHEDULED` or
    `CORRECTIVE_ACTION` already occupies that calendar day, the scheduling is
    rejected with `ERR_INSPECTION_DAY_CONFLICT` (HTTP 409)."

    Design: Corner/validations/inspection_day_slot_conflict
    """
    facility = create_registered_facility()
    first = create_scheduled_inspection(
        facility_id=facility["id"], scheduled_date="2026-09-05T09:00:00Z"
    )
    assert first["status"] == "SCHEDULED"

    # Same site, same UTC calendar day at a different hour: conflict.
    resp = api_client.create_inspection(
        {
            "facility_id": facility["id"],
            "inspection_type": "FOR_CAUSE",
            "scheduled_date": "2026-09-05T18:00:00Z",
        },
        _INSPECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTION_DAY_CONFLICT)

    # The next calendar day is free.
    second = create_scheduled_inspection(
        facility_id=facility["id"],
        inspection_type="FOR_CAUSE",
        scheduled_date="2026-09-06T09:00:00Z",
    )
    assert second["status"] == "SCHEDULED"


def test_inspection_verify_segregation_of_duties():
    """PRD Section 3.9: "Verification of the corrective work belongs to a
    different pair of hands: the verifying `WelfareInspector`'s `X-User-ID`
    must differ from `reported_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403). An `outcome` of `VERIFIED_OK` closes the inspection as
    `CLOSED_VERIFIED`."

    Design: Corner/rbac/inspection_verify_segregation_of_duties
    """
    facility = create_registered_facility()
    inspection = create_inspection_in_corrective_action(
        facility_id=facility["id"],
        reporter_id="insp-1",
        findings=[create_finding("recordkeeping gap", "MINOR")],
        corrective_deadline="2026-09-20T00:00:00Z",
    )
    assert inspection["status"] == "CORRECTIVE_ACTION"

    resp = api_client.verify_inspection(
        inspection["id"], {"outcome": "VERIFIED_OK"}, make_inspector_headers("insp-1")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    verified = verify_inspection(inspection["id"], "VERIFIED_OK", "insp-2")
    assert verified["status"] == "CLOSED_VERIFIED"
