"""Nothing is deferred: one decision, and the whole cascade is already readable.

The contract has no eventual consistency anywhere, so the single test here takes
the largest cascade in the system — a technology selection that mints a capital
project, runs its rate ladder and flips a flag on two pilots — and reads every
consequence with no clock movement and no intervening write.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_decimal,
    assert_equals,
    assert_money_cents,
    assert_rate_ladder,
    assert_status,
    first_row,
)
from test_helpers.fixtures import (
    piloted_evaluation,
    read_entry_point,
    read_pilot,
    register_entry_point,
)
from test_helpers.test_users import FINANCE_OFFICER_HEADERS, TREATMENT_ENGINEER_HEADERS


def test_the_selection_response_already_carries_everything_it_created(api):
    """The decision response, and the very first read after it, are both complete.

    Carbon scores 80.14 against ion exchange's 76.20 with both skids above the
    removal floor, so the decision itself already reports the selected technology.
    The project the decision minted is readable immediately, and on that first read
    it already carries the seeded costs, the
    finished ladder at 7.18 percent and a 341-cent bill, the reactivation route that
    carbon dictates and no concentrate permit — none of it deferred to a later pass or
    computed lazily on first access. The winner is flagged and the loser is not, and
    the entry point is still only piloting, because installation waits on the project
    reaching service.

    PRD: "Finally the project's full financial ladder is computed from those seeded
    figures, so a freshly created project already carries a complete, unfunded rate
    impact."

    Design: Corner/consistency/the_selection_response_already_carries_everything_it_created
    """
    entry_point = register_entry_point(api)
    piloted = piloted_evaluation(api, entry_point["id"], residuals_budget_cents=500000)
    assert_decimal(piloted["gac"]["technology_score"], 80.14, label="technology_score")
    assert_decimal(piloted["ix"]["technology_score"], 76.20, label="technology_score")

    decided = validate_success(
        api.decide_treatment_evaluation(
            piloted["evaluation_id"],
            f.evaluation_decision_payload(
                action="SELECT", decision_note="GAC scores highest above the removal floor"
            ),
            TREATMENT_ENGINEER_HEADERS,
        )
    )
    assert_status(decided, "SELECTED")
    assert_equals(decided, "selected_technology", "GAC")

    project = first_row(
        api.list_capital_projects(
            FINANCE_OFFICER_HEADERS,
            params={"treatment_evaluation_id": piloted["evaluation_id"]},
        )
    )
    assert_money_cents(project["capital_cost_cents"], 680000000, "capital_cost_cents")
    assert_money_cents(project["annual_om_cost_cents"], 31000000, "annual_om_cost_cents")
    assert_rate_ladder(
        project,
        local_share_cents=680000000,
        borrowed_cents=680000000,
        annual_debt_service_cents=41586568,
        base_annual_requirement_cents=72586568,
        provisional_rate_impact_pct=7.07,
        surcharge_bp=150,
        final_annual_requirement_cents=73675367,
        rate_impact_pct=7.18,
        uniform_monthly_increase_cents=341,
        monthly_bill_increase_cents=341,
    )
    assert_equals(project, "funding_status", "NOT_APPLIED")
    assert_equals(project, "construction_status", "PLANNED")
    assert_equals(project, "required_disposal_method", "REACTIVATION")
    assert_equals(project, "concentrate_permit_required", False)

    assert_equals(read_pilot(api, piloted["gac_id"]), "selected", True)
    assert_equals(read_pilot(api, piloted["ix_id"]), "selected", False)
    assert_equals(read_entry_point(api, entry_point["id"]), "treatment_status", "PILOT")
