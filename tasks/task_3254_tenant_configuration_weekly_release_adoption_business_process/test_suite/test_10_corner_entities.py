"""Corner queue B: entities — defaults, not-found, immutability, tenancy."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    admin_of,
    assert_step_event,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_tenant,
    initiate,
    set_clock,
    setup_active_definition,
)


def test_tenant_creation_applies_defaults_and_bootstrap(api):
    """PRD §3.1: "The operator may also set `service_level_tier` (defaulting to
    `STANDARD`; `PREMIUM` tenants receive a 14-day extension on feature-release
    opt-in windows), `weekly_update_auto_apply` (defaulting to true)".
    PRD §2.1: "tenant creation mints a bootstrap administrator `Worker` with
    `worker_ref` `BOOTSTRAP-ADMIN` and a null `org_unit_id`, and records that
    worker's id on the tenant as `bootstrap_admin_worker_id`".

    Design: Corner/entities/tenant_creation_defaults_and_system_fields
    """
    tenant = create_tenant("T-ENT1")
    assert tenant["service_level_tier"] == "STANDARD"
    assert tenant["weekly_update_auto_apply"] is True
    assert tenant["adopted_feature_count"] == 0
    assert tenant["active_membership_count"] == 0
    assert tenant["handoff_state"] == "IN_BUILD"
    assert tenant["status"] == "ACTIVE"

    bootstrap = get_success_data(
        api_client.get_worker(
            tenant["id"], tenant["bootstrap_admin_worker_id"], admin_of(tenant),
        )
    )
    assert bootstrap["worker_ref"] == "BOOTSTRAP-ADMIN"
    assert bootstrap["org_unit_id"] is None


def test_get_missing_org_unit_returns_not_found(api):
    """PRD §2.6: "Nested URLs validate their path segments left to right: the
    tenant is resolved first, then the child resource, then the grandchild.
    The first segment that does not resolve yields `ERR_NOT_FOUND` (HTTP 404)
    without evaluating later segments."

    Design: Corner/entities/entity_not_found_returns_404
    """
    tenant = create_tenant("T-ENT2")
    admin = admin_of(tenant)
    resp = api_client.get_org_unit(tenant["id"], NON_EXISTENT_UUID, admin)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_step_events_carry_no_version_or_updated_at(api):
    """PRD §2.5: "Two entity kinds deliberately break this pattern:
    `TransactionStepEvent` and `Notification` carry only `id` and `created_at`.
    Both `updated_at` and `version` are absent from those two resources; they
    are append-only audit artifacts and are never mutated after creation."

    Design: Corner/entities/transaction_step_event_immutable_no_update
    """
    ctx = setup_active_definition("T-ENT3", steps=[{"order": 1}])
    inst = initiate(ctx)
    events, _meta = validate_paginated(
        api_client.list_events(ctx["tenant"]["id"], inst["id"], ctx["admin"])
    )
    assert len(events) >= 1, "initiation appends at least one step event"
    for event in events:
        assert_step_event(event)


def test_worker_with_cross_tenant_org_unit_rejected(api):
    """PRD §2.6: "Request bodies that reference other resources by id must
    reference resources inside the same tenant scope; a body that points at a
    resource owned by a different tenant is rejected with
    `ERR_CROSS_TENANT_REFERENCE` (HTTP 422)."

    Design: Corner/entities/cross_tenant_fk_reference_rejected
    """
    from test_helpers import create_active_unit

    tenant_a = create_tenant("T-A")
    tenant_b = create_tenant("T-B")
    unit_b = create_active_unit(tenant_b["id"], "UB", admin_of(tenant_b))

    resp = api_client.create_worker(
        tenant_a["id"],
        {"worker_ref": "WX", "full_name": "Cross", "org_unit_id": unit_b["id"],
         "hire_date": "2026-09-02T00:00:00Z"},
        admin_of(tenant_a),
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_TENANT_REFERENCE)
