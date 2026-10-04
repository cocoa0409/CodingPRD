"""Corner queue B: calculations — input-set filtering."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    admin_of,
    op_headers,
    ApiErrorId,
    add_step,
    create_active_unit,
    create_definition,
    create_feature_train,
    create_group,
    create_tenant,
    create_worker,
    enroll,
    get_train,
    set_clock,
)


def test_adoption_health_after_force_enable_and_retire(api):
    """PRD §3.7: "It starts from a base of 100 and subtracts 5 for each adoption
    in `ENROLLED` or `TESTING_PASSED` and 15 for each adoption in `DEFERRED`."
    PRD §3.7: "Hop 3: `DEFERRED` rows on the train also move to
    `FORCE_ENABLED` — deferral does not survive the mandatory date".
    PRD §3.7: "A train may be retired from `MANDATORY_LIVE` only when a later
    `FEATURE_RELEASE` train is already `MANDATORY_LIVE`".

    After the mandatory cascade the adoption is FORCE_ENABLED, which carries no
    status penalty, so the score returns to 100 even once the train is retired.

    Design: Corner/calculations/adoption_health_input_set_filtering
    """
    tenant = create_tenant("T-CA1")
    admin = admin_of(tenant)
    f1 = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    f2 = create_feature_train(
        "F2026-R2", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-10-02T00:00:00Z",
    )
    set_clock("2026-09-02T00:00:00Z")
    adoption = enroll(tenant["id"], f1["id"], "F1", admin)

    health = get_success_data(api_client.get_adoption_health(tenant["id"], admin))
    assert health["score"] == 95 and health["enrolled_count"] == 1

    set_clock("2026-10-03T00:00:00Z")  # both trains reach mandatory dates
    assert get_train(f1["id"])["status"] == "MANDATORY_LIVE"
    assert get_train(f2["id"])["status"] == "MANDATORY_LIVE"

    retired = get_success_data(api_client.retire_release_train(f1["id"], op_headers()))
    assert retired["status"] == "RETIRED"

    health = get_success_data(api_client.get_adoption_health(tenant["id"], admin))
    assert health["enrolled_count"] == 0
    assert health["deferred_count"] == 0
    assert health["late_count"] == 0
    assert health["score"] == 100, (
        "FORCE_ENABLED carries no status penalty; the score returns to base"
    )


def test_removed_step_excluded_blocks_activation(api):
    """PRD §3.3: "on `DRAFT` definitions the step moves from `ACTIVE` to
    `REMOVED`".
    PRD §3.5: "the definition has at least one `ACTIVE` `APPROVAL` step
    (`ERR_NO_APPROVAL_STEP`, HTTP 422)" — a REMOVED step no longer counts
    toward activation eligibility.

    Design: Corner/calculations/step_chain_input_set_excludes_removed_steps
    """
    tenant = create_tenant("T-CA2")
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "U1", admin)
    group = create_group(tid, "G-ROLE", admin, assignment_mode="ROLE_BASED",
                         org_unit_id=unit["id"], min_approvers=1)
    worker = create_worker(tid, unit["id"], "WR", admin)
    definition = create_definition(tid, admin, transaction_type="EXPENSE",
                                   name="Flow")
    step = add_step(tid, definition["id"], 1, admin, group_id=group["id"])

    # Cascade: terminate the worker (empties the unit), then deactivate.
    get_success_data(api_client.terminate_worker(tid, worker["id"], admin))
    get_success_data(api_client.deactivate_org_unit(tid, unit["id"], admin))

    steps, _meta = validate_paginated(
        api_client.list_steps(tid, definition["id"], admin)
    )
    assert steps[0]["id"] == step["id"]
    assert steps[0]["status"] == "REMOVED"

    current = get_success_data(api_client.get_definition(tid, definition["id"], admin))
    resp = api_client.activate_definition(
        tid, definition["id"],
        {"expected_definition_version": current["version"]}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_NO_APPROVAL_STEP)
