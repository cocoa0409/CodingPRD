"""Corner queue B: validations — violation-to-error coverage."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    admin_of,
    approver_as,
    dev_headers,
    op_headers,
    partner_as,
    ApiErrorId,
    activate_definition,
    add_membership,
    add_step,
    create_active_connector,
    create_active_unit,
    create_definition,
    create_feature_train,
    create_group,
    create_group_with_member,
    create_run,
    create_tenant,
    create_worker,
    enroll,
    get_train,
    initiate,
    set_clock,
    setup_active_definition,
    setup_tenant_with_group,
)


def test_segregation_initiator_cannot_approve(api):
    """PRD §3.6: "the acting worker must not be the instance's
    `initiator_worker_id` — segregation of duties — else
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_initiator_cannot_approve
    """
    ctx = setup_tenant_with_group("T-VA1")
    tid, admin = ctx["tenant"]["id"], ctx["admin"]
    # The initiator ALSO holds membership in the approver group.
    add_membership(tid, ctx["group"]["id"], ctx["initiator"]["id"], admin)
    definition = create_definition(tid, admin, transaction_type="HIRE", name="Flow")
    add_step(tid, definition["id"], 1, admin, group_id=ctx["group"]["id"])
    activate_definition(tid, definition["id"], admin)
    inst = initiate(ctx)

    resp = api_client.approve_step(
        tid, inst["id"], 1, {}, approver_as(ctx["initiator"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    inst = get_success_data(api_client.get_transaction(tid, inst["id"], admin))
    assert inst["status"] == "IN_PROGRESS"
    assert inst["current_step_order"] == 1


def test_non_member_cannot_approve(api):
    """PRD §3.6: "the acting worker must hold an `ACTIVE` membership in the
    step's `approver_security_group_id` (`ERR_NOT_STEP_APPROVER`, HTTP 403)".

    Design: Corner/validations/non_member_cannot_approve
    """
    ctx = setup_active_definition("T-VA2", steps=[{"order": 1}])
    tid = ctx["tenant"]["id"]
    outsider = create_worker(tid, ctx["unit"]["id"], "OUT", ctx["admin"])
    inst = initiate(ctx)

    resp = api_client.approve_step(
        tid, inst["id"], 1, {}, approver_as(outsider["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_STEP_APPROVER)


def test_wrong_step_order_rejected(api):
    """PRD §3.6: "the `step_order` in the request must equal
    `current_step_order` (`ERR_STEP_NOT_PENDING`, HTTP 409)".

    Design: Corner/validations/wrong_step_order_rejected
    """
    ctx = setup_active_definition(
        "T-VA3", steps=[{"order": 1}, {"order": 2}],
    )
    tid = ctx["tenant"]["id"]
    inst = initiate(ctx)
    assert inst["current_step_order"] == 1

    resp = api_client.approve_step(
        tid, inst["id"], 2, {}, approver_as(ctx["approver"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STEP_NOT_PENDING)


def test_hierarchy_step_order_and_return_target_violations(api):
    """PRD §3.5: "Step orders within a definition must form a contiguous
    1-based sequence from 1 to N, and `return_target_step_order` must be
    strictly less than the step's own `step_order`; both violations surface
    `ERR_HIERARCHY_VIOLATION`."

    Design: Corner/validations/hierarchy_cycle_and_step_order_violations
    """
    tenant = create_tenant("T-VA4")
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "U1", admin)
    approver = create_worker(tid, unit["id"], "MGR", admin)
    group = create_group_with_member(tid, "G1", approver["id"], admin)
    definition = create_definition(tid, admin, transaction_type="HIRE", name="Flow")
    add_step(tid, definition["id"], 1, admin, group_id=group["id"])

    # Gap: adding step 3 when only step 1 exists breaks contiguity.
    resp = api_client.create_step(
        tid, definition["id"],
        {"step_order": 3, "step_kind": "APPROVAL",
         "approver_security_group_id": group["id"],
         "inclusion_condition": "ALWAYS"},
        admin,
    )
    validate_error(resp, ApiErrorId.ERR_HIERARCHY_VIOLATION)

    # return_target_step_order must be strictly less than step_order.
    resp = api_client.create_step(
        tid, definition["id"],
        {"step_order": 2, "step_kind": "APPROVAL",
         "approver_security_group_id": group["id"],
         "inclusion_condition": "ALWAYS",
         "return_target_step_order": 2},
        admin,
    )
    validate_error(resp, ApiErrorId.ERR_HIERARCHY_VIOLATION)


def test_role_derived_membership_immutable(api):
    """PRD §3.4: "Membership rows carry a `membership_source`: `ROLE_DERIVED`
    rows are created and invalidated only by system org-resolution".
    PRD §3.4: "attempting to delete a `ROLE_DERIVED` membership is rejected
    with `ERR_ROLE_DERIVED_MEMBERSHIP_IMMUTABLE`".

    Design: Corner/validations/role_derived_membership_immutable
    """
    tenant = create_tenant("T-VA5")
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "U1", admin)
    group = create_group(tid, "G-ROLE", admin, assignment_mode="ROLE_BASED",
                         org_unit_id=unit["id"], min_approvers=1)
    create_worker(tid, unit["id"], "W1", admin)

    memberships, meta = validate_paginated(
        api_client.list_memberships(tid, group["id"], admin)
    )
    assert meta["total_count"] == 1
    assert memberships[0]["membership_source"] == "ROLE_DERIVED", (
        "creating a worker synthesizes ROLE_DERIVED memberships for "
        "ROLE_BASED groups covering its unit"
    )

    resp = api_client.delete_membership(tid, group["id"], memberships[0]["id"], admin)
    validate_error(resp, ApiErrorId.ERR_ROLE_DERIVED_MEMBERSHIP_IMMUTABLE)


def test_invalid_date_ranges_rejected(api):
    """PRD §3.7: "the three dates must be strictly ordered — start before end
    before mandatory date — else `ERR_INVALID_DATE_RANGE`."
    PRD §3.3: "a child's `effective_date` must not be earlier than its
    parent's; violations of either rule, or of the manager-chain acyclicity
    rule below, surface `ERR_HIERARCHY_VIOLATION` (HTTP 422)."
    PRD §2.7: "14. Date ranges — a child unit's `effective_date` is not earlier
    than its parent's, and a train's `opt_in_window_start` is before
    `opt_in_window_end` which is before `mandatory_date`, else
    `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/invalid_date_ranges_rejected
    """
    resp = api_client.create_release_train(
        {"release_label": "BAD-1", "release_kind": "FEATURE_RELEASE",
         "opt_in_window_start": "2026-09-10T00:00:00Z",
         "opt_in_window_end": "2026-09-01T00:00:00Z",
         "mandatory_date": "2026-10-01T00:00:00Z"},
        op_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

    tenant = create_tenant("T-VA6")
    admin = admin_of(tenant)
    parent = get_success_data(api_client.create_org_unit(
        tenant["id"],
        {"unit_name": "P", "unit_type": "DIVISION",
         "effective_date": "2026-09-10T00:00:00Z"},
        admin,
    ), 201)
    resp = api_client.create_org_unit(
        tenant["id"],
        {"unit_name": "C", "unit_type": "TEAM",
         "effective_date": "2026-09-05T00:00:00Z",
         "parent_unit_id": parent["id"]},
        admin,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_connector_trigger_config_and_blackout_validated(api):
    """PRD §3.8: "Activation checks the matching field is present for the
    connector's mode (`ERR_INVALID_TRIGGER_CONFIG`, HTTP 422), that the
    blackout window is non-empty — start and end hours equal is forbidden
    (`ERR_INVALID_BLACKOUT_WINDOW`, HTTP 422)".

    Design: Corner/validations/connector_trigger_config_and_blackout_validated
    """
    tenant = create_tenant("T-VA7")
    tid = tenant["id"]
    c1 = get_success_data(api_client.create_connector(
        tid,
        {"connector_name": "C1", "trigger_mode": "SCHEDULED",
         "blackout_window_start_utc": 3, "blackout_window_end_utc": 4},
        dev_headers(),
    ), 201)
    c2 = get_success_data(api_client.create_connector(
        tid,
        {"connector_name": "C2", "trigger_mode": "SCHEDULED",
         "schedule_cron": "0 1 * * *",
         "blackout_window_start_utc": 5, "blackout_window_end_utc": 5},
        dev_headers(),
    ), 201)

    resp = api_client.activate_connector(tid, c1["id"], dev_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_TRIGGER_CONFIG)

    resp = api_client.activate_connector(tid, c2["id"], dev_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_BLACKOUT_WINDOW)


def test_duplicate_active_definition_rejected(api):
    """PRD §3.5: "no other definition for the same tenant and
    `transaction_type` is already `ACTIVE` (`ERR_DUPLICATE_ACTIVE_DEFINITION`,
    HTTP 409)".

    Design: Corner/validations/duplicate_active_definition_rejected
    """
    ctx = setup_active_definition("T-VA8", steps=[{"order": 1}])
    tid, admin = ctx["tenant"]["id"], ctx["admin"]

    second = create_definition(tid, admin, transaction_type="HIRE", name="Flow2")
    add_step(tid, second["id"], 1, admin, group_id=ctx["group"]["id"])
    current = get_success_data(api_client.get_definition(tid, second["id"], admin))
    resp = api_client.activate_definition(
        tid, second["id"],
        {"expected_definition_version": current["version"]}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_DEFINITION)

    second = get_success_data(api_client.get_definition(tid, second["id"], admin))
    assert second["status"] == "DRAFT"


def test_activation_requires_approval_step(api):
    """PRD §3.5: "the definition has at least one `ACTIVE` `APPROVAL` step
    (`ERR_NO_APPROVAL_STEP`, HTTP 422)".

    Design: Corner/validations/activation_requires_approval_step
    """
    tenant = create_tenant("T-VA9")
    admin = admin_of(tenant)
    tid = tenant["id"]
    definition = create_definition(tid, admin, transaction_type="EXPENSE",
                                   name="Noisy")
    add_step(tid, definition["id"], 1, admin, kind="NOTIFICATION")

    current = get_success_data(api_client.get_definition(tid, definition["id"], admin))
    resp = api_client.activate_definition(
        tid, definition["id"],
        {"expected_definition_version": current["version"]}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_NO_APPROVAL_STEP)


def test_group_in_use_cannot_be_disabled(api):
    """PRD §3.4: "A group can also be disabled directly by a
    `TenantAdministrator`, but only while no `ACTIVE` business process
    definition has an `ACTIVE` step whose `approver_security_group_id`
    references the group; otherwise the request fails with `ERR_GROUP_IN_USE`
    (HTTP 409)."

    Design: Corner/validations/group_in_use_cannot_be_disabled
    """
    ctx = setup_active_definition("T-VA10", steps=[{"order": 1}])
    tid, admin = ctx["tenant"]["id"], ctx["admin"]

    resp = api_client.disable_security_group(tid, ctx["group"]["id"], admin)
    validate_error(resp, ApiErrorId.ERR_GROUP_IN_USE)

    group = get_success_data(
        api_client.get_security_group(tid, ctx["group"]["id"], admin)
    )
    assert group["status"] == "ACTIVE"


def test_org_deactivation_guards(api):
    """PRD §3.3: "A `TenantAdministrator` deactivates a unit only when it has
    no `ACTIVE` descendant units (`ERR_HAS_ACTIVE_CHILDREN`, HTTP 409) and its
    `headcount` is 0 (`ERR_UNIT_NOT_EMPTY`, HTTP 409)."

    Design: Corner/validations/org_deactivation_guards
    """
    tenant = create_tenant("T-VA11")
    admin = admin_of(tenant)
    tid = tenant["id"]
    parent = create_active_unit(tid, "P", admin, unit_type="DIVISION")
    create_active_unit(tid, "C", admin, parent_unit_id=parent["id"])
    busy = create_active_unit(tid, "X", admin)
    create_worker(tid, busy["id"], "WX", admin)

    resp = api_client.deactivate_org_unit(tid, parent["id"], admin)
    validate_error(resp, ApiErrorId.ERR_HAS_ACTIVE_CHILDREN)

    resp = api_client.deactivate_org_unit(tid, busy["id"], admin)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_EMPTY)


def test_worker_termination_blocked_by_reports(api):
    """PRD §3.3: "Termination requires that the worker have no direct reports
    in `ACTIVE` status (`ERR_HAS_ACTIVE_REPORTS`, HTTP 409)."

    Design: Corner/validations/worker_termination_blocked_by_reports
    """
    tenant = create_tenant("T-VA12")
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "U1", admin)
    manager = create_worker(tid, unit["id"], "M", admin)
    create_worker(tid, unit["id"], "R", admin, manager_worker_id=manager["id"])

    resp = api_client.terminate_worker(tid, manager["id"], admin)
    validate_error(resp, ApiErrorId.ERR_HAS_ACTIVE_REPORTS)

    manager = get_success_data(api_client.get_worker(tid, manager["id"], admin))
    assert manager["status"] == "ACTIVE"


def test_evidence_required_for_testing_passed(api):
    """PRD §3.7: "Recording sandbox testing moves a row from `ENROLLED` to
    `TESTING_PASSED` and requires `sandbox_test_evidence_id`: either an
    `IntegrationRun` that succeeded on a `SANDBOX` tenant of this customer, or
    a non-empty free-form evidence string. Missing or unresolvable evidence is
    rejected with `ERR_TEST_EVIDENCE_MISSING` (HTTP 422)."

    Design: Corner/validations/test_evidence_required_for_testing_passed
    """
    tenant = create_tenant("T-VA13")
    admin = admin_of(tenant)
    train = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    set_clock("2026-09-02T00:00:00Z")
    adoption = enroll(tenant["id"], train["id"], "F1", admin)

    resp = api_client.record_testing(
        tenant["id"], adoption["id"], {"sandbox_test_evidence_id": ""}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_TEST_EVIDENCE_MISSING)

    adoption = get_success_data(
        api_client.get_feature_adoption(tenant["id"], adoption["id"], admin)
    )
    assert adoption["status"] == "ENROLLED"


def test_train_retire_requires_successor(api):
    """PRD §3.7: "A train may be retired from `MANDATORY_LIVE` only when a
    later `FEATURE_RELEASE` train is already `MANDATORY_LIVE`; otherwise the
    retirement fails with `ERR_NO_SUCCESSOR_TRAIN` (HTTP 422)."

    Design: Corner/validations/train_retire_requires_successor
    """
    train = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    set_clock("2026-10-02T00:00:00Z")
    assert get_train(train["id"])["status"] == "MANDATORY_LIVE"

    resp = api_client.retire_release_train(train["id"], op_headers())
    validate_error(resp, ApiErrorId.ERR_NO_SUCCESSOR_TRAIN)

    assert get_train(train["id"])["status"] == "MANDATORY_LIVE"


def test_handoff_leg_order_and_tenant_kind(api):
    """PRD §3.2: "The first leg is performed by an `ImplementationPartner` and
    is rejected with `ERR_NOT_IMPLEMENTATION_TENANT` (HTTP 422) unless
    `tenant_kind` is `IMPLEMENTATION`, and with `ERR_NO_ACTIVE_BP_DEFINITION`
    (HTTP 422) unless at least one business process definition on the tenant is
    `ACTIVE` — a tenant is not handoff-ready until it has at least one live
    business process."

    Design: Corner/validations/handoff_leg_order_and_tenant_kind
    """
    prod = create_tenant("T-PROD")
    impl = create_tenant("T-IMPL", kind="IMPLEMENTATION")

    resp = api_client.handoff_advance(
        prod["id"], partner_as(prod["bootstrap_admin_worker_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_IMPLEMENTATION_TENANT)

    resp = api_client.handoff_advance(
        impl["id"], partner_as(impl["bootstrap_admin_worker_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_BP_DEFINITION)

    impl = get_success_data(api_client.get_tenant(impl["id"], op_headers()))
    assert impl["handoff_state"] == "IN_BUILD"


def test_connector_retire_blocked_by_runs_in_flight(api):
    """PRD §3.8: "Retirement from `ACTIVE` requires no runs of the connector in
    `QUEUED` or `RUNNING` (`ERR_RUNS_IN_FLIGHT`, HTTP 409)".

    Design: Corner/validations/connector_retire_blocked_by_runs_in_flight
    """
    tenant = create_tenant("T-VA15")
    set_clock("2026-09-02T00:00:00Z")
    connector = create_active_connector(tenant["id"], "C1")
    create_run(tenant["id"], connector["id"], "MANUAL")  # RUNNING immediately

    resp = api_client.retire_connector(tenant["id"], connector["id"], dev_headers())
    validate_error(resp, ApiErrorId.ERR_RUNS_IN_FLIGHT)

    connector = get_success_data(
        api_client.get_connector(tenant["id"], connector["id"], dev_headers())
    )
    assert connector["status"] == "ACTIVE"
