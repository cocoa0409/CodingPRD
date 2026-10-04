"""Mine plans (PRD §3.7, §2.8, §2.4): submission, OCC-guarded approval,
supersession (one APPROVED plan per type), plan-type applicability, and the
clock-driven REVISION_DUE flip.

Clock note: all readings are >= the startup reading 2026-09-01T00:00:00Z
(PRD §2.4). A plan approved at 2026-09-10T00:00:00Z has next_revision_due_at
2027-03-09T00:00:00Z (approved_at + 180 days).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_mine_plan_payload,
    approve_plan,
    make_operator_rep_headers,
    refresh_mine,
    refresh_plan,
    set_clock,
    setup_registry,
    submit_and_approve_plan,
    submit_mine_plan_payload,
    submit_plan,
    validate_created,
    validate_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["admin_headers"]
_DM = TEST_USERS["district_manager_headers"]


def test_approve_supersede_conserves_single_approved_plan(api):
    """PRD §3.7: "approval stamps `approved_at`, sets `next_revision_due_at`
    180 days later, moves the plan to `APPROVED`, increments the mine's
    `version`, supersedes whichever plan of the same mine and plan type was
    previously `APPROVED` — that prior plan moves to `SUPERSEDED`, and the new
    plan's `supersedes_plan_id` records its id — so that at most one plan per
    type is ever approved."
    PRD §3.7: "the server assigns `revision_no` as one more than the highest
    revision number among prior plans of the same mine and plan type"
    PRD §3.7: "The plans listing filters by `mine_id`, `supersedes_plan_id`,
    `plan_type`, and `status`."

    Design: Difficulty/compensating_invariant/approve_supersede_conserves_single_approved_plan
    """
    set_clock("2026-09-05T09:00:00Z")
    operator, mine, _i1 = setup_registry()

    plan_r1 = submit_plan(mine, operator, "VENTILATION", "doc-vent-r1")
    assert plan_r1["revision_no"] == 1
    plan_r1 = approve_plan(plan_r1)
    assert plan_r1["status"] == "APPROVED"

    # The APPROVED set for (mine, VENTILATION) is exactly {r1} at this point.
    rows, meta = validate_paginated(
        api.list_mine_plans(
            _DM,
            params={"mine_id": mine["id"], "plan_type": "VENTILATION", "status": "APPROVED"},
        )
    )
    assert [r["id"] for r in rows] == [plan_r1["id"]] and meta["total_count"] == 1

    set_clock("2026-10-01T09:00:00Z")
    plan_r2 = submit_plan(refresh_mine(mine["id"]), operator, "VENTILATION", "doc-vent-r2")
    assert plan_r2["revision_no"] == 2
    plan_r2 = approve_plan(plan_r2)

    # Cardinality conserved: the approved set is now exactly {r2}.
    rows, meta = validate_paginated(
        api.list_mine_plans(
            _DM,
            params={"mine_id": mine["id"], "plan_type": "VENTILATION", "status": "APPROVED"},
        )
    )
    assert [r["id"] for r in rows] == [plan_r2["id"]] and meta["total_count"] == 1

    assert refresh_plan(plan_r1["id"])["status"] == "SUPERSEDED"
    plan_r2_after = refresh_plan(plan_r2["id"])
    assert plan_r2_after["status"] == "APPROVED"
    assert plan_r2_after["supersedes_plan_id"] == plan_r1["id"], (
        "the supersede link records the chain"
    )
    assert plan_r2_after["revision_no"] == 2


def test_plan_revision_due_flips_on_clock_advance(api):
    """PRD §2.4: "Advancing the clock at or past an `APPROVED` mine plan's
    `next_revision_due_at` flips that plan to `REVISION_DUE`, as detailed in
    §3.7."
    PRD §3.7: "approval stamps `approved_at`, sets `next_revision_due_at` 180
    days later, moves the plan to `APPROVED`"

    Design: Corner/state_machines/plan_revision_due_flips_on_clock_advance
    """
    set_clock("2026-09-10T00:00:00Z")
    operator, mine, _i1 = setup_registry()
    plan = submit_and_approve_plan(mine, operator, "VENTILATION", "doc-vent-r1")
    assert plan["status"] == "APPROVED"
    assert plan["approved_at"] == "2026-09-10T00:00:00Z"
    # 2026-09-10 + 180 days == 2027-03-09
    assert plan["next_revision_due_at"] == "2027-03-09T00:00:00Z"

    # One second before the due instant: still APPROVED.
    set_clock("2027-03-08T23:59:59Z")
    assert refresh_plan(plan["id"])["status"] == "APPROVED"

    # At the due instant (inclusive): REVISION_DUE.
    set_clock("2027-03-09T00:00:00Z")
    assert refresh_plan(plan["id"])["status"] == "REVISION_DUE"


def test_ventilation_plan_rejected_at_surface_mine(api):
    """PRD §3.7: "Operators maintain three families of **MinePlan**:
    `VENTILATION`, `ROOF_CONTROL`, and `EMERGENCY_RESPONSE`. The first two
    apply only to `UNDERGROUND` mines; an emergency-response plan is required
    of every mine, and submitting a `VENTILATION` or `ROOF_CONTROL` plan for a
    `SURFACE` mine is rejected with `ERR_PLAN_TYPE_NOT_REQUIRED`."

    Design: Corner/validations/ventilation_plan_rejected_at_surface_mine
    """
    operator, mine, _i1 = setup_registry(mine_type="SURFACE")

    resp = api.submit_mine_plan(
        mine["id"],
        submit_mine_plan_payload("VENTILATION", document_ref="doc-vent-x"),
        make_operator_rep_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_TYPE_NOT_REQUIRED)

    resp = api.submit_mine_plan(
        mine["id"],
        submit_mine_plan_payload("EMERGENCY_RESPONSE", document_ref="doc-erp-1"),
        make_operator_rep_headers(operator["id"]),
    )
    plan = validate_created(resp)
    assert plan["plan_type"] == "EMERGENCY_RESPONSE"
    assert plan["revision_no"] == 1
    assert plan["status"] == "SUBMITTED"


def test_operatorrep_cannot_approve_plans(api):
    """PRD §2.1: "`DistrictManager` assigns, reassigns, and cancels
    inspections, terminates imminent-danger orders, approves or rejects mine
    plans, and issues pattern-of-violations notices; it cannot issue citations
    or decide contests."
    PRD §2.1: "A request whose role is declared but not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/operatorrep_cannot_approve_plans
    """
    operator, mine, _i1 = setup_registry()
    plan = submit_plan(mine, operator, "VENTILATION", "doc-vent-r1")

    # Even the mine's own operator is refused: approval is DistrictManager-only.
    mine_now = refresh_mine(mine["id"])
    resp = api.approve_mine_plan(
        plan["id"],
        approve_mine_plan_payload(mine_now["version"]),
        make_operator_rep_headers(operator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert refresh_plan(plan["id"])["status"] == "SUBMITTED"


def test_occ_plan_approve_stale_mine_version_rejected(api):
    """PRD §2.8: "Approving a mine plan requires the request to carry
    `expected_mine_version`, holding the `version` of the owning Mine as the
    client last observed it; because approval supersedes whichever plan of the
    same type is currently approved, a client acting on a stale view of the
    mine would supersede the wrong plan, so a mismatch with the mine's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_plan_approve_stale_mine_version_rejected
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, _i1 = setup_registry()
    plan_v = submit_plan(mine, operator, "VENTILATION", "doc-vent-r1")
    plan_r = submit_plan(refresh_mine(mine["id"]), operator, "ROOF_CONTROL", "doc-roof-r1")

    # Capture the mine version BEFORE the first approval mutates it.
    stale_version = refresh_mine(mine["id"])["version"]

    approved = approve_plan(plan_v)  # current at this moment: succeeds
    assert approved["status"] == "APPROVED"

    # The same captured version is now stale (approval incremented the mine).
    resp = api.approve_mine_plan(
        plan_r["id"], approve_mine_plan_payload(stale_version), _DM
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert refresh_plan(plan_r["id"])["status"] == "SUBMITTED", (
        "a stale approval mutates nothing: no supersession, no approval"
    )
