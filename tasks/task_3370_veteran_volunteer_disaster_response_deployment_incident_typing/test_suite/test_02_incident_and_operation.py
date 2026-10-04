"""Incident lifecycle, operation setup/typing, the offer-requires-OPEN gate,
after-action-review segregation of duties, and OCC-guarded writes."""
from test_helpers import (
    ApiErrorId,
    assert_incident,
    assert_operation,
    create_operation,
    demobe_deployment,
    get_incident,
    get_operation,
    intake_work_order,
    make_deployable_volunteer,
    offer_deployment_payload,
    set_clock,
    setup_assessed_incident,
    setup_typed_incident,
    setup_two_volunteer_operation,
    transition_incident,
    transition_operation,
    validate_error,
    validate_success,
)


def test_incident_terminal_closed_rejects_transitions(api, incident_commander_headers):
    """PRD §2.6: "6. **State legality.** The target entity must be in a from-state for the requested transition; repeated transitions and transitions out of terminal states are rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.8: "Closing the incident — `STANDING_DOWN` to the terminal `CLOSED` state — is then permitted only once every operation of the incident rests in a terminal state, `COMPLETE` or `CANCELLED`."

    Design: Corner/state_machines/incident_closed_terminal_rejected
    """
    set_clock()
    incident = setup_typed_incident(
        incident_type="FLOOD", name="Storm A", severity=3, affected_households=40,
    )
    transition_incident(incident["id"], status="STANDING_DOWN")
    closed = transition_incident(incident["id"], status="CLOSED")
    assert_incident(closed)
    assert closed["status"] == "CLOSED"
    resp = api.patch_incident(
        incident["id"],
        {"status": "ASSESSED", "severity": 5, "affected_households": 99},
        incident_commander_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_incident(incident["id"])
    assert after["status"] == "CLOSED"
    assert after["severity"] == 3


def test_operation_created_in_draft_with_empty_gap(api, incident_commander_headers):
    """PRD §3.3: "A new operation stands in `DRAFT` with `aar_status` `NONE`, `rostered_count` 0, and an empty `capability_gap` until volunteers are rostered against it."

    Design: Corner/state_machines/operation_initial_state_is_draft
    """
    set_clock()
    incident = setup_typed_incident()
    resp = api.create_operation(
        incident["id"],
        {
            "title": "Fresh Op",
            "hazard_focus": "DEBRIS",
            "team_size_required": 2,
            "duration_days": 3,
            "required_capabilities": ["HEAVY_EQUIPMENT"],
            "start_date": "2026-09-15",
        },
        incident_commander_headers,
    )
    data = validate_success(resp, 201)
    assert_operation(data)
    assert data["status"] == "DRAFT"
    assert data["aar_status"] == "NONE"
    assert data["rostered_count"] == 0
    assert data["capability_gap"] == {}


def test_deployment_offer_rejected_while_operation_draft(api, operations_lead_headers):
    """PRD §3.4: "Offering against an operation that is not `OPEN` is rejected with `ERR_OPERATION_NOT_OPEN` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/deployment_offer_requires_open_operation
    """
    set_clock()
    volunteer = make_deployable_volunteer()
    incident = setup_typed_incident()
    operation = create_operation(incident["id"])
    assert operation["status"] == "DRAFT"
    resp = api.offer_deployment(
        operation["id"],
        offer_deployment_payload(volunteer_id=volunteer["id"]),
        operations_lead_headers,
    )
    validate_error(resp, ApiErrorId.ERR_OPERATION_NOT_OPEN)


def test_deployment_offer_succeeds_once_operation_open(api, operations_lead_headers):
    """PRD §3.4: "When an operation is `OPEN`, an `OperationsLead` issues call-up offers, one deployment per volunteer" and "A created offer stands in `OFFERED`."

    Design: Difficulty/cross_entity_state_dependency/deployment_offer_requires_open_operation
    """
    set_clock()
    volunteer = make_deployable_volunteer()
    incident = setup_typed_incident()
    operation = create_operation(incident["id"])
    operation = transition_operation(operation["id"], status="OPEN")
    resp = api.offer_deployment(
        operation["id"],
        offer_deployment_payload(volunteer_id=volunteer["id"]),
        operations_lead_headers,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "OFFERED"
    assert data["operation_id"] == operation["id"]
    assert data["volunteer_id"] == volunteer["id"]


def test_aar_segregation_submit_cannot_adopt(
    api, operations_lead_headers, incident_commander_headers,
):
    """PRD §3.8: "An `OperationsLead` submits the review — `NONE` to `SUBMITTED` — while the operation is `ACTIVE` or `DEMOBILIZING`, carrying a non-empty `aar_notes` body; the server records the submitting role in `aar_submitted_by_role`."
    PRD §3.8: "Adoption is deliberately someone else's job: an `IncidentCommander` moves `SUBMITTED` to the terminal `ADOPTED` state, and the segregation-of-duties rule requires the adopting role to differ from the role recorded in `aar_submitted_by_role` — a submission by an `OperationsLead` cannot be adopted by an `OperationsLead`, and the attempt fails authorization with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.8: "Moving from `DEMOBILIZING` to the terminal `COMPLETE` state demands two things: the after-action review must be `ADOPTED`, else `ERR_AAR_NOT_ADOPTED` (HTTP 409), and no deployment of the operation may remain in `ON_SITE` or `SAFETY_HOLD`."

    Design: Corner/endpoints/aar_segregation_submit_cannot_adopt
    """
    bundle = setup_two_volunteer_operation()
    operation_id = bundle["operation"]["id"]
    resp = api.patch_operation(
        operation_id,
        {"aar_status": "SUBMITTED", "aar_notes": "Smooth demob; one near-miss logged."},
        operations_lead_headers,
    )
    operation = validate_success(resp, 200)
    assert operation["aar_status"] == "SUBMITTED"
    assert operation["aar_submitted_by_role"] == "OperationsLead"
    validate_success(api.patch_operation(operation_id, {"status": "DEMOBILIZING"}, operations_lead_headers), 200)
    # Clear the on-site deployment so that only the AAR gate can fail below.
    demobe_deployment(bundle["d1"]["id"])
    resp = api.patch_operation(operation_id, {"status": "COMPLETE"}, operations_lead_headers)
    validate_error(resp, ApiErrorId.ERR_AAR_NOT_ADOPTED)
    resp = api.patch_operation(operation_id, {"aar_status": "ADOPTED"}, operations_lead_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    operation = validate_success(
        api.patch_operation(operation_id, {"aar_status": "ADOPTED"}, incident_commander_headers),
        200,
    )
    assert operation["aar_status"] == "ADOPTED"
    operation = validate_success(
        api.patch_operation(operation_id, {"status": "COMPLETE"}, operations_lead_headers), 200,
    )
    assert operation["status"] == "COMPLETE"


def test_retype_with_stale_version_rejected(api, operations_lead_headers):
    """PRD §2.7: "Re-typing an operation requires the request to carry `expected_operation_version`, holding the `version` of the `Operation` the client last observed. If the operation's version has advanced since that observation — because another writer has already applied a typing change — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a stale view from silently overwriting a typing the client never saw."

    Design: Corner/cross_cutting_layers/occ_retype_stale_version_rejected
    """
    set_clock()
    incident = setup_typed_incident()
    operation = create_operation(incident["id"])
    observed_at_create = operation["version"]
    opened = transition_operation(operation["id"], status="OPEN")
    resp = api.retype_operation(
        operation["id"],
        {
            "expected_operation_version": observed_at_create,
            "team_size_required": 3,
            "duration_days": 5,
            "required_capabilities": ["CHAINSAW"],
        },
        operations_lead_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = get_operation(operation["id"])
    assert after["team_size_required"] == 2
    assert after["duration_days"] == 4
    assert after["version"] == opened["version"]


def test_retype_with_current_version_applies_and_increments(api, operations_lead_headers):
    """PRD §3.3: "An `OperationsLead` may re-type an operation while it is in `DRAFT` or `OPEN`, replacing `team_size_required`, `duration_days`, and `required_capabilities` in one write and recomputing the `capability_gap` against the new requirements."
    PRD §3.3: "A successful retype increments the operation's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_retype_stale_version_rejected
    """
    set_clock()
    incident = setup_typed_incident()
    operation = create_operation(incident["id"])
    opened = transition_operation(operation["id"], status="OPEN")
    resp = api.retype_operation(
        operation["id"],
        {
            "expected_operation_version": opened["version"],
            "team_size_required": 3,
            "duration_days": 5,
            "required_capabilities": ["CHAINSAW"],
        },
        operations_lead_headers,
    )
    data = validate_success(resp, 200)
    assert_operation(data)
    assert data["team_size_required"] == 3
    assert data["duration_days"] == 5
    assert data["required_capabilities"] == ["CHAINSAW"]
    assert data["version"] == opened["version"] + 1


def test_first_triage_applies_and_bumps_version(api, intake_coordinator_headers):
    """PRD §3.6: "A successful triage moves `INTAKE` to `TRIAGED` and stamps both priority fields."
    PRD §2.7: "Triaging a work order works the same way: the request must carry `expected_work_order_version` matching the work order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_triage_stale_version_rejected
    """
    set_clock()
    incident = setup_assessed_incident(severity=3, affected_households=40, name="Storm A")
    work_order = intake_work_order(
        incident["id"], requester_name="Owner One", hazard_kind="TARPING",
        vulnerable_resident=False,
    )
    resp = api.triage_work_order(
        work_order["id"],
        {"expected_work_order_version": work_order["version"]},
        intake_coordinator_headers,
    )
    data = validate_success(resp, 200)
    assert data["status"] == "TRIAGED"
    assert data["version"] == work_order["version"] + 1
    assert data["priority_score"] is not None
    assert data["priority_tier"] is not None


def test_second_triage_with_stale_version_rejected(api, intake_coordinator_headers):
    """PRD §2.7: "the request must carry `expected_work_order_version` matching the work order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A second triage legitimately supersedes an earlier priority verdict, so the version check is what tells the client a superseding triage already landed."
    PRD §2.6: "When a single request violates several rules, exactly one error is returned, chosen by a fixed validation priority — lower priority numbers win. The ordering is:" followed by "5. **Optimistic concurrency.**" ahead of "6. **State legality.**".

    Design: Corner/cross_cutting_layers/occ_triage_stale_version_rejected
    """
    set_clock()
    incident = setup_assessed_incident(severity=3, affected_households=40, name="Storm A")
    work_order = intake_work_order(
        incident["id"], requester_name="Owner One", hazard_kind="TARPING",
        vulnerable_resident=False,
    )
    observed_version = work_order["version"]
    validate_success(
        api.triage_work_order(
            work_order["id"], {"expected_work_order_version": observed_version},
            intake_coordinator_headers,
        ),
        200,
    )
    resp = api.triage_work_order(
        work_order["id"],
        {"expected_work_order_version": observed_version},
        intake_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
