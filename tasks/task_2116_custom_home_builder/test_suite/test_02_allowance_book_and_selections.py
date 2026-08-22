"""The allowance book: proposals, acceptance, buy-out lock and reconciliation."""

from test_helpers import (
    ApiErrorId,
    assert_allowance_item,
    assert_instant_equals,
    assert_money_equals,
    assert_project_ledger_invariants,
    assert_selection,
    create_selection_payload,
    post_and_approve_cost_entry,
    propose_selection,
    read_allowance_item,
    read_project,
    read_selection,
    set_clock,
    setup_approved_change_order,
    setup_job,
    setup_locked_allowance,
    setup_selected_allowance,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_selection_total_sums_quote_freight_and_installation(api):
    """PRD §3.2: "The server computes `selection_total` as the vendor quote plus freight plus
    installation, rounded half up to two decimals, and files the proposal in `PROPOSED` with
    `decided_at` and `superseded_at` null."
    PRD §3.2: "A new line opens in `OPEN` with `selected_selection_id`,
    `final_variance_amount`, `reconciled_amount`, `material_lead_time_days`, `locked_at`,
    `frozen_at`, and `reconciled_at` all null, and `provisional_variance_amount` at zero."

    Design: Corner/entities/create_selection_computes_selection_total_from_three_inputs
    """
    ctx = setup_job(allowance_category="CABINETRY", allowance_amount=25000.00)
    item = ctx["allowance_item"]

    response = api.create_selection(
        create_selection_payload(
            item["id"],
            item["version"],
            vendor_quote_amount=21000.00,
            freight_amount=1500.00,
            install_amount=1500.00,
            lead_time_days=20,
        ),
        ctx["client_headers"],
    )
    selection = validate_success(response, 201)

    assert_selection(selection)
    assert_money_equals(selection["selection_total"], 24000.00, "selection_total")
    assert selection["status"] == "PROPOSED"
    assert selection["decided_at"] is None
    assert selection["superseded_at"] is None

    line = read_allowance_item(item["id"])
    assert line["status"] == "OPEN"
    assert_money_equals(
        line["provisional_variance_amount"], 0, "provisional_variance_amount"
    )


def test_newer_proposal_supersedes_the_outstanding_one(api):
    """PRD §3.2: "Filing a new proposal against a line that already carries an outstanding
    `PROPOSED` proposal drives that older proposal `PROPOSED → SUPERSEDED` and stamps its
    `superseded_at` with the logical clock now; the allowance item's `version` is incremented
    as part of the same write, which is precisely why the stale-version guard exists."
    PRD §3.2: "Rejecting a proposal advances it `PROPOSED → REJECTED`, stamps `decided_at`,
    and deliberately leaves the parent line in `OPEN` so the homeowner can come back with a
    different vendor."

    Design: Corner/state_machines/newer_selection_supersedes_prior_proposal_on_same_allowance_item
    """
    ctx = setup_job(allowance_category="CABINETRY", allowance_amount=25000.00)
    item = ctx["allowance_item"]

    first = propose_selection(
        ctx,
        vendor_name="Northwood Millwork",
        vendor_quote_amount=21000.00,
        freight_amount=1500.00,
        install_amount=1500.00,
        lead_time_days=20,
    )

    second = validate_success(
        api.create_selection(
            create_selection_payload(
                item["id"],
                read_allowance_item(item["id"])["version"],
                vendor_name="Cascade Cabinet Co",
                vendor_quote_amount=19000.00,
                freight_amount=900.00,
                install_amount=1100.00,
                lead_time_days=30,
            ),
            ctx["client_headers"],
        ),
        201,
    )

    superseded = read_selection(first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_at"] is not None
    assert second["status"] == "PROPOSED"
    assert_money_equals(second["selection_total"], 21000.00, "selection_total")

    line = read_allowance_item(item["id"])
    assert line["status"] == "OPEN"

    rows, _meta = validate_paginated(
        api.list_allowance_item_selections(item["id"], ADMIN, params={"limit": 100})
    )
    proposed = [row for row in rows if row["status"] == "PROPOSED"]
    assert len(proposed) == 1, f"Exactly one proposal may stay outstanding, got {len(proposed)}"


def test_selection_carrying_a_stale_allowance_version_is_refused(api):
    """PRD §2.8: "Proposing a new selection against an allowance line requires the request to
    carry `expected_allowance_item_version`, a non-optional field holding the `version` of the
    target `AllowanceItem` as the client last observed it. If that value does not equal the
    allowance item's current `version`, the proposal is rejected with
    `ERR_STALE_ALLOWANCE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_allowance_version_on_selection_create_returns_412
    """
    ctx = setup_job(allowance_category="CABINETRY", allowance_amount=25000.00)
    item = ctx["allowance_item"]
    stale_version = item["version"]

    first = propose_selection(
        ctx,
        expected_allowance_item_version=stale_version,
        vendor_quote_amount=21000.00,
        freight_amount=1500.00,
        install_amount=1500.00,
        lead_time_days=20,
    )

    response = api.create_selection(
        create_selection_payload(
            item["id"],
            stale_version,
            vendor_name="Cascade Cabinet Co",
            vendor_quote_amount=19000.00,
            freight_amount=900.00,
            install_amount=1100.00,
            lead_time_days=30,
        ),
        ctx["client_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_ALLOWANCE_VERSION, 412)

    untouched = read_selection(first["id"])
    assert untouched["status"] == "PROPOSED"
    assert untouched["superseded_at"] is None

    rows, meta = validate_paginated(
        api.list_allowance_item_selections(item["id"], ADMIN, params={"limit": 100})
    )
    assert meta["total_count"] == 1, "the rejected proposal must not be stored"


def test_selection_proposed_after_the_deadline_is_refused(api):
    """PRD §3.2: "Two temporal and postural gates guard the proposal: the logical clock now
    must be at or before the line's `selection_deadline` — an instant exactly equal to the
    deadline is still in time, while anything later earns `ERR_SELECTION_DEADLINE_PASSED` —
    and the line must be `OPEN` on a project whose `budget_posture` is not `OVER_GMP`, failing
    which the proposal earns `ERR_ALLOWANCE_FROZEN`."

    Design: Corner/validations/selection_proposed_after_deadline_returns_deadline_passed
    """
    ctx = setup_job(
        allowance_category="LIGHTING",
        allowance_amount=9000.00,
        selection_deadline="2026-08-15T00:00:00.000Z",
    )
    item = ctx["allowance_item"]
    set_clock("2026-08-16T00:00:00.000Z")

    response = api.create_selection(
        create_selection_payload(
            item["id"],
            item["version"],
            vendor_name="Lumen Lighting",
            vendor_quote_amount=8000.00,
            freight_amount=200.00,
            install_amount=400.00,
            lead_time_days=10,
        ),
        ctx["client_headers"],
    )
    validate_error(response, ApiErrorId.ERR_SELECTION_DEADLINE_PASSED, 422)

    rows, meta = validate_paginated(
        api.list_allowance_item_selections(item["id"], ADMIN, params={"limit": 100})
    )
    assert meta["total_count"] == 0
    assert read_allowance_item(item["id"])["status"] == "OPEN"


def test_second_decision_on_an_accepted_proposal_is_refused(api):
    """PRD §3.2: "Approving it advances the proposal `PROPOSED → ACCEPTED`, and requires that
    the proposal still be `PROPOSED`, that its parent line still be `OPEN`, and that the
    project's `budget_posture` not be `OVER_GMP`; a decision aimed at a proposal in any other
    status is refused with `ERR_SELECTION_NOT_PENDING`."
    PRD §3.2: "Acceptance stamps `decided_at` with the logical clock now and cascades the
    parent line `OPEN → SELECTED`: `selected_selection_id` is pointed at the accepted proposal,
    `provisional_variance_amount` is computed as the accepted proposal's `selection_total`
    minus the line's `allowance_amount`, rounded half up to two decimals, and that figure
    immediately enters `allowance_variance_total`, which forces `contract_sum_current` and then
    `budget_posture` to be recomputed."

    Design: Corner/errors/second_decision_on_an_accepted_selection_returns_not_pending
    """
    ctx = setup_job(allowance_category="CABINETRY", allowance_amount=25000.00)
    selection = setup_selected_allowance(
        ctx,
        vendor_quote_amount=21000.00,
        freight_amount=1500.00,
        install_amount=1500.00,
        lead_time_days=20,
    )

    response = api.decide_selection(
        selection["id"], {"decision": "REJECT"}, ctx["pm_headers"]
    )
    validate_error(response, ApiErrorId.ERR_SELECTION_NOT_PENDING, 409)

    assert read_selection(selection["id"])["status"] == "ACCEPTED"
    line = read_allowance_item(ctx["allowance_item"]["id"])
    assert line["status"] == "SELECTED"
    assert_money_equals(
        line["provisional_variance_amount"], -1000.00, "provisional_variance_amount"
    )


def test_locking_an_overrun_allowance_line_opens_a_draft_change_order(api):
    """PRD §3.2: "The lock stamps `locked_at` with the logical clock now and copies the
    accepted proposal's `lead_time_days` into the line's `material_lead_time_days`."
    PRD §3.2: "Finally, if the line locked with a `provisional_variance_amount` strictly
    greater than zero, the server automatically opens a change order in `DRAFT` with `origin`
    of `ALLOWANCE_OVERAGE`, `source_allowance_item_id` pointing back at this line,
    `direct_cost` equal to the `provisional_variance_amount`, and `schedule_impact_days` of
    zero — the overrun becomes a priced, client-approvable document rather than a silent
    budget leak."

    Design: Corner/state_machines/allowance_lock_with_positive_variance_auto_creates_draft_change_order
    """
    ctx = setup_job(allowance_category="FLOORING", allowance_amount=18000.00)
    item = ctx["allowance_item"]
    setup_selected_allowance(
        ctx,
        vendor_quote_amount=19000.00,
        freight_amount=1000.00,
        install_amount=1000.00,
        lead_time_days=20,
    )

    locked = validate_success(
        api.settle_allowance_item(
            item["id"], {"action": "LOCK"}, ctx["controller_a_headers"]
        ),
        200,
    )

    assert_allowance_item(locked)
    assert locked["status"] == "LOCKED"
    assert_money_equals(
        locked["provisional_variance_amount"], 3000.00, "provisional_variance_amount"
    )
    assert locked["material_lead_time_days"] == 20
    assert_instant_equals(locked["locked_at"], "2026-08-01T00:00:00.000Z", "locked_at")

    rows, meta = validate_paginated(
        api.list_change_orders(
            ADMIN, params={"source_allowance_item_id": item["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1, "the overrun must open exactly one change order"
    overage = rows[0]
    assert overage["status"] == "DRAFT"
    assert overage["origin"] == "ALLOWANCE_OVERAGE"
    assert_money_equals(overage["direct_cost"], 3000.00, "direct_cost")
    assert overage["schedule_impact_days"] == 0

    project = read_project(ctx["project"]["id"])
    assert_money_equals(
        project["allowance_variance_total"], 3000.00, "allowance_variance_total"
    )
    assert_money_equals(project["contract_sum_current"], 903000.00, "contract_sum_current")
    assert project["budget_posture"] == "WITHIN_BUDGET"
    assert_project_ledger_invariants(project)


def test_reconciliation_replaces_the_provisional_variance_with_the_final_one(api):
    """PRD §3.2: "Reconciliation sets `reconciled_amount` to the sum of those qualifying
    allowance-actual cost entry `amount` values rounded half up to two decimals — entries still
    `PENDING` and entries `REJECTED` are excluded — and sets `final_variance_amount` to that
    reconciled figure minus the line's `allowance_amount`, again rounded half up to two
    decimals."
    PRD §2.6: "`allowance_variance_total` is a sum across the project's allowance items, where
    each item's contribution depends on its own status: an item in `RECONCILED` contributes its
    `final_variance_amount`; an item in `SELECTED` or `LOCKED` contributes its
    `provisional_variance_amount`; an item in `OPEN` or `FROZEN` contributes zero."

    Design: Corner/calculations/allowance_final_variance_replaces_provisional_on_reconcile
    """
    ctx = setup_job(allowance_category="CABINETRY", allowance_amount=25000.00)
    item = ctx["allowance_item"]
    setup_locked_allowance(
        ctx,
        vendor_quote_amount=21000.00,
        freight_amount=1500.00,
        install_amount=1500.00,
        lead_time_days=20,
    )
    post_and_approve_cost_entry(
        ctx,
        entry_type="ALLOWANCE_ACTUAL",
        cost_code="12-400",
        amount=26500.00,
        incurred_at="2026-08-20T00:00:00.000Z",
        source_allowance_item_id=item["id"],
        owner_direct=True,
    )

    reconciled = validate_success(
        api.settle_allowance_item(
            item["id"], {"action": "RECONCILE"}, ctx["controller_a_headers"]
        ),
        200,
    )

    assert reconciled["status"] == "RECONCILED"
    assert_money_equals(reconciled["reconciled_amount"], 26500.00, "reconciled_amount")
    assert_money_equals(
        reconciled["final_variance_amount"], 1500.00, "final_variance_amount"
    )
    assert_money_equals(
        reconciled["provisional_variance_amount"], -1000.00, "provisional_variance_amount"
    )

    project = read_project(ctx["project"]["id"])
    assert_money_equals(
        project["allowance_variance_total"], 1500.00, "allowance_variance_total"
    )
    assert_money_equals(project["contract_sum_current"], 901500.00, "contract_sum_current")
    assert project["budget_posture"] == "WITHIN_BUDGET"
    assert_money_equals(project["cost_to_date"], 26500.00, "cost_to_date")
    assert_project_ledger_invariants(project)


def test_reconciling_without_an_allowance_actual_cost_is_refused(api):
    """PRD §3.2: "Reconciling advances the line `LOCKED → RECONCILED`, and it is legal only
    once at least one cost entry of type `ALLOWANCE_ACTUAL` in status `APPROVED`,
    `INCLUDED_IN_DRAW`, or `PAID` points at the line; without one, the attempt earns
    `ERR_ALLOWANCE_ACTUAL_MISSING`."

    Design: Corner/errors/reconcile_without_allowance_actual_cost_returns_actual_missing
    """
    ctx = setup_job(allowance_category="CABINETRY", allowance_amount=25000.00)
    item = ctx["allowance_item"]
    setup_locked_allowance(
        ctx,
        vendor_quote_amount=21000.00,
        freight_amount=1500.00,
        install_amount=1500.00,
        lead_time_days=20,
    )

    response = api.settle_allowance_item(
        item["id"], {"action": "RECONCILE"}, ctx["controller_a_headers"]
    )
    validate_error(response, ApiErrorId.ERR_ALLOWANCE_ACTUAL_MISSING, 409)

    line = read_allowance_item(item["id"])
    assert line["status"] == "LOCKED"
    assert line["final_variance_amount"] is None

    project = read_project(ctx["project"]["id"])
    assert_money_equals(
        project["allowance_variance_total"], -1000.00, "allowance_variance_total"
    )


def test_proposal_against_a_frozen_allowance_line_is_refused(api):
    """PRD §2.6: "When a recomputation moves the posture *into* `OVER_GMP`, every allowance
    item on that project that is currently `OPEN` cascades to `FROZEN`, has its `frozen_at`
    stamped with the logical clock now, and has its `version` incremented."
    PRD §2.10: "**Allowance line accepting proposals.** A selection may be proposed only
    against an allowance item whose status is `OPEN` and whose project's `budget_posture` is
    anything other than `OVER_GMP`; otherwise `ERR_ALLOWANCE_FROZEN` (409)."

    Design: Corner/errors/selection_against_frozen_allowance_returns_allowance_frozen
    """
    ctx = setup_job(gmp_cap=950000.00)
    setup_approved_change_order(ctx, direct_cost=40000.00, schedule_impact_days=10)

    frozen_line = read_allowance_item(ctx["allowance_item"]["id"])
    assert frozen_line["status"] == "FROZEN"

    response = api.create_selection(
        create_selection_payload(
            frozen_line["id"],
            frozen_line["version"],
            vendor_name="Cascade Flooring",
            vendor_quote_amount=16000.00,
            freight_amount=500.00,
            install_amount=900.00,
            lead_time_days=15,
        ),
        ctx["client_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ALLOWANCE_FROZEN, 409)

    assert read_project(ctx["project"]["id"])["budget_posture"] == "OVER_GMP"
    rows, meta = validate_paginated(
        api.list_allowance_item_selections(frozen_line["id"], ADMIN, params={"limit": 100})
    )
    assert meta["total_count"] == 0
