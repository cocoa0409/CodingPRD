"""Shared savings under both declared bases, and the gates the audited basis adds.

The two bases assemble the settled cost differently from identical project data, so
they can select different construction-manager rates and the fee cap can bind on one
while sitting idle on the other.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    AUDITOR_HEADERS,
    OWNER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_fields,
    assert_money,
    assert_money_fields,
    assert_project_axes,
    factories,
    fixtures,
    to_decimal,
)

HARBORVIEW_CLINIC = {
    "project_kwargs": {
        "name": "Harborview Clinic",
        "precon_fee_amount": Decimal("25000.00"),
    }
}


def _clinic_with_two_reconciled_reports(api: ApiClient) -> str:
    """An executed clinic whose August and September books are both reconciled.

    August carries a single undisputed 1,000,000.00 line. September carries an
    undisputed 140,000.00 line alongside a disputed 25,100.00 one, so the two bases
    see a different settled cost from the same two reports.
    """
    priced = fixtures.executed_project(api, **HARBORVIEW_CLINIC)
    project_id = priced.id

    fixtures.reconciled_cost_report(
        api,
        project_id,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        quantity=Decimal("1000.0000"),
        unit_rate=Decimal("1000.0000"),
    )

    september = fixtures.cost_report(
        api,
        project_id,
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
    )
    fixtures.append_line(
        api,
        september["id"],
        quantity=Decimal("100.0000"),
        unit_rate=Decimal("1400.0000"),
        disputed=False,
    )
    fixtures.append_line(
        api,
        september["id"],
        quantity=Decimal("100.0000"),
        unit_rate=Decimal("251.0000"),
        disputed=True,
    )
    validate_success(
        api.reconcile_cost_report(
            september["id"],
            factories.cost_report_reconcile_payload("RECONCILE"),
            OWNER_HEADERS,
        )
    )
    return project_id


def _open_october_report(api: ApiClient, project_id: str) -> str:
    """An October report carrying one 10,000.00 line and left at OPEN."""
    october = fixtures.cost_report(
        api,
        project_id,
        period_start="2026-10-01T00:00:00Z",
        period_end="2026-11-01T00:00:00Z",
    )
    fixtures.append_line(
        api,
        october["id"],
        quantity=Decimal("100.0000"),
        unit_rate=Decimal("100.0000"),
    )
    return october["id"]


def _adjustment_posted_under_an_open_audit(api: ApiClient, project_id: str) -> None:
    """Exercise audit rights and post a signed 5,000.00 adjustment, leaving it open."""
    fixtures.audit_in_progress(api, project_id)
    validate_success(
        api.audit_action(
            project_id,
            factories.audit_action_payload(
                "POST_ADJUSTMENT", adjustment_amount=Decimal("5000.00")
            ),
            AUDITOR_HEADERS,
        )
    )


def test_the_provisional_basis_counts_disputed_dollars_as_real_cost(
    api: ApiClient,
) -> None:
    """The conservative reading treats the disputed 25,100.00 as money already spent.

    PRD: "The **recoverable base** is the project's `gmp_amount` minus its `cm_fee_amount` minus its `insurance_amount`."

    PRD: "Under `PRE_AUDIT_PROVISIONAL`, the settled cost is the sum of `reported_cost_total` over the project's cost reports whose status is `RECONCILED` or `DISPUTED`."

    PRD: "Disputed dollars are counted **against** the construction manager — treated as real cost — and `audit_adjustment_total` is ignored entirely."

    PRD: "It writes `provisional_savings_pool`, `provisional_cm_savings_share` and `provisional_owner_savings_share`, and moves `closeout_status` `NOT_STARTED → PROVISIONAL_COMPUTED`."

    Design: Difficulty/dual_variant_calc/shared_savings_pre_audit_provisional_vs_post_audit_final_divergence
    """
    project_id = _clinic_with_two_reconciled_reports(api)
    fixtures.closed_audit(api, project_id, adjustment_amount=Decimal("5000.00"))

    project = validate_success(
        api.shared_savings(
            project_id,
            factories.shared_savings_payload("PRE_AUDIT_PROVISIONAL", False),
            OWNER_HEADERS,
        )
    )

    assert_money_fields(
        project,
        {
            "provisional_savings_pool": Decimal("24900.00"),
            "provisional_cm_savings_share": Decimal("6225.00"),
            "provisional_owner_savings_share": Decimal("18675.00"),
            "final_savings_pool": Decimal("0.00"),
            "final_cm_savings_share": Decimal("0.00"),
            "final_owner_savings_share": Decimal("0.00"),
        },
    )
    assert_project_axes(
        project,
        gmp_status="EXECUTED",
        closeout_status="PROVISIONAL_COMPUTED",
        audit_status="CLOSED",
    )


def test_the_audited_basis_diverges_from_the_provisional_one_and_binds_the_fee_cap(
    api: ApiClient,
) -> None:
    """A larger pool selects the 35% tier, and the cap withholds 1,135.60 from it.

    PRD: "Under `POST_AUDIT_FINAL`, the settled cost is the sum of `undisputed_cost_total` over the project's cost reports whose status is `RECONCILED`, **plus** the project's `audit_adjustment_total`."

    PRD: "The percentage is **rounded before the tier comparison**, and both tier boundaries are non-strict on their upper edge: a percentage of at most 0.02 selects a 25% construction-manager rate; otherwise a percentage of at most 0.05 selects 35%; anything above 0.05 selects 50%."

    PRD: "The construction manager's share is the lesser of the uncapped share and the cap, and the owner's share is the pool minus the construction manager's share — so the owner absorbs whatever the cap withholds, and the two shares always add back to the pool exactly."

    PRD: "Because both the pool and therefore the selected tier can move, the two bases can select different construction-manager rates from exactly the same project data, and the cap may bind on one basis while sitting idle on the other."

    Design: Difficulty/dual_variant_calc/shared_savings_pre_audit_provisional_vs_post_audit_final_divergence
    """
    project_id = _clinic_with_two_reconciled_reports(api)
    fixtures.closed_audit(api, project_id, adjustment_amount=Decimal("5000.00"))

    provisional = validate_success(
        api.shared_savings(
            project_id,
            factories.shared_savings_payload("PRE_AUDIT_PROVISIONAL", False),
            OWNER_HEADERS,
        )
    )
    final = validate_success(
        api.shared_savings(
            project_id,
            factories.shared_savings_payload("POST_AUDIT_FINAL", False),
            OWNER_HEADERS,
        )
    )

    assert_money_fields(
        final,
        {
            "final_savings_pool": Decimal("45000.00"),
            "final_cm_savings_share": Decimal("11114.40"),
            "final_owner_savings_share": Decimal("33885.60"),
            "provisional_savings_pool": Decimal("24900.00"),
            "provisional_cm_savings_share": Decimal("6225.00"),
            "provisional_owner_savings_share": Decimal("18675.00"),
        },
    )
    assert to_decimal(final["final_savings_pool"]) != to_decimal(
        provisional["provisional_savings_pool"]
    ), "the two bases assembled the same settled cost, so the divergence was lost"
    assert to_decimal(final["final_cm_savings_share"]) + to_decimal(
        final["final_owner_savings_share"]
    ) == to_decimal(final["final_savings_pool"]), (
        "the two audited shares do not add back to the audited pool exactly"
    )
    assert_project_axes(
        final,
        gmp_status="EXECUTED",
        closeout_status="FINAL_COMPUTED",
        contingency_posture="OPEN",
    )


def test_the_audited_basis_reports_the_unreconciled_report_before_the_audit_gate(
    api: ApiClient,
) -> None:
    """Both audited-basis preconditions fail at once, and the earlier one is reported.

    PRD: "This basis is permitted only when the project's `audit_status` is `CLOSED`, failing which it is rejected with `ERR_AUDIT_NOT_CLOSED` (HTTP 422), and only when no cost report of the project remains at `OPEN`, `DISPUTED` or `RECONCILIATION_HELD`, failing which it is rejected with `ERR_COST_REPORTS_NOT_RECONCILED` (HTTP 422)."

    PRD: "13. Business-constraint rules — `ERR_VARIANCE_JUSTIFICATION_REQUIRED`, then `ERR_ALLOWANCE_UNITS_EXCEEDED`, then `ERR_ALLOWANCE_OVERRUN_UNAUTHORIZED`, then `ERR_ALLOWANCE_REVERSAL_INVALID`, then `ERR_NO_RECONCILED_COST_REPORT`, then `ERR_COST_REPORTS_NOT_RECONCILED`, then `ERR_AUDIT_NOT_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/post_audit_final_savings_depends_on_cost_report_and_audit_states
    """
    project_id = _clinic_with_two_reconciled_reports(api)
    _open_october_report(api, project_id)
    _adjustment_posted_under_an_open_audit(api, project_id)

    validate_error(
        api.shared_savings(
            project_id,
            factories.shared_savings_payload("POST_AUDIT_FINAL", False),
            OWNER_HEADERS,
        ),
        ApiErrorId.COST_REPORTS_NOT_RECONCILED,
        422,
    )

    untouched = fixtures.read_project(api, project_id)
    assert_project_axes(
        untouched,
        closeout_status="NOT_STARTED",
        audit_status="IN_PROGRESS",
        gmp_status="EXECUTED",
    )
    assert_money(
        untouched["final_savings_pool"], Decimal("0.00"), "final_savings_pool"
    )


def test_the_provisional_basis_ignores_both_audited_only_preconditions(
    api: ApiClient,
) -> None:
    """An open report and an open audit do not stop the conservative reading.

    PRD: "It may be run while the audit is anywhere at all, including `NOT_REQUESTED`, and while cost reports remain `OPEN`, `DISPUTED` or held."

    PRD: "Under `PRE_AUDIT_PROVISIONAL`, the settled cost is the sum of `reported_cost_total` over the project's cost reports whose status is `RECONCILED` or `DISPUTED`."

    Design: Difficulty/cross_entity_state_dependency/post_audit_final_savings_depends_on_cost_report_and_audit_states
    """
    project_id = _clinic_with_two_reconciled_reports(api)
    _open_october_report(api, project_id)
    _adjustment_posted_under_an_open_audit(api, project_id)

    project = validate_success(
        api.shared_savings(
            project_id,
            factories.shared_savings_payload("PRE_AUDIT_PROVISIONAL", False),
            OWNER_HEADERS,
        )
    )

    assert_money_fields(
        project,
        {
            "provisional_savings_pool": Decimal("24900.00"),
            "provisional_cm_savings_share": Decimal("6225.00"),
            "provisional_owner_savings_share": Decimal("18675.00"),
            "final_savings_pool": Decimal("0.00"),
        },
    )
    assert_project_axes(
        project, closeout_status="PROVISIONAL_COMPUTED", audit_status="IN_PROGRESS"
    )


def test_the_audited_split_computes_once_both_dependency_gates_clear(
    api: ApiClient,
) -> None:
    """Reconciling the last report clears one gate, and closing the audit clears the other.

    PRD: "A `CLOSE`, also permitted only from `IN_PROGRESS`, moves `audit_status` `IN_PROGRESS → CLOSED` and freezes `audit_adjustment_total` at its accumulated value; no further adjustments are accepted afterwards."

    PRD: "With `execute` false it writes `final_savings_pool`, `final_cm_savings_share` and `final_owner_savings_share` and moves `closeout_status` to `FINAL_COMPUTED`, from either `NOT_STARTED` or `PROVISIONAL_COMPUTED`."

    PRD: "Under `POST_AUDIT_FINAL`, the settled cost is the sum of `undisputed_cost_total` over the project's cost reports whose status is `RECONCILED`, **plus** the project's `audit_adjustment_total`."

    Design: Difficulty/cross_entity_state_dependency/post_audit_final_savings_depends_on_cost_report_and_audit_states
    """
    project_id = _clinic_with_two_reconciled_reports(api)
    october_id = _open_october_report(api, project_id)
    _adjustment_posted_under_an_open_audit(api, project_id)

    reconciled = validate_success(
        api.reconcile_cost_report(
            october_id,
            factories.cost_report_reconcile_payload("RECONCILE"),
            OWNER_HEADERS,
        )
    )
    assert_fields(reconciled, {"status": "RECONCILED"})
    assert_money(
        reconciled["reported_cost_total"], Decimal("10000.00"), "reported_cost_total"
    )

    validate_error(
        api.shared_savings(
            project_id,
            factories.shared_savings_payload("POST_AUDIT_FINAL", False),
            OWNER_HEADERS,
        ),
        ApiErrorId.AUDIT_NOT_CLOSED,
        422,
    )

    closed = validate_success(
        api.audit_action(
            project_id, factories.audit_action_payload("CLOSE"), AUDITOR_HEADERS
        )
    )
    assert_project_axes(closed, audit_status="CLOSED")
    assert_money(
        closed["audit_adjustment_total"], Decimal("5000.00"), "audit_adjustment_total"
    )

    final = validate_success(
        api.shared_savings(
            project_id,
            factories.shared_savings_payload("POST_AUDIT_FINAL", False),
            OWNER_HEADERS,
        )
    )
    assert_money_fields(
        final,
        {
            "final_savings_pool": Decimal("35000.00"),
            "final_cm_savings_share": Decimal("11114.40"),
            "final_owner_savings_share": Decimal("23885.60"),
        },
    )
    assert_project_axes(final, closeout_status="FINAL_COMPUTED", gmp_status="EXECUTED")
