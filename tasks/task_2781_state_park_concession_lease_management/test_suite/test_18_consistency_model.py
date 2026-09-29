"""Consistency coverage: the award cascade is readable by every other role in
the very next call, with no intervening settle step."""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
    assert_pct_equals,
    assert_status,
    assert_version_is,
)
from test_helpers.test_users import PANELIST_ONE_USER_ID, PANELIST_TWO_USER_ID

RIVAL_SCORES = {
    "score_experience": 75,
    "score_operating_plan": 75,
    "score_capital_investment": 75,
    "score_financial_capacity": 75,
    "score_fee_offer": 75,
}


def test_the_award_cascade_is_readable_immediately_by_every_other_role(api):
    """PRD §3.4: "Candidates are then ranked by `composite_score` from highest to lowest; ties are broken by `offered_franchise_fee_pct` from highest to lowest, then by `proposed_capital_investment_cents` from highest to lowest, then by `created_at` from earliest to latest."
    PRD §3.4: "A successful award fans out."
    PRD §3.4: "The winning proposal moves `SCORED → SELECTED`."
    PRD §3.4: "Every other proposal on this prospectus still in `SUBMITTED`, `UNDER_REVIEW` or `SCORED` moves to `NOT_SELECTED` — a proposal that was never scored is non-responsive by definition, and a proposal stuck `UNDER_REVIEW` with fewer than two sheets is treated the same way."
    PRD §3.4: "The winning terms are copied onto the lease at this moment and never re-derived: `base_fee_pct` from the winner's `offered_franchise_fee_pct`, `minimum_annual_guarantee_cents` from its `proposed_annual_guarantee_cents`, `capital_investment_obligation_cents` from its `proposed_capital_investment_cents`, and `term_years` from the prospectus."
    PRD §3.4: "A `PerformanceBond` is minted alongside it and the lease's `performance_bond_id` points at it."
    PRD §3.4: "Finally the opportunity moves `SOLICITED → AWARDED` and the prospectus itself moves `CLOSED → AWARDED`, which is terminal for both."
    PRD §3.4: "Every row the award touches advances its own `version` by one, and the response is the new lease."
    PRD §3.4: "`term_end` is obtained by adding the whole number of `term_years` to `term_start` and then subtracting one day — a ten-year term starting 2027-03-01 therefore ends 2037-02-28."
    PRD §3.5: "The bond row is created by the award itself, in status `PENDING`, with `lease_id` pointing at the new lease, `surety_name` and `penal_sum_cents` still null, `available_balance_cents` at 0 and `drawn_total_cents` at 0."
    PRD §2.5: "Field visibility follows a simple rule: every field named in this document, whether the client supplied it, the system stamped it, or a formula computed it, is present in the resource object returned for that entity."
    PRD §2.1: "Every role may call every `GET` endpoint, with one exception: the two score-sheet read endpoints are closed to `Concessionaire` — panel score sheets are not disclosed to offerors — while `ProgramAdministrator`, `ConcessionSpecialist`, `ContractingOfficer`, `EvaluationPanelist` and `AuditorGeneral` may all read them."

    Design: Corner/consistency_model/award_cascade_is_readable_immediately_after_the_write_returns
    """
    ctx = X.setup_scored_proposal(api)
    rival = X.register_offeror(
        api, legal_name="Ridgeline Outfitters Inc", bond_capacity_cents=20000000
    )
    rival_proposal = X.submit_proposal(
        api,
        ctx["prospectus_id"],
        rival["id"],
        offered_franchise_fee_pct=4.50,
        proposed_capital_investment_cents=30000000,
        proposed_annual_guarantee_cents=6000000,
    )
    X.begin_review(api, rival_proposal["id"])
    X.file_evaluation(api, rival_proposal["id"], PANELIST_ONE_USER_ID, **RIVAL_SCORES)
    X.file_evaluation(api, rival_proposal["id"], PANELIST_TWO_USER_ID, **RIVAL_SCORES)
    rival_scored = get_success_data(
        api.get_proposal(rival_proposal["id"], X.specialist_headers())
    )
    assert_status(rival_scored, "SCORED")
    assert_pct_equals(rival_scored["composite_score"], "75.00", "composite_score")

    X.set_clock(api, X.POST_DEADLINE_CLOCK)
    X.close_prospectus(api, ctx["prospectus_id"])

    response = api.award_prospectus(
        ctx["prospectus_id"], F.award_payload("2027-03-01"), X.award_officer_headers()
    )
    validate_success(response, 201)
    lease = get_success_data(response)
    assert_lease_state(lease, contract_status="PENDING_EXECUTION", compliance_status="COMPLIANT")
    assert_version_is(lease, 1)
    assert_pct_equals(lease["base_fee_pct"], "5.00", "base_fee_pct")
    assert_fields(
        lease,
        {
            "offeror_id": ctx["offeror_id"],
            "selected_proposal_id": ctx["proposal_id"],
            "prospectus_id": ctx["prospectus_id"],
            "park_id": ctx["park_id"],
            "term_years": 10,
            "term_start": "2027-03-01",
            "term_end": "2037-02-28",
        },
    )
    assert_cents_equals(
        lease["required_bond_amount_cents"], 3000000, "required_bond_amount_cents"
    )

    owner_read = get_success_data(
        api.get_lease(lease["id"], X.concessionaire_headers(ctx["offeror_id"]))
    )
    assert owner_read == lease, "the winner's own read must match the award response exactly"

    bond = get_success_data(api.get_bond(lease["performance_bond_id"], X.auditor_headers()))
    assert_status(bond, "PENDING")
    assert_fields(bond, {"lease_id": lease["id"]})
    assert_cents_equals(bond["required_amount_cents"], 3000000, "required_amount_cents")
    assert_cents_equals(bond["drawn_total_cents"], 0, "drawn_total_cents")
    assert_cents_equals(bond["available_balance_cents"], 0, "available_balance_cents")

    assert_status(
        get_success_data(api.get_proposal(ctx["proposal_id"], X.specialist_headers())),
        "SELECTED",
    )
    assert_status(
        get_success_data(api.get_proposal(rival_proposal["id"], X.specialist_headers())),
        "NOT_SELECTED",
    )
    assert_status(
        get_success_data(api.get_prospectus(ctx["prospectus_id"], X.admin_headers())),
        "AWARDED",
    )
    assert_status(
        get_success_data(api.get_opportunity(ctx["opportunity_id"], X.admin_headers())),
        "AWARDED",
    )
