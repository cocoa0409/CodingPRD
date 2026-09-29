"""Establishing the guaranteed maximum price, and milestone variance at the edge.

The pricing build-up is specified so that a collapsed single-pass reading publishes
a materially different number, and the justification gate is specified as a strict
comparison against a ratio that has already been rounded to four places.
"""

from decimal import Decimal
from typing import Tuple

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CM_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_equals,
    assert_fields,
    assert_gmp_identity,
    assert_money,
    assert_money_fields,
    assert_project_axes,
    assert_ratio,
    factories,
    fixtures,
    to_decimal,
)
from test_helpers.types import JsonObject

RIVERSIDE_DATA_HALL = {
    "cm_fee_pct": Decimal("0.0375"),
    "insurance_rate": Decimal("0.0125"),
    "cost_of_work_total": Decimal("40000000.00"),
    "general_conditions_total": Decimal("2500000.00"),
    "owner_contingency_amount": Decimal("1200000.00"),
    "construction_contingency_amount": Decimal("240000.00"),
    "project_kwargs": {
        "name": "Riverside Data Hall",
        "owner_org": "Riverside Metro Owner Authority",
        "precon_fee_amount": Decimal("250000.00"),
    },
}


def _eastbank_with_reconciled_sd_basis(api: ApiClient) -> Tuple[str, JsonObject]:
    """A project whose schematic-design estimate is the reconciled basis at 38,000,000."""
    project = fixtures.create_project(
        api,
        name="Eastbank Water Treatment Expansion",
        owner_org="Eastbank Regional Water Authority",
    )
    basis = fixtures.reconciled_estimate(
        api,
        project["id"],
        milestone_code="SD",
        submitted_cost_of_work=Decimal("38000000.00"),
    )
    return project["id"], basis


def _cd_100(api: ApiClient, project_id: str, amount: Decimal) -> JsonObject:
    """File a construction-documents estimate priced at ``amount``."""
    return fixtures.create_estimate(
        api,
        project_id,
        milestone_code="CD_100",
        submitted_cost_of_work=amount,
    )


def test_base_proposal_prices_through_the_pinned_four_step_build_up(api: ApiClient) -> None:
    """The fee rate lands on base-plus-insurance, never on base-plus-provisional-fee.

    PRD: "Compute a *provisional* fee as the project's `cm_fee_pct` multiplied by that base, rounded half-up to 2 decimal places, and retain it on the proposal as `provisional_fee_amount`."

    PRD: "Compute `insurance_amount` as the project's `insurance_rate` multiplied by the sum of the base and `provisional_fee_amount`, rounded half-up to 2 decimal places."

    PRD: "Compute the **binding** `cm_fee_amount` as the project's `cm_fee_pct` multiplied by the sum of the base and `insurance_amount`, rounded half-up to 2 decimal places."

    PRD: "Compute the proposal's `gmp_amount` as the exact sum of five already-rounded terms: the base, `insurance_amount`, `cm_fee_amount`, `owner_contingency_amount` and `construction_contingency_amount`."

    PRD: "A collapsed single-pass reading that omits insurance from the fee base produces a materially different number, which is exactly why the order is pinned."

    Design: Difficulty/combinatorial_formula/gmp_pricing_pinned_circular_fee_and_insurance_evaluation_order
    """
    priced = fixtures.draft_priced_project(api, **RIVERSIDE_DATA_HALL)
    proposal = priced.proposal

    assert_money_fields(
        proposal,
        {
            "provisional_fee_amount": Decimal("1593750.00"),
            "insurance_amount": Decimal("551171.88"),
            "cm_fee_amount": Decimal("1614418.95"),
            "gmp_amount": Decimal("46105590.83"),
            "amount_delta": Decimal("0.00"),
        },
    )
    assert to_decimal(proposal["gmp_amount"]) != Decimal("46084921.88"), (
        "the guaranteed maximum price was priced by the collapsed single-pass reading "
        "that omits insurance from the fee base"
    )
    assert_fields(
        proposal,
        {"proposal_type": "BASE", "status": "DRAFT", "change_event_id": None},
    )


def test_executing_the_base_proposal_copies_the_priced_build_up_onto_the_project(
    api: ApiClient,
) -> None:
    """Execution funds both pots at once and opens the seven-term closed envelope.

    PRD: "The proposal advances `OWNER_REVIEW → EXECUTED`, the project advances `GMP_UNDER_REVIEW → EXECUTED`, and the proposal's figures are copied onto the project: `gmp_amount` from the proposal's `gmp_amount`, `cost_of_work_budget_total` from `cost_of_work_total`, `general_conditions_total` from `general_conditions_total`, `insurance_amount` from `insurance_amount`, and `cm_fee_amount` from `cm_fee_amount`."

    PRD: "Both contingency pots are funded at once: `owner_contingency_original` and `owner_contingency_remaining` are both set to the proposal's `owner_contingency_amount`, and `construction_contingency_original` and `construction_contingency_remaining` are both set to the proposal's `construction_contingency_amount`, while `contingency_drawn_to_cost_total` is set to 0.00."

    PRD: "The project's `proposed_gmp_amount` is then rolled up — with no pending amendments it equals the executed `gmp_amount` — the `contingency_posture` is re-derived (a fully funded construction pot yields `OPEN`), and the project's `version` increments by 1."

    Design: Difficulty/combinatorial_formula/gmp_pricing_pinned_circular_fee_and_insurance_evaluation_order
    """
    priced = fixtures.executed_project(api, **RIVERSIDE_DATA_HALL)
    project = priced.project

    assert_fields(priced.proposal, {"status": "EXECUTED"})
    assert_project_axes(project, gmp_status="EXECUTED", contingency_posture="OPEN")
    assert_money_fields(
        project,
        {
            "gmp_amount": Decimal("46105590.83"),
            "cost_of_work_budget_total": Decimal("40000000.00"),
            "general_conditions_total": Decimal("2500000.00"),
            "insurance_amount": Decimal("551171.88"),
            "cm_fee_amount": Decimal("1614418.95"),
            "owner_contingency_original": Decimal("1200000.00"),
            "owner_contingency_remaining": Decimal("1200000.00"),
            "construction_contingency_original": Decimal("240000.00"),
            "construction_contingency_remaining": Decimal("240000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
            "proposed_gmp_amount": Decimal("46105590.83"),
        },
    )
    assert_equals(project, "pending_amendment_count", 0)
    assert_gmp_identity(project)


def test_variance_at_exactly_five_percent_submits_without_a_justification(
    api: ApiClient,
) -> None:
    """The gate is strict, so the estimate sitting exactly on the edge clears it.

    PRD: "Whenever a basis is selected, `variance_basis_estimate_id` records that basis row's identifier and `variance_pct` is the basis-relative signed ratio: the new estimate's `submitted_cost_of_work` less the basis estimate's `submitted_cost_of_work`, divided by the basis estimate's `submitted_cost_of_work`, rounded half-up to 4 decimal places."

    PRD: "If the set is non-empty, the candidate with the highest `milestone_rank` wins, ties among equal ranks being broken in favour of the latest `created_at`, and `variance_basis` is recorded as `HIGHEST_RECONCILED_MILESTONE`."

    PRD: "A variance of exactly 0.0500 does not require a justification, and a negative variance, where the milestone came in under its basis, never requires one."

    Design: Difficulty/boundary_precision_check/milestone_variance_at_exact_threshold_and_at_the_half_up_rounding_boundary
    """
    project_id, basis = _eastbank_with_reconciled_sd_basis(api)

    at_threshold = _cd_100(api, project_id, Decimal("39900000.00"))
    assert_ratio(at_threshold["variance_pct"], Decimal("0.0500"), "variance_pct")
    assert_fields(
        at_threshold,
        {
            "variance_basis": "HIGHEST_RECONCILED_MILESTONE",
            "variance_basis_estimate_id": basis["id"],
            "milestone_rank": 4,
            "status": "DRAFT",
        },
    )

    submitted = validate_success(
        api.submit_estimate(
            at_threshold["id"], factories.estimate_submit_payload(), CM_HEADERS
        )
    )
    assert_fields(submitted, {"status": "SUBMITTED", "justification_note": None})
    assert_ratio(submitted["variance_pct"], Decimal("0.0500"), "variance_pct")


def test_variance_rounding_half_up_down_onto_the_threshold_still_clears_the_gate(
    api: ApiClient,
) -> None:
    """A ratio of 0.050049973 rounds down onto 0.0500 before the strict comparison.

    PRD: "Where a comparison is made against a rounded ratio, the ratio is rounded **before** the comparison, never after."

    PRD: "Filing a newer estimate for the same `project_id` and the same `milestone_code` supersedes its predecessor: any prior estimate of that project and milestone whose status is `DRAFT`, `SUBMITTED` or `RETURNED` moves to `SUPERSEDED`, has its `superseded_by_estimate_id` set to the new row's identifier, and has its `version` incremented."

    Design: Difficulty/boundary_precision_check/milestone_variance_at_exact_threshold_and_at_the_half_up_rounding_boundary
    """
    project_id, _ = _eastbank_with_reconciled_sd_basis(api)
    at_threshold = _cd_100(api, project_id, Decimal("39900000.00"))
    validate_success(
        api.submit_estimate(
            at_threshold["id"], factories.estimate_submit_payload(), CM_HEADERS
        )
    )

    rounds_down = _cd_100(api, project_id, Decimal("39901899.00"))
    assert_ratio(rounds_down["variance_pct"], Decimal("0.0500"), "variance_pct")

    submitted = validate_success(
        api.submit_estimate(
            rounds_down["id"], factories.estimate_submit_payload(), CM_HEADERS
        )
    )
    assert_fields(submitted, {"status": "SUBMITTED", "justification_note": None})

    displaced = fixtures.read_estimate(api, at_threshold["id"])
    assert_fields(
        displaced,
        {"status": "SUPERSEDED", "superseded_by_estimate_id": rounds_down["id"]},
    )


def test_variance_rounding_half_up_above_the_threshold_demands_a_justification(
    api: ApiClient,
) -> None:
    """A ratio of 0.05005 rounds half-up to 0.0501 and trips the gate.

    PRD: "Submission re-runs the variance computation against the current reconciled basis, writes a supplied `justification_note` onto the row, and then applies **the justification gate**: when the recomputed `variance_pct` is strictly greater than five percent — that is, strictly greater than 0.0500 — a non-empty `justification_note` must be present, and its absence is rejected with `ERR_VARIANCE_JUSTIFICATION_REQUIRED` (HTTP 422)."

    PRD: "Estimates already at `RECONCILED` are never superseded; they remain the reconciliation basis for everything downstream."

    Design: Difficulty/boundary_precision_check/milestone_variance_at_exact_threshold_and_at_the_half_up_rounding_boundary
    """
    project_id, basis = _eastbank_with_reconciled_sd_basis(api)

    over_threshold = _cd_100(api, project_id, Decimal("39901900.00"))
    assert_ratio(over_threshold["variance_pct"], Decimal("0.0501"), "variance_pct")

    validate_error(
        api.submit_estimate(
            over_threshold["id"], factories.estimate_submit_payload(), CM_HEADERS
        ),
        ApiErrorId.VARIANCE_JUSTIFICATION_REQUIRED,
        422,
    )
    refused = fixtures.read_estimate(api, over_threshold["id"])
    assert_fields(refused, {"status": "DRAFT", "justification_note": None})

    note = "membrane system upgraded after the CD_100 pricing set"
    submitted = validate_success(
        api.submit_estimate(
            over_threshold["id"],
            factories.estimate_submit_payload(justification_note=note),
            CM_HEADERS,
        )
    )
    assert_fields(submitted, {"status": "SUBMITTED", "justification_note": note})

    untouched = fixtures.read_estimate(api, basis["id"])
    assert_fields(
        untouched, {"status": "RECONCILED", "superseded_by_estimate_id": None}
    )
    assert_money(
        untouched["submitted_cost_of_work"],
        Decimal("38000000.00"),
        "submitted_cost_of_work",
    )
