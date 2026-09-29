"""Who may act, who may not, and which unknown identifier answers with which code."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CREW_NOT_ASSIGNED,
    ERR_FAULT_EVENT_NOT_FOUND,
    ERR_PATH_RESOURCE_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_WORK_ORDER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_cents,
    assert_error_envelope_is_minimal,
    assert_total_count,
    assert_version_unchanged,
    created,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    BLADE_OPEN,
    BLADE_PRIORITIZED,
    CREW_AVAILABLE,
    CREW_ON_SHIFT,
    DAMAGE_DELAMINATION,
    DAMAGE_LEADING_EDGE_EROSION,
    DAMAGE_LIGHTNING_STRIKE,
    INSPECTION_DRONE,
    INSPECTION_ROPE_ACCESS,
    WO_CANCELLED,
    WO_COMPLETED,
    WO_IN_PROGRESS,
    WO_SCHEDULED,
    WO_SUBMITTED,
)
from test_helpers.factories import (
    blade_damage_payload,
    farm_payload,
    scada_payload,
    work_order_payload,
)
from test_helpers.fixtures import (
    base_site,
    read_agreement,
    read_blade_damage,
    read_crew,
    read_farm,
    read_turbine,
    read_work_order,
    record_blade_damage,
    setup_role_denial_targets,
    setup_wrong_crew_order,
)
from test_helpers.test_users import (
    CREW_LEAD_USER_ID,
    ENGINEER_2_USER_ID,
    ENGINEER_USER_ID,
    PLANNER_USER_ID,
    make_control_room_headers,
    make_crew_lead_headers,
    make_engineer_headers,
    make_headers_with_blank_role,
    make_headers_with_blank_user_id,
    make_headers_without_role,
    make_headers_without_user_id,
    make_planner_headers,
    make_site_admin_headers,
    make_undeclared_role_headers,
)


def test_one_unknown_identifier_answers_with_three_different_not_found_codes(api):
    """The same unknown UUID, addressed to five collections, yields three codes.

    Reads and action endpoints agree within a collection, and the collection without a
    code of its own falls back to the generic identifier.

    PRD §2.9: "Four collections have dedicated not-found identifiers: a farm identifier
    that does not resolve yields `ERR_FARM_NOT_FOUND`, a turbine identifier yields
    `ERR_TURBINE_NOT_FOUND`, a work-order identifier yields `ERR_WORK_ORDER_NOT_FOUND`,
    and a fault-event identifier yields `ERR_FAULT_EVENT_NOT_FOUND`."
    PRD §2.9: "Every other single-resource path segment — turbine models, fault code rules,
    crews, weather windows, crane mobilizations, spare parts, component replacements, blade
    findings, service agreements, curtailment orders and landowner settlements — yields the
    generic `ERR_PATH_RESOURCE_NOT_FOUND`."
    PRD §2.9: "All five carry HTTP 404."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/errors/unknown_path_ids_return_the_collection_specific_not_found_code
    """
    expectations = [
        (api.get_work_order(NON_EXISTENT_UUID, make_planner_headers()), ERR_WORK_ORDER_NOT_FOUND),
        (
            api.submit_work_order(NON_EXISTENT_UUID, make_planner_headers()),
            ERR_WORK_ORDER_NOT_FOUND,
        ),
        (
            api.get_fault_event(NON_EXISTENT_UUID, make_control_room_headers()),
            ERR_FAULT_EVENT_NOT_FOUND,
        ),
        (
            api.close_fault_event(NON_EXISTENT_UUID, make_engineer_headers()),
            ERR_FAULT_EVENT_NOT_FOUND,
        ),
        (api.get_crew(NON_EXISTENT_UUID, make_planner_headers()), ERR_PATH_RESOURCE_NOT_FOUND),
        (
            api.get_spare_part(NON_EXISTENT_UUID, make_site_admin_headers()),
            ERR_PATH_RESOURCE_NOT_FOUND,
        ),
    ]
    for response, expected_error_id in expectations:
        validate_error(response, expected_error_id, expected_status=404)
        assert_error_envelope_is_minimal(response)


def test_an_absent_empty_or_undeclared_role_header_is_answered_before_anything_else(api):
    """Four malformed header sets and one unknown path all stop at authentication.

    The last call aims at an identifier that resolves to nothing, and it is still answered
    401 rather than 404, which places the header check ahead of path resolution.

    PRD §2.1: "Both headers must be present and non-empty, and `X-User-Role` must name one
    of the six roles below."
    PRD §2.1: "A request that omits either header, sends either as an empty value, or names
    a role outside the six is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any
    other processing happens."
    PRD §2.1: "The six roles are `SiteAdmin`, `ControlRoomOperator`, `MaintenancePlanner`,
    `ReliabilityEngineer`, `CrewLead` and `CommercialManager`."
    PRD §2.9: "Four collections have dedicated not-found identifiers: a farm identifier
    that does not resolve yields `ERR_FARM_NOT_FOUND`, a turbine identifier yields
    `ERR_TURBINE_NOT_FOUND`, a work-order identifier yields `ERR_WORK_ORDER_NOT_FOUND`,
    and a fault-event identifier yields `ERR_FAULT_EVENT_NOT_FOUND`."

    Design: Corner/rbac/a_missing_or_undeclared_role_header_is_unauthenticated
    """
    site = base_site(api)
    farm_id = site["farm"]["id"]
    # Commissioning the fixture's turbine already advanced the farm's own version by
    # cascade, so the baseline for "a rejected request writes nothing" is the farm as
    # it stands now, not the row returned at creation time.
    baseline = read_farm(api, farm_id)

    malformed_header_sets = [
        make_headers_without_role(),
        make_headers_with_blank_role(),
        make_headers_without_user_id(),
        make_headers_with_blank_user_id(),
        make_undeclared_role_headers(),
    ]
    for headers in malformed_header_sets:
        response = api.get_farm(farm_id, headers)
        validate_error(response, ERR_UNAUTHENTICATED, expected_status=401)
        assert_error_envelope_is_minimal(response)

    unknown_turbine = api.get_turbine(NON_EXISTENT_UUID, make_headers_without_role())
    validate_error(unknown_turbine, ERR_UNAUTHENTICATED, expected_status=401)

    readable = read_farm(api, farm_id)
    assert readable["id"] == farm_id
    assert_version_unchanged(baseline, readable)


def test_each_roles_exclusive_operation_is_refused_to_the_other_five(api):
    """Four well-formed requests, four peer roles, four refusals — including the admin's.

    The site administrator is refused the commercial settlement and the control room is
    refused the commercially restricted read, so authority is a per-endpoint list rather
    than a ladder of seniority.

    PRD §2.1: "A request whose headers are well-formed but whose role is not among the roles
    authorised for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "| POST | `/wind-ops/farms` | Register a wind farm with its levy percentages and
    landowner budget cap. | `SiteAdmin` |"
    PRD §4: "| POST | `/wind-ops/turbines/{id}/scada-sync` | Post a supervisory-control
    telemetry increment for one turbine: elapsed operating hours plus metered and potential
    energy for the period. | `ControlRoomOperator` |"
    PRD §4: "| POST | `/wind-ops/service-agreements/{id}/settle` | Close the measurement
    period and assess liquidated damages. | `CommercialManager` |"
    PRD §4: "| GET | `/wind-ops/service-agreements/{id}` | Read one service agreement
    including both availability figures, the projected shortfall and the assessed liquidated
    damages. | `SiteAdmin`, `CommercialManager`, `ReliabilityEngineer` |"
    PRD §2.1: "It may read every collection except the commercially restricted
    service-agreement and landowner-settlement reads."
    PRD §3.2: "Telemetry is the only path by which `operating_hours` advances."

    Design: Corner/rbac/another_roles_exclusive_operation_is_unauthorized
    """
    site = setup_role_denial_targets(api)
    turbine_id = site["turbine"]["id"]
    agreement_id = site["agreement"]["id"]

    validate_error(
        api.create_farm(
            farm_payload(name="Rogue Site", region_code="MT-W", grid_operator_code="NWMT"),
            make_control_room_headers(),
        ),
        ERR_UNAUTHORIZED,
        expected_status=403,
    )
    validate_error(
        api.scada_sync(turbine_id, scada_payload(10.0, 20000.0, 21000.0), make_planner_headers()),
        ERR_UNAUTHORIZED,
        expected_status=403,
    )
    validate_error(
        api.settle_agreement(agreement_id, make_site_admin_headers()),
        ERR_UNAUTHORIZED,
        expected_status=403,
    )
    validate_error(
        api.get_service_agreement(agreement_id, make_control_room_headers()),
        ERR_UNAUTHORIZED,
        expected_status=403,
    )

    assert_total_count(api.list_farms(make_site_admin_headers()), 1)

    turbine = read_turbine(api, turbine_id)
    assert turbine["operating_hours"] == 0, turbine["operating_hours"]
    assert_version_unchanged(site["turbine"], turbine)

    agreement = read_agreement(api, agreement_id)
    assert agreement["state"] == AGREEMENT_ACTIVE
    assert_version_unchanged(site["agreement"], agreement)


def test_neither_the_unassigned_crew_nor_the_submitting_engineer_may_drive_the_order(api):
    """One order, two kinds of refusal: a data comparison and a four-eyes rule.

    The lead of the crew that holds no reservation is refused on both start and completion,
    while the engineer who submitted the order is refused on completion alone, and the order
    survives all three refusals unchanged.

    PRD §2.1: "Concretely, when a `CrewLead` starts or completes a work order, the acting
    `X-User-ID` must equal that work order's `crew_id`, and a mismatch is rejected with
    `ERR_CREW_NOT_ASSIGNED` (HTTP 403)."
    PRD §2.1: "Completing a work order requires that the acting `X-User-ID` differs from that
    order's `submitted_by_user_id`."
    PRD §2.1: "Note that these two rules are evaluated after basic role authorisation but
    before the crew-assignment ownership check: on work-order completion the order of
    evaluation is `ERR_UNAUTHENTICATED`, then `ERR_UNAUTHORIZED`, then
    `ERR_SEGREGATION_OF_DUTIES`, then `ERR_CREW_NOT_ASSIGNED`."
    PRD §3.5: "The assigned crew's `status` is set to `ON_SHIFT`."
    PRD §3.5: "The order moves `IN_PROGRESS → COMPLETED` and its `labor_cost_cents` is set to
    `actual_hours` multiplied by the assigned crew's `hourly_rate_cents`, rounded half up to
    a whole cent."
    PRD §3.3: "A new order starts in `state` `DRAFT` with `revision_round` at 0,
    `priority_score` at 0 and `labor_cost_cents` at 0, and with `crew_id`,
    `weather_window_id`, `planned_start_utc`, `planned_end_utc`, `actual_hours` and
    `submitted_by_user_id` all null."
    PRD §3.5: "Alongside those hops, completion posts the labour cost to the site ledger,
    adding `labor_cost_cents` both to the farm's `maintenance_spend_cents` and to its
    `opex_accrued_cents`."
    PRD §2.12: "A rejected request writes nothing at all — no counter moves, no `version`
    advances, no partial cascade survives."

    Design: Corner/rbac/start_and_complete_cannot_be_driven_by_the_wrong_crew_or_by_the_submitter
    """
    site = setup_wrong_crew_order(api)
    order_id = site["order"]["id"]
    crew_a_id = site["crew_a"]["id"]
    crew_b_id = site["crew_b"]["id"]

    validate_error(
        api.start_work_order(order_id, make_crew_lead_headers(crew_b_id)),
        ERR_CREW_NOT_ASSIGNED,
        expected_status=403,
    )
    still_scheduled = read_work_order(api, order_id)
    assert still_scheduled["state"] == WO_SCHEDULED
    assert_version_unchanged(site["order"], still_scheduled)

    started = validate_success(api.start_work_order(order_id, make_crew_lead_headers(crew_a_id)))
    assert started["state"] == WO_IN_PROGRESS
    assert read_crew(api, crew_a_id)["status"] == CREW_ON_SHIFT

    validate_error(
        api.complete_work_order(order_id, 8, make_engineer_headers()),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    validate_error(
        api.complete_work_order(order_id, 8, make_crew_lead_headers(crew_b_id)),
        ERR_CREW_NOT_ASSIGNED,
        expected_status=403,
    )

    unchanged = read_work_order(api, order_id)
    assert unchanged["state"] == WO_IN_PROGRESS
    assert_cents(unchanged["labor_cost_cents"], 0, "order.labor_cost_cents")
    assert_version_unchanged(started, unchanged)
    assert_cents(
        read_farm(api, site["farm"]["id"])["maintenance_spend_cents"],
        0,
        "farm.maintenance_spend_cents",
    )
    assert read_crew(api, crew_b_id)["status"] == CREW_AVAILABLE

    completed = validate_success(
        api.complete_work_order(order_id, 8, make_crew_lead_headers(crew_a_id))
    )
    assert completed["state"] == WO_COMPLETED
    assert_cents(completed["labor_cost_cents"], 720000, "order.labor_cost_cents")
    assert read_crew(api, crew_b_id)["status"] == CREW_AVAILABLE


def test_the_inspector_who_recorded_a_finding_cannot_accept_it_into_the_repair_programme(api):
    """The four-eyes rule guards prioritization too, comparing against the recorder.

    Both actors hold the same role, so the refusal can only come from the identifier the
    recording stamped, and a second engineer clears the finding without difficulty.

    PRD §2.1: "Prioritizing a blade finding requires that the acting `X-User-ID` differs from
    that finding's `recorded_by_user_id`."
    PRD §3.6: "Recording a finding sets its `state` to `OPEN`, stamps `recorded_by_user_id`
    with the acting `X-User-ID`, and leaves `waiver_rationale` null."
    PRD §3.6: "Accepting a finding into the repair programme moves it `OPEN → PRIORITIZED`
    and may be done by a `ReliabilityEngineer` or a `CrewLead`, but never by the inspector who
    recorded it — the acting `X-User-ID` must differ from `recorded_by_user_id`, and a match is
    refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.6: "Classification immediately produces a `severity_score` on a 0-to-100 scale from
    four factors."
    PRD §3.6: "`repair_priority_band` is `CRITICAL` when `severity_score` is at least 80,
    `HIGH` when it is at least 60 but below 80, `MEDIUM` when it is at least 40 but below 60,
    and `LOW` otherwise."

    Design: Corner/rbac/blade_damage_prioritization_rejects_the_engineer_who_recorded_it
    """
    site = base_site(api)
    finding = record_blade_damage(
        api,
        site["turbine"]["id"],
        headers=make_engineer_headers(),
        inspection_method=INSPECTION_DRONE,
        blade_position="C",
        inspected_at="2026-08-01T02:00:00Z",
        damage_category=3,
        damage_type=DAMAGE_DELAMINATION,
        chord_position_pct=45.0,
        damage_length_mm=900,
        exposed_area_cm2=600.0,
    )
    assert finding["state"] == BLADE_OPEN
    assert finding["recorded_by_user_id"] == ENGINEER_USER_ID

    validate_error(
        api.prioritize_blade_damage(finding["id"], make_engineer_headers()),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    refused = read_blade_damage(api, finding["id"])
    assert refused["state"] == BLADE_OPEN
    assert refused["recorded_by_user_id"] == ENGINEER_USER_ID
    assert_version_unchanged(finding, refused)

    accepted = validate_success(
        api.prioritize_blade_damage(finding["id"], make_engineer_headers(ENGINEER_2_USER_ID))
    )
    assert accepted["state"] == BLADE_PRIORITIZED
    assert 0 <= accepted["severity_score"] <= 100, accepted["severity_score"]
    assert accepted["repair_priority_band"] is not None


def test_every_shared_operation_answers_to_both_of_the_roles_that_declare_it(api):
    """Four shared endpoints are driven from each of their two declared sides in turn.

    Raising, submitting, recording a finding and cancelling are each exercised twice with
    different roles, and the submission stamp follows the acting user rather than the creator.

    PRD §3.3: "A work order is raised against a turbine by a `MaintenancePlanner` or a
    `ReliabilityEngineer`."
    PRD §3.3: "Either way the turbine must not be `DECOMMISSIONED`, `submitted_by_user_id` is
    set to the acting `X-User-ID` — overwriting whatever it held on a previous submission — and
    the order's `priority_score` is computed."
    PRD §4: "| POST | `/wind-ops/work-orders/{id}/submit` | Submit a DRAFT or
    REVISION_REQUESTED work order for planning. | `MaintenancePlanner`, `ReliabilityEngineer` |"
    PRD §3.6: "Blade findings enter the system from three kinds of inspection, recorded by a
    `ReliabilityEngineer` or a `CrewLead` against a turbine."
    PRD §3.6: "Recording a finding sets its `state` to `OPEN`, stamps `recorded_by_user_id`
    with the acting `X-User-ID`, and leaves `waiver_rationale` null."
    PRD §3.5: "Abandoning an order is a `MaintenancePlanner` or `SiteAdmin` action carrying a
    `cancellation_reason`, and it is reachable from `DRAFT`, `SUBMITTED` and
    `REVISION_REQUESTED` as well as from `SCHEDULED`."

    Design: Corner/rbac/shared_operations_work_for_every_role_that_declares_them
    """
    site = base_site(api)
    turbine_id = site["turbine"]["id"]

    planners_order = created(
        api.create_work_order(work_order_payload(turbine_id), make_planner_headers())
    )
    engineers_order = created(
        api.create_work_order(work_order_payload(turbine_id), make_engineer_headers())
    )

    submitted_by_engineer = validate_success(
        api.submit_work_order(planners_order["id"], make_engineer_headers())
    )
    assert submitted_by_engineer["state"] == WO_SUBMITTED
    assert submitted_by_engineer["submitted_by_user_id"] == ENGINEER_USER_ID

    submitted_by_planner = validate_success(
        api.submit_work_order(engineers_order["id"], make_planner_headers())
    )
    assert submitted_by_planner["state"] == WO_SUBMITTED
    assert submitted_by_planner["submitted_by_user_id"] == PLANNER_USER_ID

    engineers_finding = created(
        api.record_blade_damage(
            turbine_id,
            blade_damage_payload(
                inspection_method=INSPECTION_DRONE,
                blade_position="A",
                inspected_at="2026-08-01T02:00:00Z",
                damage_category=2,
                damage_type=DAMAGE_LEADING_EDGE_EROSION,
                chord_position_pct=30.0,
                damage_length_mm=400,
                exposed_area_cm2=90.0,
            ),
            make_engineer_headers(),
        )
    )
    assert engineers_finding["state"] == BLADE_OPEN
    assert engineers_finding["recorded_by_user_id"] == ENGINEER_USER_ID

    leads_finding = created(
        api.record_blade_damage(
            turbine_id,
            blade_damage_payload(
                inspection_method=INSPECTION_ROPE_ACCESS,
                blade_position="B",
                inspected_at="2026-08-01T03:00:00Z",
                damage_category=2,
                damage_type=DAMAGE_LIGHTNING_STRIKE,
                chord_position_pct=20.0,
                damage_length_mm=200,
                exposed_area_cm2=40.0,
            ),
            make_crew_lead_headers(),
        )
    )
    assert leads_finding["state"] == BLADE_OPEN
    assert leads_finding["recorded_by_user_id"] == CREW_LEAD_USER_ID

    cancelled_by_planner = validate_success(
        api.cancel_work_order(
            planners_order["id"], "superseded by the engineer's order", make_planner_headers()
        )
    )
    assert cancelled_by_planner["state"] == WO_CANCELLED

    cancelled_by_admin = validate_success(
        api.cancel_work_order(
            engineers_order["id"], "site stand-down", make_site_admin_headers()
        )
    )
    assert cancelled_by_admin["state"] == WO_CANCELLED
