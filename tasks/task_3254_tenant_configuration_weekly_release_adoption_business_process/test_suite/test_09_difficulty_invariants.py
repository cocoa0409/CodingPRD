"""Difficulty queue A: compensating invariants (membership count, adopted count)."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_paginated,
    admin_of,
    add_membership,
    create_active_unit,
    create_feature_train,
    create_group,
    create_tenant,
    create_worker,
    enroll,
    get_adoption,
    get_tenant,
    set_clock,
)


def test_membership_add_remove_preserves_active_count(api):
    """PRD §3.4: "Creating a membership increments the tenant's
    `active_membership_count` by 1."
    PRD §3.4: "removal never hard-deletes: the row moves from `ACTIVE` to
    `INVALIDATED`, is retained for audit, is excluded from
    `active_membership_count` (which decrements by 1) and from approver
    resolution".

    Design: Difficulty/compensating_invariant/membership_add_remove_preserves_active_membership_count
    """
    tenant = create_tenant("T-CI1")
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "U1", admin)
    approver = create_worker(tid, unit["id"], "MGR", admin)
    extra = create_worker(tid, unit["id"], "EXTRA", admin)
    group = create_group(tid, "G1", admin, min_approvers=1)
    add_membership(tid, group["id"], approver["id"], admin)

    before = get_tenant(tid)["active_membership_count"]
    assert before == 1

    membership = add_membership(tid, group["id"], extra["id"], admin)
    assert get_tenant(tid)["active_membership_count"] == before + 1

    resp = api_client.delete_membership(tid, group["id"], membership["id"], admin)
    assert resp.status_code == 204, (
        f"membership removal returns 204, got {resp.status_code}"
    )

    after = get_tenant(tid)["active_membership_count"]
    assert after == before, (
        f"add+remove must compensate exactly: {before} -> {after}"
    )

    retained = get_success_data(
        api_client.get_membership_flat(membership["id"], admin)
    )
    assert retained["status"] == "INVALIDATED", (
        "removal soft-invalidates; the row is retained for audit"
    )


def test_membership_removal_below_min_disables_group(api):
    """PRD §3.4: "if the group's `ACTIVE` memberships thereby drop below
    `min_approvers` the group transitions to `DISABLED`".

    Design: Difficulty/compensating_invariant/membership_add_remove_preserves_active_membership_count
    """
    tenant = create_tenant("T-CI1B")
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "U1", admin)
    approver = create_worker(tid, unit["id"], "MGR", admin)
    group = create_group(tid, "G1", admin, min_approvers=1)
    membership = add_membership(tid, group["id"], approver["id"], admin)

    resp = api_client.delete_membership(tid, group["id"], membership["id"], admin)
    assert resp.status_code == 204

    group = get_success_data(api_client.get_security_group(tid, group["id"], admin))
    assert group["status"] == "DISABLED", (
        "0 ACTIVE memberships < min_approvers 1 disables the group"
    )
    assert get_tenant(tid)["active_membership_count"] == 0


def _adopted_predecessor_setup():
    """F-OLD ADOPTED on train f0; F-NEW TESTING_PASSED on train f1 deprecating
    F-OLD. Returns before the mandatory cascade fires."""
    tenant = create_tenant("T-CI2")
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
    set_clock("2026-09-02T00:00:00Z")
    a_old = enroll(tid, f0["id"], "F-OLD", admin)
    get_success_data(api_client.record_testing(
        tid, a_old["id"], {"sandbox_test_evidence_id": "EV-OLD"}, admin,
    ))
    get_success_data(api_client.adopt_feature(tid, a_old["id"], admin))
    a_new = enroll(tid, f1["id"], "F-NEW", admin, deprecates_feature_key="F-OLD")
    get_success_data(api_client.record_testing(
        tid, a_new["id"], {"sandbox_test_evidence_id": "EV-NEW"}, admin,
    ))
    return tenant, admin, f1, a_old, a_new


def test_adopt_then_force_rollback_conserves_adopted_count(api):
    """PRD §2.8: "`adopted_feature_count` counts the tenant's
    `TenantFeatureAdoption` rows currently in `ADOPTED` status (incremented on
    adoption and on force-enablement, decremented on rollback)".
    PRD §3.7: "Hop 1: every adoption row for the train in `ENROLLED` or
    `TESTING_PASSED` moves to `FORCE_ENABLED`, incrementing the tenant's
    `adopted_feature_count` by 1 per row. Hop 2: for each row flipped in hop 1
    that names a `deprecates_feature_key`, any adoption on the same tenant
    whose `feature_key` equals that predecessor and whose status is `ADOPTED`
    or `FORCE_ENABLED` moves to `ROLLED_BACK`, decrementing
    `adopted_feature_count` by 1 per row".

    Design: Difficulty/compensating_invariant/adopt_then_rollback_preserves_adopted_feature_count
    """
    tenant, admin, f1, a_old, a_new = _adopted_predecessor_setup()
    tid = tenant["id"]

    before = get_tenant(tid)["adopted_feature_count"]
    assert before == 1, "only F-OLD is ADOPTED before the mandatory cascade"

    set_clock("2026-10-01T00:00:00Z")  # f1 mandatory date

    assert get_adoption(tid, a_new["id"], admin)["status"] == "FORCE_ENABLED"
    assert get_adoption(tid, a_old["id"], admin)["status"] == "ROLLED_BACK"
    after = get_tenant(tid)["adopted_feature_count"]
    assert after == before, (
        f"force-enable (+1) and rollback (-1) compensate: {before} -> {after}"
    )


def test_mandatory_cascade_idempotent_on_repeated_clock_advance(api):
    """PRD §3.7: "When a feature train reaches its `mandatory_date` it
    transitions `OPT_IN_CLOSED` to `MANDATORY_LIVE` and fires a three-hop
    cascade across every tenant." The cascade is bound to the train's state
    transition; once the train is MANDATORY_LIVE no further transition fires,
    so re-advancing the clock past the same mandatory date must not move the
    counter again.

    Design: Difficulty/compensating_invariant/adopt_then_rollback_preserves_adopted_feature_count
    """
    tenant, admin, f1, a_old, a_new = _adopted_predecessor_setup()
    tid = tenant["id"]

    set_clock("2026-10-01T00:00:00Z")
    after_first = get_tenant(tid)["adopted_feature_count"]
    assert after_first == 1

    set_clock("2026-10-02T00:00:00Z")  # further past the same mandatory date
    after_second = get_tenant(tid)["adopted_feature_count"]
    assert after_second == after_first, (
        "the mandatory cascade must not fire twice"
    )
    assert get_adoption(tid, a_new["id"], admin)["status"] == "FORCE_ENABLED"
    assert get_adoption(tid, a_old["id"], admin)["status"] == "ROLLED_BACK"
