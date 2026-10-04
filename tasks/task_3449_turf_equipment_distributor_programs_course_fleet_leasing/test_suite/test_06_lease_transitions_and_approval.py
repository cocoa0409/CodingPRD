"""Lease lifecycle: state legality, terminal lockdown, optimistic concurrency,
immediate visibility, the approval gates (spec, credit, standing), and the
pinned rate computation with tier x seasonal x trade-in credit (PRD §3.4).
"""
from test_helpers import (
    ApiErrorId,
    accept_appraisal,
    cancel_lease,
    create_appraisal_for,
    create_catalog_model,
    create_lease_for,
    make_distributor_manager_headers,
    setup_lease_in_state,
    setup_lease_scenario,
    setup_program,
    submit_lease,
    validate_error,
    validate_success,
)

WK_MDX = {
    "model_code": "WK-MDX",
    "category": "UTILITY_VEHICLE",
    "tier": "PRO",
    "list_price_cents": 2800000,
    "eligible_turf_types": ["BENTGRASS", "BERMUDA", "POA_ANNUA", "MIXED"],
    "warranty_labor_hourly_cap_cents": 8500,
    "parts_support_years": 8,
}


def _setup_credit_stack():
    """CLUB course + M1 (7,500,000) and M2 (2,800,000); lease
    [M1 x4, M2 x2] starting 2027-03-01 (spring peak) with one accepted BOOK
    appraisal (M1, 2200 h, grade B)."""
    ctx = setup_program()
    m2 = create_catalog_model(**WK_MDX)
    lease = create_lease_for(
        ctx["distributor"],
        ctx["course"],
        [{"model_id": ctx["model"]["id"], "qty": 4}, {"model_id": m2["id"], "qty": 2}],
    )
    appraisal = create_appraisal_for(lease, ctx["model"])
    accept_appraisal(appraisal, ctx["course"])
    lease = submit_lease(lease)
    ctx["m2"] = m2
    ctx["lease"] = lease
    ctx["appraisal"] = appraisal
    return ctx


def test_lease_draft_to_active_returns_invalid_state(api, corporate_admin_headers):
    """PRD §2.8: "6. State legality — the requested transition is declared for
    the resource's current state; unknown or inapplicable targets are included
    here, and terminal states accept no transitions (`ERR_INVALID_STATE`,
    409)."

    Design: Corner/state_machines/lease_draft_to_active_returns_invalid_state
    """
    ctx = setup_lease_scenario()
    lease = ctx["lease"]
    resp = api.transition_lease(
        lease["id"], "ACTIVE", lease["version"],
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert after["status"] == "DRAFT" and after["version"] == 1, (
        "no side effects fire on an undeclared transition"
    )


def test_double_submit_spec_rejected_second_time(api):
    """PRD §2.8: "6. State legality — the requested transition is declared for
    the resource's current state; unknown or inapplicable targets are included
    here, and terminal states accept no transitions (`ERR_INVALID_STATE`,
    409)."

    Design: Corner/state_machines/double_submit_spec_rejected_second_time
    """
    ctx = setup_lease_scenario()
    lease = submit_lease(ctx["lease"])
    assert lease["status"] == "SPEC_REVIEW" and lease["version"] == 2
    resp = api.transition_lease(
        lease["id"], "SPEC_REVIEW", lease["version"],
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    # SPEC_REVIEW -> SPEC_REVIEW is not a declared edge; no silent no-op.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancelled_lease_terminal_lockdown(api):
    """PRD §2.8: "unknown or inapplicable targets are included here, and
    terminal states accept no transitions (`ERR_INVALID_STATE`, 409)."
    PRD §3.4: "`CLOSED` and `CANCELLED` are the lease's terminal states."

    Design: Corner/state_machines/cancelled_lease_terminal_lockdown
    """
    ctx = setup_lease_scenario()
    cancelled = cancel_lease(ctx["lease"])
    assert cancelled["status"] == "CANCELLED"
    resp = api.transition_lease(
        cancelled["id"], "SPEC_REVIEW", cancelled["version"],
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_lease_transition_stale_version_returns_412(api, corporate_admin_headers):
    """PRD §2.7: "If that value no longer equals the lease's current `version`
    — because another writer has since submitted, approved, activated,
    cancelled, or been cascade-reverted — the request is rejected with
    `ERR_STALE_LEASE_VERSION` (HTTP 412), preventing the client from driving a
    lease it has not observed."

    Design: Corner/cross_cutting_layers/lease_transition_stale_version_returns_412
    """
    ctx = setup_lease_scenario()
    lease = ctx["lease"]  # version 1
    lease = submit_lease(lease)  # version 2
    resp = api.transition_lease(
        lease["id"], "APPROVED", ctx["lease"]["version"], corporate_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LEASE_VERSION.value)
    after = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert after["status"] == "SPEC_REVIEW" and after["version"] == 2


def test_transition_response_reflects_mutation_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §2.4: "`version` (integer): a system-managed integer that increments
    with every modification to the resource, and serves as the basis for
    optimistic concurrency control where the API exposes it."

    Design: Corner/cross_cutting_layers/transition_response_reflects_mutation_immediately
    """
    ctx = setup_lease_scenario()
    lease = ctx["lease"]
    submitted = validate_success(
        api.transition_lease(
            lease["id"], "SPEC_REVIEW", lease["version"],
            make_distributor_manager_headers(ctx["distributor"]["id"]),
        )
    )
    assert submitted["status"] == "SPEC_REVIEW", (
        "the transition response itself carries the mutated state"
    )
    assert submitted["version"] == 2


def test_lease_approve_spec_violation_rejected(api, corporate_admin_headers):
    """PRD §3.4: "The compliance rule is per line and absolute: a
    `CHAMPIONSHIP` course admits only `TOURNAMENT`-tier models; a `CLUB` course
    admits `TOURNAMENT` or `PRO`; a `MAINTENANCE` course admits `TOURNAMENT`,
    `PRO`, or `STANDARD`"
    PRD §3.4: "The approval re-verifies, under the OCC guard: the distributor's
    standing is still `ACTIVE` (`ERR_DISTRIBUTOR_NOT_ACTIVE`);
    `spec_compliant` is true (`ERR_SPEC_VIOLATION`, HTTP 422)"

    Design: Corner/validations/lease_approve_spec_violation_rejected
    """
    ctx = setup_program(
        course_overrides={"name": "Augusta Pines", "cut_quality_standard": "CHAMPIONSHIP"},
        model_overrides=dict(WK_MDX, eligible_turf_types=["BENTGRASS"]),
    )
    lease = create_lease_for(
        ctx["distributor"], ctx["course"], [{"model_id": ctx["model"]["id"], "qty": 1}]
    )
    submitted = validate_success(
        api.transition_lease(
            lease["id"], "SPEC_REVIEW", lease["version"],
            make_distributor_manager_headers(ctx["distributor"]["id"]),
        )
    )
    assert submitted["spec_compliant"] is False, (
        "a PRO-tier line on a CHAMPIONSHIP course makes the whole lease non-compliant"
    )
    resp = api.transition_lease(
        lease["id"], "APPROVED", submitted["version"], corporate_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_SPEC_VIOLATION.value)


def test_lease_approve_over_credit_limit_rejected(api, corporate_admin_headers):
    """PRD §3.4: "the computed `total_contract_value_cents` does not exceed the
    course's `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 422)."

    Design: Corner/validations/lease_approve_over_credit_limit_rejected
    """
    ctx = setup_program(course_overrides={"credit_limit_cents": 40000000})
    m2 = create_catalog_model(**WK_MDX)
    lease = create_lease_for(
        ctx["distributor"],
        ctx["course"],
        [{"model_id": ctx["model"]["id"], "qty": 4}, {"model_id": m2["id"], "qty": 2}],
    )
    lease = submit_lease(lease)
    # Spring CLUB total: 35,600,000 x 1.08 x 1.06 = 40,754,880 > 40,000,000.
    resp = api.transition_lease(
        lease["id"], "APPROVED", lease["version"], corporate_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)
    after = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert after["status"] == "SPEC_REVIEW"


def test_lease_activate_before_start_returns_lease_not_started(api, corporate_admin_headers):
    """PRD §3.4: "Activation, from `APPROVED` to `ACTIVE`, returns to the
    owning `DistributorManager` under the OCC guard and one temporal gate: the
    current logical date must be on or after `start_date`, else
    `ERR_LEASE_NOT_STARTED` (HTTP 409)."

    Design: Corner/validations/lease_activate_before_start_returns_lease_not_started
    """
    # Default factory start_date 2027-03-01 lies after the 2026-09-01 clock.
    ctx = setup_lease_in_state("APPROVED")
    lease = ctx["lease"]
    resp = api.transition_lease(
        lease["id"], "ACTIVE", lease["version"],
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_STARTED.value)
    after = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert after["status"] == "APPROVED"


def test_approve_from_draft_rejected_invalid_state(api, corporate_admin_headers):
    """PRD §2.8: "When a request could fail several checks at once, the checks
    are evaluated in the following priority order, and the earliest failing
    tier determines the response"
    PRD §2.8: "6. State legality — the requested transition is declared for the
    resource's current state; unknown or inapplicable targets are included
    here, and terminal states accept no transitions (`ERR_INVALID_STATE`,
    409)."
    PRD §2.8: "13. Fiscal ceilings — course credit limits and distributor
    annual claim caps (`ERR_CREDIT_LIMIT_EXCEEDED`,
    `ERR_CLAIM_CAP_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_lease_approve
    """
    ctx = setup_program(
        course_overrides={
            "name": "Penny Pinch GC",
            "turf_profile": "MIXED",
            "cut_quality_standard": "MAINTENANCE",
            "credit_limit_cents": 1,
        }
    )
    lease = create_lease_for(
        ctx["distributor"], ctx["course"], [{"model_id": ctx["model"]["id"], "qty": 1}]
    )
    # DRAFT -> APPROVED is undeclared (tier 6) and would also blow the credit
    # limit (tier 13); the earliest failing tier wins.
    resp = api.transition_lease(
        lease["id"], "APPROVED", lease["version"], corporate_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_rejected_approve_leaves_lease_draft_without_financials(api, corporate_admin_headers):
    """PRD §3.4: "Approval is also when the lease's economics are fixed."
    PRD §3.4: "The lease opens in `DRAFT` with `version` 1"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_lease_approve
    """
    ctx = setup_program(
        course_overrides={
            "name": "Penny Pinch GC",
            "turf_profile": "MIXED",
            "cut_quality_standard": "MAINTENANCE",
            "credit_limit_cents": 1,
        }
    )
    lease = create_lease_for(
        ctx["distributor"], ctx["course"], [{"model_id": ctx["model"]["id"], "qty": 1}]
    )
    resp = api.transition_lease(
        lease["id"], "APPROVED", lease["version"], corporate_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_lease(lease["id"], corporate_admin_headers))
    assert after["status"] == "DRAFT" and after["version"] == 1
    assert after.get("monthly_rate_cents") is None
    assert after.get("total_contract_value_cents") is None


def test_approve_computes_base_total_and_credit(api, corporate_admin_headers):
    """PRD §3.4: "`base_value_cents` is the sum over lines of each model's
    `list_price_cents` multiplied by the line quantity. A tier multiplier
    follows the course's `cut_quality_standard`: 1.15 for `CHAMPIONSHIP`, 1.08
    for `CLUB`, and 1.00 for `MAINTENANCE`. A seasonal factor of 1.06 applies
    when the month of `start_date` is March, April, or May — the spring
    delivery peak — and 1.00 otherwise. `total_contract_value_cents` is the
    base value multiplied by the tier multiplier and the seasonal factor,
    rounded half-up to integer cents exactly once. `trade_in_credit_cents` is
    the sum of `valued_cents` over the lease's appraisals that move to
    `CREDITED` at this approval."

    Design: Difficulty/combinatorial_formula/lease_rate_tier_seasonal_credit_stack
    """
    ctx = _setup_credit_stack()
    lease = ctx["lease"]
    approved = validate_success(
        api.transition_lease(lease["id"], "APPROVED", lease["version"], corporate_admin_headers)
    )
    # base = 7,500,000 x 4 + 2,800,000 x 2 = 35,600,000
    assert approved["base_value_cents"] == 35600000
    # total = round_half_up(35,600,000 x 1.08 x 1.06) = 40,754,880 (rounded once)
    assert approved["total_contract_value_cents"] == 40754880
    # BOOK appraisal (M1, 2200 h, B): age 44 months; book =
    # round_half_up(7,500,000 x (1 - 44/84)) = 3,571,429.
    assert approved["trade_in_credit_cents"] == 3571429


def test_approve_computes_net_and_monthly(api, corporate_admin_headers):
    """PRD §3.4: "`net_contract_value_cents` is the total minus the credit,
    floored at 0. Finally `monthly_rate_cents` is the net value divided by
    `cycle_months`, rounded half-up to integer cents"
    PRD §3.5: "When the owning lease is approved, every `ACCEPTED` appraisal
    moves to `CREDITED` and its `valued_cents` folds into the lease's
    `trade_in_credit_cents` — the credit locks at that instant."

    Design: Difficulty/combinatorial_formula/lease_rate_tier_seasonal_credit_stack
    """
    ctx = _setup_credit_stack()
    lease = ctx["lease"]
    approved = validate_success(
        api.transition_lease(lease["id"], "APPROVED", lease["version"], corporate_admin_headers)
    )
    # net = 40,754,880 - 3,571,429 = 37,183,451
    assert approved["net_contract_value_cents"] == 37183451
    # monthly = round_half_up(37,183,451 / 36) = 1,032,874 (rounded once)
    assert approved["monthly_rate_cents"] == 1032874
    appraisal = validate_success(
        api.get_appraisal(ctx["appraisal"]["id"], corporate_admin_headers)
    )
    assert appraisal["status"] == "CREDITED"
