"""Difficulty queue A: transitive cascades (org deactivation, mandatory release)."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_paginated,
    admin_of,
    add_step,
    create_active_unit,
    create_definition,
    create_feature_train,
    create_group,
    create_tenant,
    create_worker,
    enroll,
    get_adoption,
    get_tenant,
    get_train,
    list_notifications,
    set_clock,
)


def _setup_role_group_cascade(name="T-TC1"):
    """Tenant with unit u1, a ROLE_BASED group on u1 (min_approvers 1), one
    worker in u1 (its ROLE_DERIVED membership synthesized), and a DRAFT
    definition whose step 1 references the group. The worker is then
    terminated (headcount must be 0 before deactivation)."""
    tenant = create_tenant(name)
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "U1", admin)
    group = create_group(tid, "G-ROLE", admin, assignment_mode="ROLE_BASED",
                         org_unit_id=unit["id"], min_approvers=1)
    worker = create_worker(tid, unit["id"], "WR", admin)
    definition = create_definition(tid, admin, transaction_type="EXPENSE",
                                   name="D-Draft")
    step = add_step(tid, definition["id"], 1, admin, group_id=group["id"])
    return tenant, admin, unit, group, worker, definition, step


def test_org_deactivation_three_hop_cascade(api):
    """PRD §3.3: "Deactivation triggers a three-hop cascade. Hop 1: every
    `ROLE_BASED` security group whose `org_unit_id` is this unit has all of its
    `ACTIVE` `ROLE_DERIVED` memberships invalidated, each invalidation
    decrementing the tenant's `active_membership_count`. Hop 2: for each group
    so affected, if the remaining `ACTIVE` memberships fall below the group's
    `min_approvers`, the group itself transitions from `ACTIVE` to `DISABLED`.
    Hop 3: for each group disabled in hop 2, every business process step whose
    `approver_security_group_id` is that group is handled — on `DRAFT`
    definitions the step moves from `ACTIVE` to `REMOVED`".

    Design: Difficulty/transitive_cascade/org_deactivation_membership_group_step_cascade
    """
    tenant, admin, unit, group, worker, definition, step = \
        _setup_role_group_cascade()
    tid = tenant["id"]

    # Termination empties the unit (deactivation requires headcount 0) and
    # invalidates the worker's memberships.
    get_success_data(api_client.terminate_worker(tid, worker["id"], admin))
    assert get_tenant(tid)["active_membership_count"] == 0

    get_success_data(api_client.deactivate_org_unit(tid, unit["id"], admin))

    unit = get_success_data(api_client.get_org_unit(tid, unit["id"], admin))
    assert unit["status"] == "INACTIVE"

    assert get_tenant(tid)["active_membership_count"] == 0

    group = get_success_data(api_client.get_security_group(tid, group["id"], admin))
    assert group["status"] == "DISABLED", (
        "hop 2: 0 ACTIVE memberships < min_approvers 1 disables the group"
    )

    steps, _meta = validate_paginated(
        api_client.list_steps(tid, definition["id"], admin)
    )
    assert steps[0]["id"] == step["id"]
    assert steps[0]["status"] == "REMOVED", (
        "hop 3: the DRAFT definition's step referencing the disabled group "
        "moves to REMOVED"
    )


def test_org_deactivation_cascade_scoped_to_own_groups(api):
    """PRD §3.3: "Hop 1: every `ROLE_BASED` security group whose `org_unit_id`
    is this unit has all of its `ACTIVE` `ROLE_DERIVED` memberships
    invalidated". Groups anchored to other units of the same tenant are
    outside the cascade's scope and survive with their memberships intact.

    Design: Difficulty/transitive_cascade/org_deactivation_membership_group_step_cascade
    """
    tenant, admin, unit1, group1, worker1, definition, step = \
        _setup_role_group_cascade("T-TC1B")
    tid = tenant["id"]

    # A second unit with its own ROLE_BASED group and an ACTIVE worker.
    unit2 = create_active_unit(tid, "U2", admin)
    group2 = create_group(tid, "G-ROLE-2", admin, assignment_mode="ROLE_BASED",
                          org_unit_id=unit2["id"], min_approvers=1)
    worker2 = create_worker(tid, unit2["id"], "W2", admin)
    assert get_tenant(tid)["active_membership_count"] == 2

    # Empty unit1, then deactivate it.
    get_success_data(api_client.terminate_worker(tid, worker1["id"], admin))
    assert get_tenant(tid)["active_membership_count"] == 1
    get_success_data(api_client.deactivate_org_unit(tid, unit1["id"], admin))

    group2 = get_success_data(api_client.get_security_group(tid, group2["id"], admin))
    assert group2["status"] == "ACTIVE", (
        "a group anchored to a different unit must survive the cascade"
    )
    memberships, meta = validate_paginated(
        api_client.list_memberships(tid, group2["id"], admin,
                                    params={"status": "ACTIVE"})
    )
    assert meta["total_count"] == 1
    assert memberships[0]["worker_id"] == worker2["id"]
    assert get_tenant(tid)["active_membership_count"] == 1


def _setup_predecessor_pair():
    """Tenant with F-OLD ADOPTED on train f0 and F-NEW TESTING_PASSED on train
    f1, where F-NEW deprecates F-OLD."""
    tenant = create_tenant("T-TC2")
    admin = admin_of(tenant)
    tid = tenant["id"]
    f0 = create_feature_train(
        "F2026-R0", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-11-01T00:00:00Z",
    )
    f1 = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    set_clock("2026-09-02T00:00:00Z")  # both windows open
    a_old = enroll(tid, f0["id"], "F-OLD", admin)
    get_success_data(
        api_client.record_testing(tid, a_old["id"],
                                  {"sandbox_test_evidence_id": "EV-OLD"}, admin)
    )
    get_success_data(api_client.adopt_feature(tid, a_old["id"], admin))
    a_new = enroll(tid, f1["id"], "F-NEW", admin, deprecates_feature_key="F-OLD")
    get_success_data(
        api_client.record_testing(tid, a_new["id"],
                                  {"sandbox_test_evidence_id": "EV-NEW"}, admin)
    )
    return tenant, admin, f0, f1, a_old, a_new


def test_mandatory_release_force_enable_rolls_back_predecessor(api):
    """PRD §3.7: "Hop 1: every adoption row for the train in `ENROLLED` or
    `TESTING_PASSED` moves to `FORCE_ENABLED`, incrementing the tenant's
    `adopted_feature_count` by 1 per row. Hop 2: for each row flipped in hop 1
    that names a `deprecates_feature_key`, any adoption on the same tenant
    whose `feature_key` equals that predecessor and whose status is `ADOPTED`
    or `FORCE_ENABLED` moves to `ROLLED_BACK`, decrementing
    `adopted_feature_count` by 1 per row, with a `FORCE_ENABLED` notification
    emitted."

    Design: Difficulty/transitive_cascade/mandatory_release_force_enable_predecessor_retirement_cascade
    """
    tenant, admin, f0, f1, a_old, a_new = _setup_predecessor_pair()
    tid = tenant["id"]
    assert get_tenant(tid)["adopted_feature_count"] == 1  # only F-OLD adopted

    set_clock("2026-09-11T00:00:00Z")  # both windows close; TESTING_PASSED rows stay
    assert get_adoption(tid, a_new["id"], admin)["status"] == "TESTING_PASSED"

    set_clock("2026-10-01T00:00:00Z")  # f1 reaches mandatory_date
    assert get_train(f1["id"])["status"] == "MANDATORY_LIVE"

    a_new = get_adoption(tid, a_new["id"], admin)
    assert a_new["status"] == "FORCE_ENABLED"
    a_old = get_adoption(tid, a_old["id"], admin)
    assert a_old["status"] == "ROLLED_BACK", (
        "hop 2: the deprecated predecessor retires on the same tenant"
    )

    # +1 for the force-enabled successor, -1 for the rolled-back predecessor.
    assert get_tenant(tid)["adopted_feature_count"] == 1

    kinds = list_notifications(tid, admin, notification_kind="FORCE_ENABLED")
    assert len(kinds) >= 1, "a FORCE_ENABLED notification must be emitted"


def test_mandatory_release_force_enables_deferred_rows(api):
    """PRD §3.7: "at that moment every feature adoption on the train still
    `ENROLLED` with no test evidence recorded is moved to `DEFERRED`."
    PRD §3.7: "Hop 3: `DEFERRED` rows on the train also move to
    `FORCE_ENABLED` — deferral does not survive the mandatory date, the
    deprecated predecessor is still retired on the tenant — and a
    `RETIREMENT_WARNING` notification is emitted."

    Design: Difficulty/transitive_cascade/mandatory_release_force_enable_predecessor_retirement_cascade
    """
    tenant = create_tenant("T-TC2B")
    admin = admin_of(tenant)
    tid = tenant["id"]
    f1 = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    set_clock("2026-09-02T00:00:00Z")
    adoption = enroll(tid, f1["id"], "F1", admin)  # ENROLLED, no test evidence

    set_clock("2026-09-11T00:00:00Z")  # window closes: ENROLLED -> DEFERRED
    adoption = get_adoption(tid, adoption["id"], admin)
    assert adoption["status"] == "DEFERRED"
    assert get_tenant(tid)["adopted_feature_count"] == 0

    set_clock("2026-10-01T00:00:00Z")  # mandatory date
    assert get_train(f1["id"])["status"] == "MANDATORY_LIVE"
    adoption = get_adoption(tid, adoption["id"], admin)
    assert adoption["status"] == "FORCE_ENABLED", (
        "deferral does not survive the mandatory date"
    )
    assert get_tenant(tid)["adopted_feature_count"] == 1

    kinds = list_notifications(tid, admin, notification_kind="RETIREMENT_WARNING")
    assert len(kinds) >= 1, "a RETIREMENT_WARNING notification must be emitted"
