"""Prescription workflow: send gating, supersession, as-applied reports, and
grower-only approval."""

import pytest

from test_helpers import (
    ApiErrorId,
    AGRONOMIST_USER_ID,
    add_active_field,
    add_machine,
    add_sent_prescription,
    approve_prescription,
    create_grant,
    create_prescription,
    create_prescription_payload,
    make_agronomist_headers,
    prescription_zone,
    read_field,
    read_prescription,
    report_as_applied,
    same_instant,
    send_prescription,
    setup_connected_machine,
    setup_org_dealer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_prescription_send_from_draft_rejected(api):
    """PRD section 3.3: sending "moves `APPROVED` → `SENT`" — the transition
    does not exist from `DRAFT`, so sending a draft prescription is a
    state-precondition failure (`ERR_INVALID_STATE_TRANSITION`, PRD section
    2.10 step 6).

    Design: Corner/state_machines/prescription_send_from_draft_rejected
    """
    ctx = setup_connected_machine(api)
    field = add_active_field(ctx, api)
    rx = create_prescription(ctx, api, field["id"], ctx["machine"]["id"])

    response = api.send_prescription_to_machine(
        rx["id"], headers=ctx["grower_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    rx = read_prescription(ctx, api, rx["id"])
    assert rx["status"] == "DRAFT"


def test_send_supersedes_prior_sent_prescription_of_same_field(api):
    """PRD section 3.3: "Sending is also the supersession point: every other
    prescription of the same field currently `SENT` transitions to `SUPERSEDED`
    with its `superseded_by_id` set to the newly sent prescription."

    Design: Corner/state_machines/send_supersedes_prior_sent_prescription_of_same_field
    """
    ctx = setup_connected_machine(api)
    field = add_active_field(ctx, api)
    machine_id = ctx["machine"]["id"]

    rx_a = add_sent_prescription(ctx, api, field["id"], machine_id)
    assert rx_a["status"] == "SENT"

    rx_b = create_prescription(
        ctx, api, field["id"], machine_id,
        crop_type="SOY",
        zones=[prescription_zone("z1", rate_l_per_ha=3.20, area_ha=10.00)],
    )
    approve_prescription(ctx, api, rx_b["id"])
    rx_b = send_prescription(ctx, api, rx_b["id"])
    assert rx_b["status"] == "SENT"

    rx_a = read_prescription(ctx, api, rx_a["id"])
    assert rx_a["status"] == "SUPERSEDED"
    assert rx_a["superseded_by_id"] == rx_b["id"]

    rows, _meta = validate_paginated(
        api.list_prescriptions(
            headers=ctx["grower_headers"],
            params={"field_boundary_id": field["id"], "status": "SENT"},
        )
    )
    assert len(rows) == 1
    assert rows[0]["id"] == rx_b["id"]


def test_report_as_applied_acknowledges_prescription(api):
    """PRD section 3.3: "That `System`-side report moves a `SENT` prescription
    to `ACKNOWLEDGED` and records the as-applied `applied_total_liters`,
    `applied_coverage_ha`, and the `applied_at` timestamp — closing the loop
    between the office plan and the field reality."

    Design: Corner/state_machines/report_as_applied_acknowledges_prescription
    """
    ctx = setup_connected_machine(api)
    field = add_active_field(ctx, api)
    rx = add_sent_prescription(ctx, api, field["id"], ctx["machine"]["id"])

    rx = report_as_applied(
        api, rx["id"], applied_total_liters=29.50, applied_coverage_ha=9.80
    )
    assert rx["status"] == "ACKNOWLEDGED"
    assert rx["applied_total_liters"] == pytest.approx(29.50, abs=1e-9)
    assert rx["applied_coverage_ha"] == pytest.approx(9.80, abs=1e-9)
    assert same_instant(rx["applied_at"], "2026-09-01T00:00:00Z")


def test_agronomist_cannot_approve_prescription(api):
    """PRD section 3.3: "Approval is grower-only: a `GrowerManager` moves a
    `DRAFT` prescription to `APPROVED`." and PRD section 2.1: "a caller whose
    role is not in that endpoint's list is rejected with
    `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)". The agronomist's grant-gated create
    is legal; the approval is not.

    Design: Corner/rbac/agronomist_cannot_approve_prescription
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    field = add_active_field(ctx, api)
    create_grant(
        ctx, api, grantee_type="AGRONOMIST", grantee_ref_id=AGRONOMIST_USER_ID,
        scopes=["AGRONOMIC"],
    )
    version = read_field(ctx, api, field["id"])["version"]
    payload = create_prescription_payload(
        ctx["org"]["id"], field["id"], machine["id"], version,
        crop_type="WHEAT",
        zones=[prescription_zone("z1", rate_l_per_ha=2.00, area_ha=8.00)],
    )
    response = api.create_prescription(
        payload, headers=make_agronomist_headers(AGRONOMIST_USER_ID)
    )
    rx = validate_success(response, 201)

    response = api.approve_prescription(
        rx["id"], headers=make_agronomist_headers(AGRONOMIST_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    rx = read_prescription(ctx, api, rx["id"])
    assert rx["status"] == "DRAFT"
