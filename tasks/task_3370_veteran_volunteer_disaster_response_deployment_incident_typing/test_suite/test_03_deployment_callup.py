"""Deployment call-up: offer ceiling, accept gates (cert, rest buffer),
repeated-transition rejection, the no-show sweep, and validation priority
between terminal state and the safety-credential gate."""
from test_helpers import (
    ApiErrorId,
    add_certification,
    create_operation,
    decline_deployment,
    demobe_deployment,
    get_deployment,
    get_operation,
    make_deployable_volunteer,
    make_volunteer_headers,
    offer_deployment,
    offer_deployment_payload,
    register_volunteer,
    run_ops_epoch,
    set_clock,
    setup_accepted_deployment,
    setup_on_site_deployment,
    setup_open_operation,
    transition_operation,
    transition_volunteer,
    validate_error,
    validate_paginated,
    validate_success,
    verify_certification,
)


def test_deployment_double_accept_rejected(api):
    """PRD §2.6: "6. **State legality.** The target entity must be in a from-state for the requested transition; repeated transitions and transitions out of terminal states are rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/deployment_double_accept_rejected
    """
    bundle = setup_accepted_deployment()
    deployment_id = bundle["deployment"]["id"]
    assert bundle["deployment"]["status"] == "ACCEPTED"
    resp = api.patch_deployment(
        deployment_id, {"status": "ACCEPTED"},
        make_volunteer_headers(bundle["volunteer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_deployment(deployment_id)
    assert after["status"] == "ACCEPTED"


def test_offer_ceiling_rejects_offer_beyond_team_size(api, operations_lead_headers):
    """PRD §3.4: "the offer ceiling fires second, rejecting with `ERR_TEAM_SIZE_EXCEEDED` (HTTP 422) when the operation's active offers — deployments in `OFFERED`, `ACCEPTED`, `ON_SITE`, or `SAFETY_HOLD` — already number `team_size_required`, so that the offer that would exceed the ceiling is the one refused."

    Design: Corner/validations/offer_ceiling_third_offer_rejected
    """
    set_clock()
    volunteers = [
        make_deployable_volunteer(full_name=name, email=email, skills=["CHAINSAW"])
        for name, email in [
            ("Ada Voss", "ada@x.org"), ("Bo Karr", "bo@x.org"), ("Cy Daly", "cy@x.org"),
        ]
    ]
    _incident, operation = setup_open_operation()
    offer_deployment(operation["id"], volunteers[0]["id"])
    offer_deployment(operation["id"], volunteers[1]["id"])
    resp = api.offer_deployment(
        operation["id"],
        offer_deployment_payload(volunteer_id=volunteers[2]["id"]),
        operations_lead_headers,
    )
    validate_error(resp, ApiErrorId.ERR_TEAM_SIZE_EXCEEDED)
    items, meta = validate_paginated(
        api.list_deployments(operations_lead_headers, params={"operation_id": operation["id"]})
    )
    assert len(items) == 2
    assert meta["total_count"] == 2


def test_accept_with_pending_required_cert_rejected(api):
    """PRD §3.4: "After the generic schema, auth, existence, and state checks, the safety-credential gate requires the volunteer to hold at least one `VERIFIED` certification whose kind appears in the operation's `required_capabilities`, else `ERR_CERT_NOT_VERIFIED` (HTTP 422)."

    Design: Corner/validations/accept_with_pending_cert_rejected
    """
    set_clock()
    volunteer = register_volunteer(
        full_name="Med Mary", email="mary@x.org", skills=["MEDICAL", "CHAINSAW"],
    )
    medical = add_certification(volunteer["id"], kind="MEDICAL")
    verify_certification(medical["id"])
    add_certification(volunteer["id"], kind="CHAINSAW")  # stays PENDING_VERIFICATION
    transition_volunteer(volunteer["id"], "VETTED")
    transition_volunteer(volunteer["id"], "DEPLOYABLE")
    _incident, operation = setup_open_operation(required_capabilities=["CHAINSAW"])
    deployment = offer_deployment(operation["id"], volunteer["id"])
    resp = api.patch_deployment(
        deployment["id"], {"status": "ACCEPTED"}, make_volunteer_headers(volunteer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CERT_NOT_VERIFIED)
    after = get_deployment(deployment["id"])
    assert after["status"] == "OFFERED"


def test_no_show_sweep_marks_unresponsive_accepted_deployment(api):
    """PRD §3.4: "A volunteer who never shows is caught by the ops run: a deployment still `ACCEPTED` once `current_utc` has passed the operation's `start_date` by more than the 24-hour grace flips to the terminal `NO_SHOW` state, with the operation's counters recomputed."
    PRD §3.3: "`rostered_count` counts the operation's deployments in `ACCEPTED` or `ON_SITE` — `SAFETY_HOLD` is deliberately excluded."

    Design: Corner/state_machines/deployment_no_show_sweep
    """
    bundle = setup_accepted_deployment(
        volunteer_overrides={"full_name": "Ghost Gus", "email": "gus@x.org"},
    )
    set_clock("2026-09-12T00:01:00Z")
    run_ops_epoch()
    deployment = get_deployment(bundle["deployment"]["id"])
    assert deployment["status"] == "NO_SHOW"
    operation = get_operation(bundle["operation"]["id"])
    assert operation["rostered_count"] == 0


def _setup_demobed_exactly_at_planned_end():
    """v1 DEPLOYABLE; d1 under op1 ON_SITE then DEMOBED at a clock exactly equal
    to its planned_end, so the deployment's window end is the same instant
    whether read as planned_end or as demobed_at: 2026-09-12T08:00:00Z.
    op2 under the same TYPED incident is OPEN for follow-on offers."""
    bundle = setup_on_site_deployment(
        offer_overrides={
            "planned_start": "2026-09-10T08:00:00Z",
            "planned_end": "2026-09-12T08:00:00Z",
        },
    )
    set_clock("2026-09-12T08:00:00Z")
    bundle["deployment"] = demobe_deployment(bundle["deployment"]["id"])
    op2 = create_operation(
        bundle["incident"]["id"],
        title="Helena Tree Ops II", duration_days=2, start_date="2026-09-14",
    )
    bundle["op2"] = transition_operation(op2["id"], status="OPEN")
    return bundle


def test_rest_buffer_rejects_restart_inside_24_hours(api):
    """PRD §3.4: "Then the rest buffer: no other deployment of the same volunteer in `ACCEPTED`, `ON_SITE`, `SAFETY_HOLD`, or `DEMOBED` may have its window ending within 24 hours (`REST_BUFFER_HOURS`) before the new `planned_start` — a gap of at least 24 hours is required, and a gap of exactly 24 hours is admissible — else `ERR_DEPLOYMENT_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/deployment_window_rest_buffer_gap
    """
    bundle = _setup_demobed_exactly_at_planned_end()
    volunteer_id = bundle["volunteer"]["id"]
    deployment = offer_deployment(
        bundle["op2"]["id"], volunteer_id,
        planned_start="2026-09-13T07:00:00Z", planned_end="2026-09-15T08:00:00Z",
    )
    resp = api.patch_deployment(
        deployment["id"], {"status": "ACCEPTED"}, make_volunteer_headers(volunteer_id)
    )
    validate_error(resp, ApiErrorId.ERR_DEPLOYMENT_WINDOW_CONFLICT)
    after = get_deployment(deployment["id"])
    assert after["status"] == "OFFERED"


def test_rest_buffer_admits_exactly_24_hour_gap(api):
    """PRD §3.4: "a gap of at least 24 hours is required, and a gap of exactly 24 hours is admissible — else `ERR_DEPLOYMENT_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/deployment_window_rest_buffer_gap
    """
    bundle = _setup_demobed_exactly_at_planned_end()
    volunteer_id = bundle["volunteer"]["id"]
    deployment = offer_deployment(
        bundle["op2"]["id"], volunteer_id,
        planned_start="2026-09-13T08:00:00Z", planned_end="2026-09-15T08:00:00Z",
    )
    data = validate_success(
        api.patch_deployment(
            deployment["id"], {"status": "ACCEPTED"}, make_volunteer_headers(volunteer_id)
        ),
        200,
    )
    assert data["status"] == "ACCEPTED"


def _setup_offer_with_revoked_cert(api, safety_officer_headers, decline_first):
    """DEPLOYABLE volunteer (single VERIFIED CHAINSAW cert) + OPEN operation +
    OFFERED deployment; optionally the volunteer declines; then the cert is
    revoked. Returns (volunteer, operation, deployment)."""
    set_clock()
    volunteer = make_deployable_volunteer()
    _incident, operation = setup_open_operation()
    deployment = offer_deployment(operation["id"], volunteer["id"])
    if decline_first:
        decline_deployment(deployment["id"], volunteer["id"])
    certs, _meta = validate_paginated(
        api.list_certifications(safety_officer_headers, params={"volunteer_id": volunteer["id"]})
    )
    validate_success(
        api.patch_certification(certs[0]["id"], {"status": "REVOKED"}, safety_officer_headers),
        200,
    )
    return volunteer, operation, deployment


def test_terminal_state_beats_cert_gate_on_accept(api, safety_officer_headers):
    """PRD §2.6: "When a single request violates several rules, exactly one error is returned, chosen by a fixed validation priority — lower priority numbers win." with "6. **State legality.** The target entity must be in a from-state for the requested transition; repeated transitions and transitions out of terminal states are rejected with `ERR_INVALID_STATE` (HTTP 409)." ahead of "7. **Business rules.** Domain rules follow in their own pinned order, detailed in §3: credential and readiness safety gates first, then instructor eligibility, then temporal rules (availability containment, rest buffer, shift overlap), then capacity and coverage constraints (fatigue cap, capability coverage, hazard alignment, offer ceiling, duplicate enrollment), then referential gates (operation state, incident typing, wind-down gates), and finally lodging capacity."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_terminal_accept
    """
    volunteer, _operation, deployment = _setup_offer_with_revoked_cert(
        api, safety_officer_headers, decline_first=True,
    )
    resp = api.patch_deployment(
        deployment["id"], {"status": "ACCEPTED"}, make_volunteer_headers(volunteer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_deployment(deployment["id"])
    assert after["status"] == "DECLINED"


def test_cert_gate_fires_when_state_legal(api, safety_officer_headers):
    """PRD §3.4: "After the generic schema, auth, existence, and state checks, the safety-credential gate requires the volunteer to hold at least one `VERIFIED` certification whose kind appears in the operation's `required_capabilities`, else `ERR_CERT_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_terminal_accept
    """
    volunteer, _operation, deployment = _setup_offer_with_revoked_cert(
        api, safety_officer_headers, decline_first=False,
    )
    resp = api.patch_deployment(
        deployment["id"], {"status": "ACCEPTED"}, make_volunteer_headers(volunteer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CERT_NOT_VERIFIED)
    after = get_deployment(deployment["id"])
    assert after["status"] == "OFFERED"
