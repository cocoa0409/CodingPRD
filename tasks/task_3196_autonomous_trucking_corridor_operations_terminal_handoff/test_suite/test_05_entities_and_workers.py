"""Entity creation, listing, and driver-workforce corners."""
import pytest

from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
)

from test_helpers import (
    api_client, ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    setup_stack, make_corridor, setup_launched_corridor, create_run,
    make_operational_terminal, make_carrier, make_commitment,
    create_run_plan_payload, create_driver_transition_payload,
    create_driver_prospect_payload, create_security_record_payload,
    create_incident_report_payload,
)


def _list_payload(stack, corridor, commitment_id, start, end, trailers, posted=225):
    return create_run_plan_payload(
        corridor["id"], stack["carrier"]["id"], stack["origin"]["id"],
        stack["destination"]["id"], commitment_id, stack["prospect"]["id"],
        window_start_epoch_day=start, window_end_epoch_day=end,
        trailer_count=trailers, posted_per_mile_cents=posted,
        sacra_loadboard_slot_held=False)


# ─── corner: entities/terminal_get_with_an_unknown_id ───────────────────────

def test_get_terminal_with_an_unknown_id_returns_terminal_not_found(api, any_headers):
    """PRD §2.11: "Path identifiers get their own, more specific codes: a
    missing corridor is `ERR_CORRIDOR_NOT_FOUND`, a missing run plan
    `ERR_RUN_PLAN_NOT_FOUND`, a missing terminal `ERR_TERMINAL_NOT_FOUND`".

    Design: Corner/entities/terminal_get_with_an_unknown_id_returns_terminal_not_found
    """
    resp = api_client.get_terminal(NON_EXISTENT_UUID, any_headers)
    validate_error(resp, ApiErrorId.ERR_TERMINAL_NOT_FOUND, expected_status=404)


# ─── corner: entities/run_plans_list_filters_by_commitment_and_paginates ────

def test_run_plan_list_filters_by_commitment(api, any_headers):
    """PRD §2.3: "filters are applied before the count is taken, so
    `total_count` always describes the filtered result set rather than the
    underlying table."

    Two of three run plans belong to the first commitment, so the filtered list
    reports total_count 2.

    Design: Corner/entities/run_plans_list_filters_by_commitment_and_paginates
    """
    stack = setup_launched_corridor()
    corridor = stack["corridor"]
    com_b = make_commitment()
    _make_plan(stack, corridor, stack["commitment"]["id"], 10, 12, 1)
    _make_plan(stack, corridor, stack["commitment"]["id"], 13, 15, 2)
    _make_plan(stack, corridor, com_b["id"], 16, 18, 2, posted=240)
    resp = api_client.list_run_plans(any_headers,
                                     params={"shipper_commitment_id": stack["commitment"]["id"],
                                             "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_run_plan_list_without_a_filter_reports_the_whole_set(api, any_headers):
    """PRD §2.3: "List responses carry four pagination fields in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/run_plans_list_filters_by_commitment_and_paginates
    """
    stack = setup_launched_corridor()
    corridor = stack["corridor"]
    com_b = make_commitment()
    _make_plan(stack, corridor, stack["commitment"]["id"], 10, 12, 1)
    _make_plan(stack, corridor, stack["commitment"]["id"], 13, 15, 2)
    _make_plan(stack, corridor, com_b["id"], 16, 18, 2, posted=240)
    data, meta = validate_paginated(api_client.list_run_plans(any_headers))
    assert len(data) == 3
    assert meta["total_count"] == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def _make_plan(stack, corridor, commitment_id, start, end, trailers, posted=225):
    return validate_success(api_client.create_run_plan(
        _list_payload(stack, corridor, commitment_id, start, end, trailers, posted),
        TEST_USERS["carrier_dispatcher_headers"]), expected_status=201)


# ─── corner: entities/carrier_dot_number_uniqueness_is_not_enforced_at_create

def test_carrier_duplicate_dot_number_is_accepted_at_create(api, any_headers):
    """PRD §3.6: "a `dot_number`, the USDOT number that acts as the
    partnership's natural key and must be unique among carriers".
    PRD §2.10: "Natural keys such as `terminal_code`, `dot_number`, `state_code`,
    `unit_id`, `security_code` and `container_number` are business identifiers
    and are validated for uniqueness where the entity says so".

    A second carrier posting an already-active DOT number is still created in
    ONBOARDING, so uniqueness is not a create-time rule.

    Design: Corner/entities/carrier_dot_number_uniqueness_is_not_enforced_at_create
    """
    active = make_carrier(dot="DOT-3196001", active=True)
    data = validate_success(api_client.create_carrier(
        {"carrier_name": "Sonoran Carriers LLC", "dot_number": "DOT-3196001"},
        TEST_USERS["compliance_officer_headers"]), expected_status=201)
    assert data["carrier_status"] == "ONBOARDING"
    still = validate_success(api_client.get_carrier(active["id"], any_headers))
    assert still["carrier_status"] == "ACTIVE"


# ─── corner: entities/driver_prospect_create_returns_identity ───────────────

def test_driver_prospect_create_returns_the_entity_backed_identity(api, any_headers):
    """PRD §3.8: "A prospect starts with `hours_worked` of 0,
    `enrollments_on_file` of 0 and a `safety_reliability_score` of 1000."
    PRD §2.1: "When `X-User-Role` is `RemoteSupportOperator`, `X-User-ID` is the
    `id` of the acting `DriverProspect`".

    Design: Corner/entities/driver_prospect_create_returns_identity_for_entity_backed_roles
    """
    terminal = make_operational_terminal("PHX-WEST")
    data = validate_success(api_client.create_driver_prospect(
        create_driver_prospect_payload(terminal["id"], prospect_name="Mira Okafor",
                                       pathway="REMOTE_SUPPORT"),
        TEST_USERS["driver_outreach_headers"]), expected_status=201)
    assert data["safety_reliability_score"] == 1000
    assert data["hours_worked"] == 0
    assert data["enrollments_on_file"] == 0
    assert data["pathway"] == "REMOTE_SUPPORT"
    assert data["home_terminal_id"] == terminal["id"]


# ─── corner: entities/security_record_route_and_clamps_change_record_status ─

def test_security_record_clamp_forces_high_consequence(api, any_headers):
    """PRD §3.12: "Clamping the record sets `convention_status` to
    `HIGH_CONSEQUENCE` and recomputes `record_status`."
    PRD §3.12: "it is clamped to `NORMAL` while the record is in transit, and
    clamped to `HIGH_CONSEQUENCE` once the high-consequence clearance lands."

    Design: Corner/entities/security_record_route_and_clamps_change_record_status
    """
    origin = make_operational_terminal("PHX-WEST")
    record = validate_success(api_client.create_security_record(
        create_security_record_payload(origin["id"]), TEST_USERS["compliance_officer_headers"]),
        expected_status=201)
    assert record["destination_terminal_id"] is None
    assert record["consignor_code"] == record["security_code"], \
        "the consignor code copies the record's own security code"
    data = validate_success(api_client.clamp_security_record(
        record["id"], TEST_USERS["compliance_officer_headers"]))
    assert data["convention_status"] == "HIGH_CONSEQUENCE"


# ─── corner: calculations/driver_reroute_risk_corridor_scope_excludes_draft_runs

def test_credential_lapse_debits_the_prospect_reliability_score(api, any_headers):
    """PRD §3.8: "A `CorridorOperationsManager` records a credential-lapse event
    on a transition, which moves the transition to `CREDENTIAL_LAPSED`, sets its
    `credential_event_count` to 1, and debits exactly 50 points from the owning
    prospect's `safety_reliability_score`, floored at 0."

    Design: Corner/calculations/driver_reroute_risk_corridor_scope_excludes_draft_runs
    """
    stack = setup_stack()
    transition = validate_success(api_client.create_driver_transition(
        create_driver_transition_payload(stack["prospect"]["id"], stack["origin"]["id"],
                                         pathway="FIRST_LAST_MILE",
                                         transition_start_epoch_day=1,
                                         transition_days_count=10, hours_recorded=4),
        TEST_USERS["driver_outreach_headers"]), expected_status=201)
    before = validate_success(api_client.get_driver_prospect(
        stack["prospect"]["id"], any_headers))["safety_reliability_score"]
    assert before == 1000
    api_client.credential_lapse_transition(transition["id"],
                                           TEST_USERS["corridor_manager_headers"])
    data = validate_success(api_client.get_driver_transition(transition["id"], any_headers))
    prospect = validate_success(api_client.get_driver_prospect(stack["prospect"]["id"], any_headers))
    assert data["credential_event_count"] == 1
    assert data["transition_status"] == "CREDENTIAL_LAPSED"
    assert prospect["safety_reliability_score"] == 950


# ─── corner: endpoints/driver_transition_ride_along_creates_a_hauler_row ────

def test_ride_along_creates_a_reverse_reachable_hauler_row(api, any_headers):
    """PRD §3.8: "A ride-along action on a transition takes a `run_plan_id` and
    creates a `RunPlanHauler` evaluation plan attached to the transition, moving
    its `transition_status` to `RIDE_ALONG_VERIFIED`."
    PRD §3.8: "it names the `run_plan_id`, the `driver_transition_id` that supplies
    the unit, a `hauler_role` of `FIRST_MILE_DRIVER`, `LAST_MILE_DRIVER` or
    `YARD_SHUTTLE`".

    Design: Corner/endpoints/driver_transition_ride_along_creates_a_reverse_reachable_hauler_row
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    transition = validate_success(api_client.create_driver_transition(
        create_driver_transition_payload(stack["prospect"]["id"], stack["origin"]["id"],
                                         pathway="RIDE_ALONG_EVALUATOR",
                                         transition_start_epoch_day=1,
                                         transition_days_count=3, hours_recorded=8),
        TEST_USERS["driver_outreach_headers"]), expected_status=201)
    data = validate_success(api_client.ride_along_transition(
        transition["id"], {"run_plan_id": run["id"]}, TEST_USERS["driver_outreach_headers"]))
    assert data["transition_status"] == "RIDE_ALONG_VERIFIED"
    haulers = validate_success(api_client.list_transition_haulers(transition["id"], any_headers))
    rows = haulers if isinstance(haulers, list) else haulers.get("data", [])
    assert len(rows) == 1
    assert rows[0]["run_plan_id"] == run["id"]
    assert rows[0]["driver_transition_id"] == transition["id"]


# ─── corner: cross_cutting/derived_field_reconciliation_of_carrier_incident_band

def test_added_recordable_incident_recomputes_the_carrier_band_to_watch(api, any_headers):
    """PRD §3.6: "`WATCH` once it reaches 2, and `CLEAN` below 2."
    PRD §3.5: "Filing also recomputes the owning carrier's
    `recordable_incidents_last_epoch`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_of_carrier_incident_band
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    validate_success(api_client.create_incident_report(
        create_incident_report_payload(stack["corridor"]["id"], run["id"],
                                       severity="MINOR", recordable_incidents=2),
        TEST_USERS["incident_reviewer_headers"]), expected_status=201)
    carrier = validate_success(api_client.get_carrier(stack["carrier"]["id"], any_headers))
    assert carrier["recordable_incidents_last_epoch"] == 2
    assert carrier["incident_band"] == "WATCH"