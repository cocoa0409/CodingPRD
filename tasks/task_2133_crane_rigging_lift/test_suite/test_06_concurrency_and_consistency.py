"""Optimistic concurrency on the three guarded writes, the version/timestamp
contract, and the immediate visibility of cascade effects."""

import pytest

from test_helpers import (
    ApiErrorId,
    BILLING_CLERK,
    DISPATCHER,
    SAFETY_MANAGER,
    build_standard_world,
    commit_gear,
    configure_body,
    create_gear_assignment_payload,
    is_iso8601_timestamp,
    new_customer,
    open_plan,
    read_crane,
    read_gear,
    read_invoice,
    read_plan,
    setup_closed_standard_job,
    survey_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_configure_carrying_the_pre_survey_version_is_rejected(api):
    """PRD 2.5: "Configuring a lift plan must carry `expected_lift_plan_version` as a
    required, non-optional field whose value is the plan's `version` as the client
    last read it."
    PRD 2.5: "If `expected_lift_plan_version` does not equal the plan's current
    `version`, the request is rejected with `ERR_STALE_PLAN_VERSION` and HTTP status
    412."
    PRD 3.3: "Because the survey writes onto the plan as well as the site, the plan's
    `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_lift_plan_version_on_configure_returns_412
    """
    world = build_standard_world()
    plan = open_plan(world, job_reference="JOB-9800")
    assert plan["version"] == 1
    surveyed = survey_plan(world, plan["id"])
    assert surveyed["version"] == 2
    commit_gear(world, plan["id"])

    stale = configure_body(world, plan["version"])
    validate_error(api.configure_lift_plan(plan["id"], stale, DISPATCHER),
                   ApiErrorId.ERR_STALE_PLAN_VERSION.value, 412)

    fresh = configure_body(world, surveyed["version"])
    configured = validate_success(api.configure_lift_plan(plan["id"], fresh, DISPATCHER))
    assert configured["plan_status"] == "CONFIGURED"
    assert configured["version"] == 3
    assert read_crane(world["crane_id"])["reserved_hours_total"] == pytest.approx(10.0)


def test_a_commitment_carrying_the_pre_inspection_gear_version_is_rejected(api):
    """PRD 2.5: "Committing a piece of rigging gear to a plan requires
    `expected_gear_version` matching that gear item's current `version`. The gear's
    derate, its inspection posture and its commitment ledger all move its `version`,
    and the assignment permanently snapshots the gear's working load limit at commit
    time — so a stale writer would freeze an obsolete limit onto the plan. A mismatch
    is `ERR_STALE_GEAR_VERSION` with HTTP status 412."
    PRD 3.4: "Creating the commitment recomputes the gear item's
    `committed_assignment_count` and increments that gear item's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_gear_version_on_gear_assignment_returns_412
    """
    world = build_standard_world(serviceable_gear=False)
    plan = open_plan(world, job_reference="JOB-9801")
    survey_plan(world, plan["id"])

    stale_version = world["gear"]["version"]
    assert stale_version == 1
    validate_success(api.create_gear_inspection(
        {"gear_id": world["gear_id"], "result": "PASS", "inspector_note": "acceptance"},
        SAFETY_MANAGER), 201)
    current_version = read_gear(world["gear_id"])["version"]
    assert current_version == 2

    validate_error(api.create_gear_assignment(
        create_gear_assignment_payload(plan["id"], world["gear_id"], stale_version),
        DISPATCHER), ApiErrorId.ERR_STALE_GEAR_VERSION.value, 412)

    assignment = validate_success(api.create_gear_assignment(
        create_gear_assignment_payload(plan["id"], world["gear_id"], current_version),
        DISPATCHER), 201)
    assert assignment["status"] == "ACTIVE"

    gear = read_gear(world["gear_id"])
    assert gear["committed_assignment_count"] == 1
    assert gear["version"] == 3


def test_a_second_invoice_on_a_stale_plan_version_never_retires_the_first_draft(api):
    """PRD 2.5: "Creating an invoice likewise requires `expected_lift_plan_version`
    matching the target lift plan's current `version`. A newly created invoice voids
    any prior draft invoice on the same plan, so a caller holding a stale view would
    retire a bill it never observed. A mismatch is again `ERR_STALE_PLAN_VERSION` with
    HTTP status 412."
    PRD 3.9: "On creation the invoice copies `customer_id` from the plan's
    `customer_id`, snapshots the plan's `standby_hours_billable` into its own
    `standby_hours_source`, opens at `DRAFT`, causes the plan's `invoice_count` to be
    recomputed and the plan's `version` to increment"

    Design: Corner/cross_cutting_complexity_layers/stale_expected_lift_plan_version_on_invoice_create_returns_412
    """
    world = build_standard_world()
    ctx = setup_closed_standard_job(world, with_standby=False,
                                    plan_overrides={"job_reference": "JOB-9802"})
    stale_version = ctx["plan_version"]

    first = validate_success(api.create_invoice(
        {"lift_plan_id": ctx["plan_id"], "billing_mode": "HOURLY", "on_site_hours": 2.5,
         "travel_hours": 1.0, "travel_miles": 0.0,
         "expected_lift_plan_version": stale_version}, BILLING_CLERK), 201)

    validate_error(api.create_invoice(
        {"lift_plan_id": ctx["plan_id"], "billing_mode": "HOURLY", "on_site_hours": 12.0,
         "travel_hours": 2.0, "travel_miles": 30.0,
         "expected_lift_plan_version": stale_version}, BILLING_CLERK),
        ApiErrorId.ERR_STALE_PLAN_VERSION.value, 412)

    assert read_invoice(first["id"])["status"] == "DRAFT", (
        "a rejected create must not supersede the standing draft"
    )
    _, meta = validate_paginated(
        api.list_invoices(BILLING_CLERK, params={"lift_plan_id": ctx["plan_id"]}))
    assert meta["total_count"] == 1
    assert read_plan(ctx["plan_id"])["invoice_count"] == 1


def test_version_climbs_by_exactly_one_per_mutation_while_created_at_holds(api):
    """PRD 2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    with exactly three fractional-second digits, recorded at the instant the row is
    first persisted and never changed afterwards."
    PRD 2.4: "Most resources additionally carry `updated_at` — same ISO 8601 UTC
    format with three fractional digits, refreshed on every mutation of that row — and
    `version`, an integer that begins at 1 when the row is created and increases by
    exactly 1 on every mutation of that row."
    PRD 3.1: "Clearing a hold leaves `credit_hold_reason` null."

    Design: Corner/cross_cutting_complexity_layers/version_increments_by_one_on_every_mutation
    """
    customer = new_customer(account_name="Northgate Industrial")
    assert customer["version"] == 1

    held = validate_success(api.set_credit_status(
        customer["id"], {"credit_hold": True, "reason": "aged receivable"}, BILLING_CLERK))
    assert held["version"] == 2
    assert is_iso8601_timestamp(held["updated_at"])

    cleared = validate_success(api.set_credit_status(
        customer["id"], {"credit_hold": False}, BILLING_CLERK))
    assert cleared["version"] == 3
    assert cleared["created_at"] == customer["created_at"]
    assert cleared["credit_hold"] is False


def test_cascade_effects_are_already_visible_in_the_triggering_response(api):
    """PRD 3.2: "The inspection record is append-only: it stamps `inspected_at` with
    the logical clock, records the `resulting_status` it drove the gear to, and
    snapshots `repair_count_after` — the gear's repair tally immediately after this
    inspection was applied."
    PRD 3.2: "The second hop voids every commitment of that gear that was still
    active, moving each to `VOIDED` and recomputing the gear's
    `committed_assignment_count`."
    PRD 3.4: "Commitments can be listed and narrowed by `lift_plan_id`, `gear_id` and
    `status`."

    Design: Corner/consistency_model/cascade_effects_are_visible_in_the_same_response
    """
    world = build_standard_world()
    plan = open_plan(world, job_reference="JOB-9900")
    survey_plan(world, plan["id"])
    assignment = commit_gear(world, plan["id"])

    inspection = validate_success(api.create_gear_inspection(
        {"gear_id": world["gear_id"], "result": "FAIL",
         "inspector_note": "core protrusion"}, SAFETY_MANAGER), 201)
    assert inspection["resulting_status"] == "QUARANTINED"

    gear = read_gear(world["gear_id"])
    assert gear["status"] == "QUARANTINED"
    assert gear["committed_assignment_count"] == 0

    voided, voided_meta = validate_paginated(api.list_gear_assignments(
        DISPATCHER, params={"gear_id": world["gear_id"], "status": "VOIDED"}))
    assert voided_meta["total_count"] == 1
    assert voided[0]["id"] == assignment["id"]

    _, active_meta = validate_paginated(api.list_gear_assignments(
        DISPATCHER, params={"lift_plan_id": plan["id"], "status": "ACTIVE"}))
    assert active_meta["total_count"] == 0
