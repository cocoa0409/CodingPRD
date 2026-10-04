"""Difficulty queue A: exact-boundary checks (opt-in window, headcount)."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    admin_as,
    admin_of,
    ApiErrorId,
    activate_definition,
    add_step,
    create_active_unit,
    create_definition,
    create_feature_train,
    create_group_with_member,
    create_tenant,
    create_worker,
    create_workers,
    set_clock,
)


def _open_train_setup():
    tenant = create_tenant("T-BP1")
    admin = admin_of(tenant)
    train = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    return tenant, admin, train


def test_enrollment_at_exact_window_end_accepted(api):
    """PRD §3.7: "The opt-in window's end is an inclusive boundary: enrollments
    are accepted at exactly `opt_in_window_end` and rejected only after it."

    Design: Difficulty/boundary_precision_check/opt_in_window_end_inclusive_enrollment
    """
    tenant, admin, train = _open_train_setup()
    set_clock("2026-09-10T00:00:00Z")  # exactly opt_in_window_end

    resp = api_client.create_feature_adoption(
        tenant["id"], {"release_train_id": train["id"], "feature_key": "F1"}, admin,
    )
    adoption = validate_success(resp, 201)
    assert adoption["status"] == "ENROLLED", (
        "enrollment at exactly opt_in_window_end must be accepted"
    )


def test_enrollment_one_second_after_window_end_rejected(api):
    """PRD §3.7: "The opt-in window's end is an inclusive boundary: enrollments
    are accepted at exactly `opt_in_window_end` and rejected only after it."
    PRD §3.7: "outside the window they fail with `ERR_OPT_IN_WINDOW_CLOSED`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/opt_in_window_end_inclusive_enrollment
    """
    tenant, admin, train = _open_train_setup()
    set_clock("2026-09-10T00:00:01Z")  # one second past opt_in_window_end

    resp = api_client.create_feature_adoption(
        tenant["id"], {"release_train_id": train["id"], "feature_key": "F2"}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_OPT_IN_WINDOW_CLOSED)


def _boundary_definition(name):
    """Tenant + ACTIVE HIRE definition: step 1 APPROVAL gated on
    IF_HEADCOUNT_GE_50, step 2 APPROVAL unconditional. Returns context with the
    unit the workers should be added to."""
    tenant = create_tenant(name)
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "U1", admin, unit_type="DIVISION")
    initiator = create_worker(tid, unit["id"], "INIT", admin)
    approver = create_worker(tid, unit["id"], "MGR", admin)
    group = create_group_with_member(tid, "G1", approver["id"], admin)
    definition = create_definition(tid, admin, transaction_type="HIRE",
                                   name="BoundaryFlow")
    add_step(tid, definition["id"], 1, admin, group_id=group["id"],
             condition="IF_HEADCOUNT_GE_50")
    add_step(tid, definition["id"], 2, admin, group_id=group["id"])
    activate_definition(tid, definition["id"], admin)
    return {
        "tenant": tenant, "admin": admin, "unit": unit,
        "initiator": initiator, "approver": approver,
        # INIT and MGR already count toward the unit's headcount.
        "base_headcount": 2,
    }


def _initiate(ctx):
    return get_success_data(api_client.create_transaction(
        ctx["tenant"]["id"],
        {"transaction_type": "HIRE", "target_org_unit_id": ctx["unit"]["id"],
         "amount": 0},
        admin_as(ctx["tenant"], ctx["initiator"]["id"]),
    ), 201)


def test_headcount_49_excludes_conditional_step(api):
    """PRD §3.6: "`IF_HEADCOUNT_GE_50` includes when the target unit's
    headcount is at least 50 — the boundary is inclusive". With headcount 49
    the condition fails and the conditional step is skipped, so the
    unconditional step 2 becomes the pending step.
    PRD §3.6: "Conditional steps whose condition fails are skipped, each skip
    appending a `SKIP` event".

    Design: Difficulty/boundary_precision_check/headcount_ge_50_inclusive_boundary
    """
    ctx = _boundary_definition("T-BP2A")
    # Reach exactly 49 direct workers (INIT and MGR already present).
    create_workers(ctx["tenant"]["id"], ctx["unit"]["id"], 47, "W", ctx["admin"])
    unit = get_success_data(
        api_client.get_org_unit(ctx["tenant"]["id"], ctx["unit"]["id"], ctx["admin"])
    )
    assert unit["headcount"] == 49

    inst = _initiate(ctx)
    assert inst["current_step_order"] == 2, (
        "headcount 49 < 50 must skip the conditional step 1"
    )


def test_headcount_50_includes_conditional_step(api):
    """PRD §3.6: "`IF_HEADCOUNT_GE_50` includes when the target unit's
    headcount is at least 50 — the boundary is inclusive". At exactly 50 the
    conditional step is included and becomes the pending step.

    Design: Difficulty/boundary_precision_check/headcount_ge_50_inclusive_boundary
    """
    ctx = _boundary_definition("T-BP2B")
    create_workers(ctx["tenant"]["id"], ctx["unit"]["id"], 48, "W", ctx["admin"])
    unit = get_success_data(
        api_client.get_org_unit(ctx["tenant"]["id"], ctx["unit"]["id"], ctx["admin"])
    )
    assert unit["headcount"] == 50

    inst = _initiate(ctx)
    assert inst["current_step_order"] == 1, (
        "headcount exactly 50 must include the conditional step (inclusive >=)"
    )
