"""Error identity and role boundaries: which refusal wins, and who may act at all.

The refusal ladder of §2.6 is walked from the outside in: every missing path id
reports its own entity code, every missing body foreign key reports its own code in
the order the endpoint declares its inputs, and the role test at priority 2 is shown
to run ahead of the path lookup at priority 3.
"""

import pytest

from test_helpers import (
    ADMIN,
    INSPECTOR,
    MANAGER,
    OPERATOR,
    SAFETY_OFFICER,
    TECHNICIAN,
    api_client,
    assert_attraction,
    assert_component,
    assert_daily_inspection,
    assert_downtime_event,
    assert_error_envelope,
    assert_instant_equals,
    assert_shop_bay,
    factories,
    fixtures,
    make_qualified_inspector_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"
CLOCK_START_DATE = "2026-08-01"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_every_path_identifier_reports_the_code_of_the_entity_it_names():
    """PRD §2.6: "The error names the resource that was missing:
    `ERR_ATTRACTION_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`,
    `ERR_CHECKLIST_ITEM_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
    `ERR_ITEM_RESULT_NOT_FOUND`, `ERR_BULLETIN_NOT_FOUND`,
    `ERR_BULLETIN_ACTION_NOT_FOUND`, `ERR_DOWNTIME_EVENT_NOT_FOUND`,
    `ERR_REQUISITION_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND`, `ERR_SHOP_BAY_NOT_FOUND` or
    `ERR_WORK_ORDER_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/every_path_id_lookup_reports_its_own_not_found_code
    """
    probes = (
        (api_client.get_attraction, "ERR_ATTRACTION_NOT_FOUND"),
        (api_client.get_component, "ERR_COMPONENT_NOT_FOUND"),
        (api_client.get_inspection_template, "ERR_TEMPLATE_NOT_FOUND"),
        (api_client.get_checklist_item, "ERR_CHECKLIST_ITEM_NOT_FOUND"),
        (api_client.get_daily_inspection, "ERR_INSPECTION_NOT_FOUND"),
        (api_client.get_inspection_item_result, "ERR_ITEM_RESULT_NOT_FOUND"),
        (api_client.get_bulletin, "ERR_BULLETIN_NOT_FOUND"),
        (api_client.get_bulletin_action, "ERR_BULLETIN_ACTION_NOT_FOUND"),
        (api_client.get_downtime_event, "ERR_DOWNTIME_EVENT_NOT_FOUND"),
        (api_client.get_part_requisition, "ERR_REQUISITION_NOT_FOUND"),
        (api_client.get_operator_certification, "ERR_CERTIFICATION_NOT_FOUND"),
        (api_client.get_incident, "ERR_INCIDENT_NOT_FOUND"),
        (api_client.get_shop_bay, "ERR_SHOP_BAY_NOT_FOUND"),
        (api_client.get_overhaul_work_order, "ERR_WORK_ORDER_NOT_FOUND"),
    )
    for read_by_id, expected_error_id in probes:
        response = read_by_id(UNKNOWN_ID, MANAGER)
        assert_error_envelope(response)
        validate_error(response, expected_error_id, 404)
        assert response.json()["data"]["message"], (
            f"{expected_error_id} carries a non-empty message"
        )


def test_a_missing_body_foreign_key_reports_its_own_code_in_declared_field_order():
    """PRD §2.6: "Every foreign key supplied in the request body resolves to a live
    row, validated in the order the fields are declared for that endpoint in §4's
    companion narrative."

    Design: Corner/errors/body_foreign_keys_report_their_own_not_found_code_in_declared_field_order
    """
    attraction = fixtures.create_attraction(
        name="FK Probe Ride",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="FK-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Probe Axle",
        component_type="AXLE",
        criticality="ESSENTIAL",
        ndt_interval_cycles=500000,
        ndt_interval_days=3650,
    )
    event = fixtures.open_downtime(
        attraction["id"], started_at="2026-08-01T09:00:00.000Z"
    )
    bay = fixtures.create_shop_bay("Bay FK", 1)

    validate_error(
        api_client.create_component(
            factories.create_component_payload(UNKNOWN_ID, name="Orphan Brake"),
            ADMIN,
        ),
        "ERR_ATTRACTION_NOT_FOUND",
        404,
    )
    _, component_meta = validate_paginated(
        api_client.list_components(MANAGER, params={"attraction_id": attraction["id"]})
    )
    assert component_meta["total_count"] == 1, "the refused create wrote no component"

    validate_error(
        api_client.diagnose_downtime_event(
            event["id"],
            factories.diagnose_downtime_payload("UNKNOWN-1", UNKNOWN_ID),
            TECHNICIAN,
        ),
        "ERR_COMPONENT_NOT_FOUND",
        404,
    )
    untouched = validate_success(
        api_client.get_downtime_event(event["id"], MANAGER)
    )
    assert_downtime_event(untouched)
    assert untouched["status"] == "OPEN"
    assert untouched["root_cause_code"] is None

    validate_error(
        api_client.create_bulletin(
            factories.create_bulletin_payload(
                "BR-FK-1",
                manufacturer="Vekoma",
                model_code="FK-1",
                severity="ADVISORY",
                supersedes_bulletin_id=UNKNOWN_ID,
            ),
            ADMIN,
        ),
        "ERR_BULLETIN_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_part_requisition(
            factories.create_part_requisition_payload(
                attraction["id"], part_number="PN-FK-A", bulletin_action_id=UNKNOWN_ID
            ),
            TECHNICIAN,
        ),
        "ERR_BULLETIN_ACTION_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_part_requisition(
            factories.create_part_requisition_payload(
                attraction["id"], part_number="PN-FK-B", downtime_event_id=UNKNOWN_ID
            ),
            TECHNICIAN,
        ),
        "ERR_DOWNTIME_EVENT_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.create_overhaul_work_order(
            factories.create_overhaul_work_order_payload(
                attraction["id"], component["id"], UNKNOWN_ID, bay["version"]
            ),
            MANAGER,
        ),
        "ERR_SHOP_BAY_NOT_FOUND",
        404,
    )
    bay_after = fixtures.read_shop_bay(bay["id"])
    assert_shop_bay(bay_after)
    assert bay_after["booked_order_count"] == 0
    assert bay_after["version"] == bay["version"], "the refused booking touched no bay"

    validate_error(
        api_client.create_overhaul_work_order(
            factories.create_overhaul_work_order_payload(
                UNKNOWN_ID, UNKNOWN_ID, UNKNOWN_ID, bay["version"]
            ),
            MANAGER,
        ),
        "ERR_ATTRACTION_NOT_FOUND",
        404,
    )

    _, requisition_meta = validate_paginated(
        api_client.list_part_requisitions(
            MANAGER, params={"attraction_id": attraction["id"]}
        )
    )
    assert requisition_meta["total_count"] == 0, "no refused requisition was stored"
    assert (
        fixtures.read_attraction(attraction["id"])["parts_budget_committed_cents"] == 0
    )


def test_the_role_test_runs_before_the_path_lookup_and_refuses_every_foreign_role():
    """PRD §2.6: "`X-User-Role` names one of the six declared roles and that role
    appears among the target endpoint's authorised roles — otherwise
    `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/every_role_is_denied_the_other_roles_exclusive_operations_and_returns_unauthorized
    """
    validate_error(
        api_client.create_attraction(
            factories.create_attraction_payload(
                name="Denied Ride",
                park_area="SKYLINE",
                manufacturer="Intamin",
                model_code="DN-1",
            ),
            MANAGER,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    _, attraction_meta = validate_paginated(api_client.list_attractions(MANAGER))
    assert attraction_meta["total_count"] == 0, "the refused registration wrote nothing"

    validate_error(
        api_client.acknowledge_bulletin(UNKNOWN_ID, ADMIN),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_daily_inspection(
            factories.create_daily_inspection_payload(UNKNOWN_ID, CLOCK_START_DATE),
            INSPECTOR,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.sign_off_daily_inspection(UNKNOWN_ID, TECHNICIAN),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_incident(
            factories.create_incident_payload(
                UNKNOWN_ID,
                occurred_at="2026-08-01T10:00:00.000Z",
                injury_severity="MINOR",
                guest_count_affected=1,
                narrative="Denied filing.",
            ),
            MANAGER,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.log_cycles(
            UNKNOWN_ID,
            factories.log_cycles_payload(CLOCK_START_DATE, 10),
            SAFETY_OFFICER,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_operator_certification(
            factories.create_operator_certification_payload(UNKNOWN_ID),
            SAFETY_OFFICER,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.set_clock(
            factories.set_clock_payload("2026-08-02T00:00:00.000Z"), MANAGER
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    witness = fixtures.create_attraction(name="Clock Witness")
    assert_attraction(witness)
    baseline = fixtures.create_component(witness["id"], name="Clock Witness Axle")
    assert_component(baseline)
    # Installation seeds last_ndt_at from the logical clock, so this reads the instant
    # the clock would have carried had the refused move landed.
    assert_instant_equals(baseline["last_ndt_at"], CLOCK_START, "last_ndt_at")


def test_the_most_restricted_role_may_log_cycles_and_read_every_derived_view():
    """PRD §3.1: "Ride cycles are the wear metric that drives half of the
    nondestructive-testing regime, and logging them is the one write operation a
    `RideOperator` shares with a `MaintenanceTechnician`."

    Design: Corner/rbac/ride_operator_may_log_cycles_and_read_every_get_endpoint
    """
    attraction = fixtures.create_attraction(
        name="Operator Access Ride",
        park_area="KIDS_COVE",
        manufacturer="Zamperla",
        model_code="OA-1",
        ride_class="FAMILY",
        theoretical_hourly_capacity=500,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Operator Axle",
        component_type="AXLE",
        criticality="ESSENTIAL",
        ndt_interval_cycles=500000,
        ndt_interval_days=3650,
    )

    after_operator = validate_success(
        api_client.log_cycles(
            attraction["id"],
            factories.log_cycles_payload(CLOCK_START_DATE, 40),
            OPERATOR,
        )
    )
    assert_attraction(after_operator)
    assert after_operator["cumulative_cycles"] == 40

    after_technician = validate_success(
        api_client.log_cycles(
            attraction["id"],
            factories.log_cycles_payload(CLOCK_START_DATE, 50),
            TECHNICIAN,
        )
    )
    assert after_technician["cumulative_cycles"] == 90, (
        "both roles accumulate onto the same counter"
    )

    read_as_operator = validate_success(
        api_client.get_attraction(attraction["id"], OPERATOR)
    )
    assert read_as_operator["operational_posture"] == "CLOSED_PENDING_INSPECTION"
    assert read_as_operator["certified_operator_count"] == 0

    readiness = validate_success(
        api_client.get_dispatch_readiness(attraction["id"], OPERATOR)
    )
    assert readiness["dispatch_readiness_index"] == pytest.approx(0.00, abs=0.01)
    assert readiness["essential_fail_count"] == 0

    components, components_meta = validate_paginated(
        api_client.list_components(OPERATOR, params={"attraction_id": attraction["id"]})
    )
    assert components_meta["total_count"] == 1
    assert [row["id"] for row in components] == [component["id"]]
    assert_component(components[0])
    assert components[0]["ndt_status"] == "CURRENT", (
        "90 cycles sit far inside an interval of 500000"
    )


def test_the_badge_that_recorded_a_line_may_not_sign_the_same_walk():
    """PRD §3.3: "A signer who recorded any result on this walk is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_recording_technician_may_not_sign_off_the_same_inspection
    """
    attraction = fixtures.create_attraction(
        name="SoD Ride",
        park_area="LAGOON",
        manufacturer="Mack",
        model_code="SD-1",
        ride_class="WATER",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    bundle = fixtures.inspection_pending_sign_off(
        ("ADVISORY",),
        outcomes=["PASS"],
        service_date=CLOCK_START_DATE,
        technician_badge="u-dual",
        attraction=attraction,
    )
    inspection = bundle["inspection"]
    assert_daily_inspection(inspection)
    assert inspection["recorded_by_user_ids"] == ["u-dual"]
    assert inspection["status"] == "PENDING_SIGN_OFF"
    assert inspection["blocking_item_count"] == 0

    validate_error(
        api_client.sign_off_daily_inspection(
            inspection["id"], make_qualified_inspector_headers("u-dual")
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    refused = validate_success(
        api_client.get_daily_inspection(inspection["id"], TECHNICIAN)
    )
    assert refused["status"] == "PENDING_SIGN_OFF"
    assert refused["signed_off_by_user_id"] is None

    signed = validate_success(
        api_client.sign_off_daily_inspection(
            inspection["id"], make_qualified_inspector_headers("insp-9")
        )
    )
    assert signed["status"] == "SIGNED_OFF"
    assert signed["signed_off_by_user_id"] == "insp-9"
    assert_instant_equals(signed["signed_off_at"], CLOCK_START, "signed_off_at")
    assert signed["recorded_by_user_ids"] == ["u-dual"], (
        "signing does not append the signer to the recording badges"
    )

    parent = fixtures.read_attraction(attraction["id"])
    assert parent["last_signed_off_service_date"] == CLOCK_START_DATE
    assert parent["operational_posture"] == "OPEN"
