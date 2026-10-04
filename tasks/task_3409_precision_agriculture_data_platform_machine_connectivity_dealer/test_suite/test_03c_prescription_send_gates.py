"""Prescription send gates: section-control licensing, temporal window, and
machine posture; plus the approve/revise revision loop."""

import pytest

from test_helpers import (
    ApiErrorId,
    activate_license,
    add_active_field,
    add_approved_prescription,
    add_machine,
    approve_prescription,
    create_prescription,
    prescription_zone,
    purchase_license,
    read_machine,
    read_prescription,
    resume_plan,
    revise_prescription,
    send_prescription,
    set_clock,
    setup_activated_machine,
    setup_connected_machine,
    setup_org_dealer,
    suspend_plan,
    validate_error,
)


def test_multi_zone_send_requires_section_control_license(api):
    """PRD section 3.3: "when the prescription carries more than one zone, the
    machine must hold a `SECTION_CONTROL` feature license in `ACTIVATED`
    (`ERR_FEATURE_NOT_LICENSED`)". PRD section 3.7: the fee for the machine's
    first license is the undiscounted base, "`SECTION_CONTROL` 180000 cents".

    Design: Corner/validations/multi_zone_send_requires_section_control_license
    """
    ctx = setup_activated_machine(api)
    machine_id = ctx["machine"]["id"]
    field = add_active_field(ctx, api)
    rx = create_prescription(
        ctx, api, field["id"], machine_id,
        crop_type="CORN",
        zones=[
            prescription_zone("z1", rate_l_per_ha=2.55, area_ha=10.00),
            prescription_zone("z2", rate_l_per_ha=3.10, area_ha=5.00),
        ],
    )
    approve_prescription(ctx, api, rx["id"])

    response = api.send_prescription_to_machine(
        rx["id"], headers=ctx["grower_headers"]
    )
    validate_error(response, ApiErrorId.ERR_FEATURE_NOT_LICENSED)

    license = purchase_license(
        ctx, api, machine_id, feature_code="SECTION_CONTROL",
        license_type="PERPETUAL",
    )
    assert license["fee_cents"] == 180000
    activate_license(api, license["id"])

    rx = send_prescription(ctx, api, rx["id"])
    assert rx["status"] == "SENT"


def test_prescription_send_after_valid_until_rejected(api):
    """PRD section 3.3: "the current logical time must be at or before
    `valid_until` (`ERR_PRESCRIPTION_EXPIRED`)" — once the clock passes the
    inclusive window end, the send fails and the prescription stays
    `APPROVED`.

    Design: Corner/validations/prescription_send_after_valid_until_rejected
    """
    ctx = setup_connected_machine(api)
    field = add_active_field(ctx, api)
    rx = create_prescription(
        ctx, api, field["id"], ctx["machine"]["id"],
        valid_from="2026-09-01T00:00:00Z",
        valid_until="2026-09-10T00:00:00Z",
    )
    approve_prescription(ctx, api, rx["id"])

    set_clock(api, "2026-09-11T00:00:00Z")
    response = api.send_prescription_to_machine(
        rx["id"], headers=ctx["grower_headers"]
    )
    validate_error(response, ApiErrorId.ERR_PRESCRIPTION_EXPIRED)
    rx = read_prescription(ctx, api, rx["id"])
    assert rx["status"] == "APPROVED"


def test_prescription_approve_revise_loop_ends_approved_revision_two(api):
    """PRD section 3.3: "If the agronomy needs another pass, a `GrowerManager`
    or an `Agronomist` may revise, returning `APPROVED` → `DRAFT` and
    incrementing `revision` — a revision loop that may repeat." One loop takes
    revision from 1 to 2 and a fresh approval returns the prescription to
    `APPROVED`.

    Design: Difficulty/non_linear_state_machine/prescription_approve_revise_revision_loop
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    field = add_active_field(ctx, api)
    rx = create_prescription(ctx, api, field["id"], machine["id"])

    approve_prescription(ctx, api, rx["id"])
    revise_prescription(ctx, api, rx["id"])
    rx = approve_prescription(ctx, api, rx["id"])
    assert rx["status"] == "APPROVED"
    assert rx["revision"] == 2


def test_prescription_revision_loop_keeps_computed_totals(api):
    """PRD section 3.3: "At creation the platform computes the prescription's
    product totals with a pinned rounding order — per zone first, then sum" —
    the totals are computed at creation, so the approve/revise loop returns
    the same prescription with `total_product_liters` unchanged at 30.00
    (3.00 L/ha x 10.00 ha).

    Design: Difficulty/non_linear_state_machine/prescription_approve_revise_revision_loop
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    field = add_active_field(ctx, api)
    rx = create_prescription(ctx, api, field["id"], machine["id"])

    approve_prescription(ctx, api, rx["id"])
    revise_prescription(ctx, api, rx["id"])
    approve_prescription(ctx, api, rx["id"])

    rx = read_prescription(ctx, api, rx["id"])
    assert rx["revision"] == 2
    assert rx["total_product_liters"] == pytest.approx(30.00, abs=1e-9)


def test_prescription_send_blocked_while_plan_suspended(api):
    """PRD section 3.3: "the machine's `connectivity_posture` must be
    `CONNECTED` (`ERR_MACHINE_POSTURE_BLOCKED`)", and PRD section 3.2:
    suspension "moves an `ACTIVE` plan to `SUSPENDED`, recomputes the machine's
    posture to `PLAN_SUSPENDED`". A send while the plan is suspended fails the
    posture gate.

    Design: Difficulty/cross_entity_state_dependency/prescription_send_gated_by_machine_posture
    """
    ctx = setup_connected_machine(api)
    field = add_active_field(ctx, api)
    rx = add_approved_prescription(ctx, api, field["id"], ctx["machine"]["id"])

    suspend_plan(ctx, api, ctx["plan"]["id"])
    machine = read_machine(ctx, api, ctx["machine"]["id"])
    assert machine["connectivity_posture"] == "PLAN_SUSPENDED"

    response = api.send_prescription_to_machine(
        rx["id"], headers=ctx["grower_headers"]
    )
    validate_error(response, ApiErrorId.ERR_MACHINE_POSTURE_BLOCKED)
    rx = read_prescription(ctx, api, rx["id"])
    assert rx["status"] == "APPROVED"


def test_prescription_send_unblocked_after_plan_resume(api):
    """PRD section 3.2: "Resuming returns a `SUSPENDED` plan to `ACTIVE`,
    again requiring an `ACTIVE` organization (`ERR_ORG_SUSPENDED`) and
    recomputing posture" — with the plan resumed the posture is `CONNECTED`
    again and the same send succeeds, moving the prescription `APPROVED` →
    `SENT` (PRD section 3.3).

    Design: Difficulty/cross_entity_state_dependency/prescription_send_gated_by_machine_posture
    """
    ctx = setup_connected_machine(api)
    field = add_active_field(ctx, api)
    rx = add_approved_prescription(ctx, api, field["id"], ctx["machine"]["id"])

    suspend_plan(ctx, api, ctx["plan"]["id"])
    response = api.send_prescription_to_machine(
        rx["id"], headers=ctx["grower_headers"]
    )
    validate_error(response, ApiErrorId.ERR_MACHINE_POSTURE_BLOCKED)

    resume_plan(ctx, api, ctx["plan"]["id"])
    rx = send_prescription(ctx, api, rx["id"])
    assert rx["status"] == "SENT"
