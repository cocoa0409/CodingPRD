"""Corner queue B: cross-cutting layers (OCC, cascades, tenancy, flags) and
immediate consistency."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    admin_of,
    dev_headers,
    op_headers,
    ApiErrorId,
    activate_definition,
    add_step,
    create_active_connector,
    create_active_unit,
    create_definition,
    create_group,
    create_group_with_member,
    create_run,
    create_tenant,
    create_worker,
    initiate,
    set_clock,
    setup_active_definition,
    setup_tenant_with_group,
)


def test_occ_tenant_update_stale_version(api):
    """PRD §2.5: "Updating a tenant's configuration requires the request to
    carry `expected_tenant_version` matching the tenant's current `version`;
    if another writer — or a cascaded side effect such as a suspension, a
    retirement, or a membership invalidation that changed derived counts — has
    advanced the tenant's version since the client last read it, the update is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "A successful update increments the tenant's `version` by 1 and
    refreshes `updated_at`."

    Design: Corner/cross_cutting_layers/occ_tenant_update_stale_version
    """
    tenant = create_tenant("T-OCC1")
    admin = admin_of(tenant)
    v1 = tenant["version"]

    updated = get_success_data(api_client.update_tenant(
        tenant["id"],
        {"expected_tenant_version": v1, "maintenance_slot_utc": 3},
        admin,
    ))
    assert updated["version"] == v1 + 1
    assert updated["maintenance_slot_utc"] == 3

    # Replay with the now-stale version.
    resp = api_client.update_tenant(
        tenant["id"],
        {"expected_tenant_version": v1, "maintenance_slot_utc": 4},
        admin,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    tenant = get_success_data(api_client.get_tenant(tenant["id"], admin))
    assert tenant["maintenance_slot_utc"] == 3, "the stale write must not apply"
    assert tenant["version"] == v1 + 1


def test_occ_definition_activate_stale_version(api):
    """PRD §2.5: "Activating a business process definition requires the request
    to carry `expected_definition_version` matching the definition's current
    `version`; a version that has moved since the client last observed the
    definition means another writer has edited the step list — for example
    adding or removing an `APPROVAL` step — so the activation is rejected with
    `ERR_STALE_VERSION` (HTTP 412) rather than letting the client activate a
    definition it has not observed."

    Design: Corner/cross_cutting_layers/occ_definition_activate_stale_version
    """
    ctx = setup_tenant_with_group("T-OCC2")
    tid, admin = ctx["tenant"]["id"], ctx["admin"]
    definition = create_definition(tid, admin, transaction_type="HIRE", name="Flow")
    add_step(tid, definition["id"], 1, admin, group_id=ctx["group"]["id"])

    current = get_success_data(api_client.get_definition(tid, definition["id"], admin))
    resp = api_client.activate_definition(
        tid, definition["id"],
        {"expected_definition_version": current["version"] - 1}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    activated = get_success_data(api_client.activate_definition(
        tid, definition["id"],
        {"expected_definition_version": current["version"]}, admin,
    ))
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == current["version"] + 1


def test_tenant_suspend_cascades_connectors(api):
    """PRD §3.2: "A successful suspension moves the tenant from `ACTIVE` to
    `SUSPENDED`, cascades every integration connector of the tenant from
    `ACTIVE` to `SUSPENDED`, and increments the tenant's `version` by 1."
    PRD §3.8: "`ACTIVE` to `SUSPENDED` on suspension — which also dead-letters
    every `QUEUED` run of the connector, and which the system applies
    automatically when the tenant is suspended".

    Design: Corner/cross_cutting_layers/tenant_suspend_cascades_connectors
    """
    tenant = create_tenant("T-CC1")
    tid = tenant["id"]
    connector = create_active_connector(tid, "C1")
    set_clock("2026-09-02T03:30:00Z")  # inside blackout [3, 4)
    run = create_run(tid, connector["id"], "SCHEDULE", as_operator=True)
    assert run["status"] == "QUEUED"

    version_before = get_success_data(api_client.get_tenant(tid, op_headers()))["version"]
    suspended = get_success_data(api_client.suspend_tenant(tid, op_headers()))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == version_before + 1

    connector = get_success_data(
        api_client.get_connector(tid, connector["id"], dev_headers())
    )
    assert connector["status"] == "SUSPENDED"

    run = get_success_data(api_client.get_run_flat(run["id"], dev_headers()))
    assert run["status"] == "DEAD_LETTERED", (
        "the connector's QUEUED runs dead-letter on suspension"
    )


def test_multi_tenancy_isolation_list_scoping(api):
    """PRD §3.4: "a `group_name` unique per tenant among groups not yet
    `DISABLED`" — uniqueness is scoped per tenant, so two tenants may reuse a
    name.
    PRD §2.6: "The platform is strictly multi-tenant."
    PRD §2.6: "Nested URLs validate their path segments left to right: the
    tenant is resolved first, then the child resource, then the grandchild.
    The first segment that does not resolve yields `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/cross_cutting_layers/multi_tenancy_isolation_list_scoping
    """
    tenant_a = create_tenant("T-MA")
    tenant_b = create_tenant("T-MB")
    group_a = create_group(tenant_a["id"], "SAME-NAME", admin_of(tenant_a))
    group_b = create_group(tenant_b["id"], "SAME-NAME", admin_of(tenant_b))

    groups, meta = validate_paginated(
        api_client.list_security_groups(tenant_a["id"], admin_of(tenant_a))
    )
    ids = [g["id"] for g in groups]
    assert group_a["id"] in ids
    assert group_b["id"] not in ids, (
        "a tenant-scoped list must never expose another tenant's resources"
    )

    resp = api_client.get_security_group(
        tenant_a["id"], group_b["id"], admin_of(tenant_a),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_amount_threshold_strictly_greater(api):
    """PRD §3.6: "`IF_AMOUNT_GT_1000` includes when the instance's `amount` is
    strictly greater than 1000 — an amount of exactly 1000 does not qualify."

    Design: Corner/cross_cutting_layers/conditional_feature_flags_amount_threshold
    """
    ctx = setup_active_definition(
        "T-FLAG1",
        steps=[{"order": 1, "condition": "IF_AMOUNT_GT_1000"}, {"order": 2}],
        transaction_type="EXPENSE",
    )

    at_boundary = initiate(ctx, transaction_type="EXPENSE", amount=1000)
    assert at_boundary["current_step_order"] == 2, (
        "amount exactly 1000 does not qualify (strictly greater)"
    )

    above = initiate(ctx, transaction_type="EXPENSE", amount=1001)
    assert above["current_step_order"] == 1, (
        "amount 1001 > 1000 includes the conditional step"
    )


def test_immediate_visibility_of_mutation(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.5: "Most entities additionally carry `updated_at` (same format,
    refreshed on every mutation) and an integer `version` that starts at 1".

    Design: Corner/consistency_model/immediate_visibility_of_mutation
    """
    tenant = create_tenant("T-CM1", kind="SANDBOX")
    assert tenant["adopted_feature_count"] == 0
    assert tenant["active_membership_count"] == 0
    assert tenant["version"] == 1
    assert tenant["bootstrap_admin_worker_id"]

    reread = get_success_data(api_client.get_tenant(tenant["id"], op_headers()))
    for field in ("adopted_feature_count", "active_membership_count", "version",
                  "bootstrap_admin_worker_id", "status", "tenant_kind"):
        assert reread[field] == tenant[field], (
            f"immediate read-back must match the create response for {field}"
        )
