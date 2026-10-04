"""Difficulty queue A: dual-variant calculations (headcount chain, refresh drift)."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    admin_of,
    approver_as,
    admin_as,
    chain_contains,
    create_active_unit,
    create_definition,
    activate_definition,
    add_step,
    create_group_with_member,
    create_prod_sandbox_pair,
    create_tenant,
    create_worker,
    create_workers,
    initiate,
    plan_refresh,
    run_refresh_to,
    set_clock,
    setup_active_definition,
)


def _setup_headcount_divergence():
    """Parent unit with 49 direct workers; child unit with 3 workers
    (including the approver). CONSERVATIVE subtree read = 52 >= 50;
    OPTIMISTIC direct read = 49 < 50."""
    tenant = create_tenant("T-DV1")
    admin = admin_of(tenant)
    tid = tenant["id"]
    parent = create_active_unit(tid, "PARENT", admin, unit_type="DIVISION")
    child = create_active_unit(tid, "CHILD", admin, unit_type="TEAM",
                               parent_unit_id=parent["id"])
    workers = create_workers(tid, parent["id"], 49, "W", admin)
    initiator = workers[0]
    create_workers(tid, child["id"], 2, "C", admin)
    approver = create_worker(tid, child["id"], "MGR", admin)
    group = create_group_with_member(tid, "HR-APPROVERS", approver["id"], admin)
    definition = create_definition(tid, admin, transaction_type="HIRE", name="HireFlow")
    add_step(tid, definition["id"], 1, admin, group_id=group["id"],
             condition="IF_HEADCOUNT_GE_50")
    add_step(tid, definition["id"], 2, admin, group_id=group["id"])
    add_step(tid, definition["id"], 3, admin, group_id=group["id"])
    definition = activate_definition(tid, definition["id"], admin)
    return {
        "tenant": tenant, "admin": admin, "parent": parent, "child": child,
        "initiator": initiator, "approver": approver, "group": group,
        "definition": definition,
    }


def test_step_chain_preview_excludes_what_execution_includes(api):
    """PRD §3.6: "The provisional, optimistic variant — used by the initiation
    preview capability and any reporting — reads the target unit's current
    direct `headcount` only. The effective, conservative variant — used at
    actual execution time — reads direct headcount plus the `ACTIVE` workers of
    descendant `ACTIVE` units, a subtree aggregate; the two variants can
    disagree for identical instance data when descendant units hold workers."
    PRD §3.6: "The preview capability returns the chain as `chain` together
    with the `variant` used."

    Design: Difficulty/dual_variant_calc/step_chain_optimistic_vs_conservative_headcount
    """
    ctx = _setup_headcount_divergence()
    tid = ctx["tenant"]["id"]

    parent = get_success_data(
        api_client.get_org_unit(tid, ctx["parent"]["id"], ctx["admin"])
    )
    assert parent["headcount"] == 49, (
        f"direct headcount must be exactly 49, got {parent['headcount']}"
    )

    # Execution (conservative): subtree aggregate 52 >= 50 -> step 1 pends.
    inst = initiate(ctx, target_unit_id=ctx["parent"]["id"],
                    initiator_id=ctx["initiator"]["id"])
    assert inst["current_step_order"] == 1, (
        "execution variant must include the IF_HEADCOUNT_GE_50 step "
        f"(subtree 52 >= 50), got current_step_order={inst['current_step_order']}"
    )

    # Preview (optimistic): direct-only 49 < 50 -> step 1 excluded.
    preview = validate_success(
        api_client.preview_chain(tid, inst["id"], ctx["admin"])
    )
    assert isinstance(preview.get("chain"), list), "preview must return a chain list"
    assert "variant" in preview, "preview must report the variant used"
    assert not chain_contains(preview["chain"], 1), (
        "optimistic preview (direct headcount 49 < 50) must exclude step 1"
    )
    assert chain_contains(preview["chain"], 2), (
        "optimistic preview must still include the ALWAYS step 2"
    )


def test_step_chain_variants_agree_without_descendants(api):
    """PRD §3.6: "the two variants can disagree for identical instance data
    when descendant units hold workers." With no descendant units the subtree
    aggregate equals the direct headcount, so both variants agree: headcount
    49 < 50 excludes the conditional step at execution and in the preview.
    PRD §3.6: "`IF_HEADCOUNT_GE_50` includes when the target unit's headcount
    is at least 50 — the boundary is inclusive".

    Design: Difficulty/dual_variant_calc/step_chain_optimistic_vs_conservative_headcount
    """
    tenant = create_tenant("T-DV1B")
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "FLAT", admin, unit_type="DIVISION")
    workers = create_workers(tid, unit["id"], 49, "W", admin)
    initiator, approver = workers[0], workers[1]
    group = create_group_with_member(tid, "HR-APPROVERS", approver["id"], admin)
    definition = create_definition(tid, admin, transaction_type="HIRE", name="HireFlow")
    add_step(tid, definition["id"], 1, admin, group_id=group["id"],
             condition="IF_HEADCOUNT_GE_50")
    add_step(tid, definition["id"], 2, admin, group_id=group["id"])
    definition = activate_definition(tid, definition["id"], admin)
    ctx = {"tenant": tenant, "admin": admin, "unit": unit, "initiator": initiator}

    inst = initiate(ctx, target_unit_id=unit["id"], initiator_id=initiator["id"])
    assert inst["current_step_order"] == 2, (
        "with no descendants, 49 < 50 must skip the conditional step at execution"
    )
    preview = validate_success(
        api_client.preview_chain(tid, inst["id"], admin)
    )
    assert not chain_contains(preview["chain"], 1)
    assert chain_contains(preview["chain"], 2)


def _setup_drift_pair(migration_mode, include_workers=None):
    """PRODUCTION source with one ACTIVE definition (2 ACTIVE steps) and one
    ACTIVE security group; SANDBOX target with neither."""
    src, tgt = create_prod_sandbox_pair("T-DV2S", "T-DV2T")
    src_admin = admin_of(src)
    group = create_group_with_member(
        src["id"], "APPROVERS", src["bootstrap_admin_worker_id"], src_admin,
    )
    definition = create_definition(
        src["id"], src_admin, transaction_type="EXPENSE", name="ExpenseFlow",
    )
    add_step(src["id"], definition["id"], 1, src_admin, group_id=group["id"])
    add_step(src["id"], definition["id"], 2, src_admin, kind="REVIEW",
             group_id=group["id"])
    activate_definition(src["id"], definition["id"], src_admin)
    job = plan_refresh(
        tgt, src["id"], "2026-09-02T02:00:00Z",
        migration_mode=migration_mode, include_workers=include_workers,
    )
    return src, tgt, job


def test_refresh_drift_provisional_vs_final_delta_only(api):
    """PRD §3.9: "The provisional score compares the two tenants' current
    configuration: for each `ACTIVE` definition on the source, add 2 when the
    target has no `ACTIVE` definition of the same `transaction_type`, or add 1
    when the target has one but the source definition's version is ahead; then
    for each `ACTIVE` security group on the source, add 1 when the target has
    no non-`DISABLED` group of the same `group_name`."
    PRD §3.9: "under `DELTA_ONLY` the same set is restricted to
    version-advanced objects." and "or all objects when no prior completed
    refresh exists."

    Design: Difficulty/dual_variant_calc/drift_score_provisional_vs_final_delta_only
    """
    src, tgt, job = _setup_drift_pair("DELTA_ONLY")
    assert job["config_drift_score"] == 3, (
        "provisional drift must be 2 (new ACTIVE definition) + 1 (new ACTIVE "
        f"group) = 3, got {job['config_drift_score']}"
    )

    completed = run_refresh_to(tgt, job["id"], "complete",
                               advance_clock_to="2026-09-02T02:30:00Z")
    assert completed["status"] == "COMPLETED"
    # No prior completed refresh: DELTA_ONLY migrates all objects.
    # final = 1 definition + 2 steps + 1 group + 0 (include_workers unset) = 4.
    assert completed["config_drift_score"] == 4, (
        "final drift under DELTA_ONLY with no prior refresh must count every "
        f"written object (1 def + 2 steps + 1 group = 4), got "
        f"{completed['config_drift_score']}"
    )


def test_refresh_drift_final_full_copy_counts_include_workers(api):
    """PRD §3.9: "under `FULL_COPY` that is the number of `ACTIVE` definitions
    in the source, plus the number of `ACTIVE` steps on those definitions, plus
    the number of `ACTIVE` security groups in the source, plus 1 when
    `include_workers` is set".
    PRD §3.9: "The provisional score compares version numbers only and does not
    account for `migration_mode` filtering."

    Design: Difficulty/dual_variant_calc/drift_score_provisional_vs_final_delta_only
    """
    src, tgt, job = _setup_drift_pair("FULL_COPY", include_workers=True)
    assert job["config_drift_score"] == 3, (
        "provisional drift ignores migration_mode and include_workers"
    )

    completed = run_refresh_to(tgt, job["id"], "complete",
                               advance_clock_to="2026-09-02T02:30:00Z")
    assert completed["status"] == "COMPLETED"
    # final = 1 definition + 2 steps + 1 group + 1 (include_workers) = 5.
    assert completed["config_drift_score"] == 5, (
        f"FULL_COPY with include_workers must score 5, got "
        f"{completed['config_drift_score']}"
    )
