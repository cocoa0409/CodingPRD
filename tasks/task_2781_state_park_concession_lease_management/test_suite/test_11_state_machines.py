"""State machine coverage: the transitions each entity admits, the transitions
it refuses, its initial fields, and the cascades a transition drags with it."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
    assert_null,
    assert_pct_equals,
    assert_status,
    assert_version_is,
)

MONTHLY_RECEIPTS = {
    "lodging_receipts_cents": 10000000,
    "food_beverage_receipts_cents": 20000000,
    "retail_receipts_cents": 8000000,
    "activity_receipts_cents": 2000000,
}
ROOF_IMPROVEMENT = {
    "description": "Lodge roof replacement",
    "funding_source": "CONCESSIONAIRE_CAPITAL",
    "proposed_cost_cents": 5000000,
    "useful_life_years": 20,
    "construction_window_start": "2027-04-01",
    "construction_window_end": "2027-07-01",
    "ownership_at_expiration": "AGENCY",
}


def _draft_prospectus_on_an_approved_opportunity(api):
    """A park, an opportunity cleared for solicitation on a 160,000,000
    projection, and a DRAFT prospectus whose window has not opened yet."""
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    park = X.register_park(api)
    opportunity = X.approved_opportunity(api, park["id"])
    prospectus = X.draft_prospectus(api, opportunity["id"])
    return {
        "park_id": park["id"],
        "opportunity_id": opportunity["id"],
        "prospectus_id": prospectus["id"],
    }


def test_issue_moves_the_prospectus_to_issued_and_solicits_the_opportunity(api):
    """PRD §3.2: "On success the prospectus moves `DRAFT → ISSUED`, its opportunity is dragged from `APPROVED_FOR_SOLICITATION` to `SOLICITED`, and both rows advance their `version` by one."
    PRD §3.1: "The projection itself is deliberately simple: `estimated_annual_gross_receipts_cents` is the comparable's receipts multiplied by `market_capture_pct` and divided by one hundred, with the result rounded half up to whole cents."

    Design: Corner/state_machines/prospectus_issue_moves_draft_to_issued_and_solicits_the_opportunity
    """
    ctx = _draft_prospectus_on_an_approved_opportunity(api)

    response = api.issue_prospectus(ctx["prospectus_id"], X.specialist_headers())
    validate_success(response, 200)
    prospectus = get_success_data(response)
    assert_status(prospectus, "ISSUED")
    assert_version_is(prospectus, 2)

    opportunity = get_success_data(
        api.get_opportunity(ctx["opportunity_id"], X.award_officer_headers())
    )
    assert_status(opportunity, "SOLICITED")
    assert_cents_equals(
        opportunity["estimated_annual_gross_receipts_cents"],
        160000000,
        "estimated_annual_gross_receipts_cents",
    )


def test_begin_fieldwork_on_a_window_with_no_accepted_report_is_refused(api):
    """PRD §3.8: "Beginning fieldwork moves it `OPENED → FIELDWORK` and freezes the baseline: `reported_gross_receipts_cents` becomes the sum of `total_receipts_cents` over the lease's `ACCEPTED` reports whose half-open periods lie inside the audit window."
    PRD §3.8: "At least one such report must exist, else `ERR_AUDIT_PERIOD_EMPTY` — there is nothing to audit."
    PRD §2.9: "**Audit substance** — `ERR_AUDIT_PERIOD_EMPTY` when fieldwork begins and no `ACCEPTED` report lies inside the audit window."

    Design: Corner/state_machines/audit_begin_fieldwork_with_no_accepted_report_in_window_is_rejected
    """
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    audit = X.open_audit(
        api,
        ctx["lease_id"],
        audit_period_start="2027-04-01",
        audit_period_end="2027-07-01",
        scope_note="Opening review of the first operating quarter.",
    )

    response = api.begin_fieldwork(audit["id"], X.auditor_headers())
    validate_error(response, "ERR_AUDIT_PERIOD_EMPTY", 409)

    audit = get_success_data(api.get_audit(audit["id"], X.award_officer_headers()))
    assert_status(audit, "OPENED")
    assert_null(audit, "reported_gross_receipts_cents")


def test_award_mints_the_lease_and_its_pending_bond_with_every_computed_term(api):
    """PRD §3.4: "The winning proposal moves `SCORED → SELECTED`."
    PRD §3.4: "A `Lease` is minted, in `contract_status` `PENDING_EXECUTION` and `compliance_status` `COMPLIANT`, carrying the `park_id` inherited from the opportunity, the `prospectus_id` of this solicitation, the `offeror_id` and `selected_proposal_id` of the winner, `awarded_by_user_id` set to the acting `X-User-ID`, `executed_by_user_id` still null, and `predecessor_lease_id` null — a lease is first-generation until a close-out elsewhere names it as a successor."
    PRD §3.4: "The winning terms are copied onto the lease at this moment and never re-derived: `base_fee_pct` from the winner's `offered_franchise_fee_pct`, `minimum_annual_guarantee_cents` from its `proposed_annual_guarantee_cents`, `capital_investment_obligation_cents` from its `proposed_capital_investment_cents`, and `term_years` from the prospectus."
    PRD §3.4: "Finally the opportunity moves `SOLICITED → AWARDED` and the prospectus itself moves `CLOSED → AWARDED`, which is terminal for both."
    PRD §3.4: "`term_end` is obtained by adding the whole number of `term_years` to `term_start` and then subtracting one day — a ten-year term starting 2027-03-01 therefore ends 2037-02-28."
    PRD §3.5: "The bond row is created by the award itself, in status `PENDING`, with `lease_id` pointing at the new lease, `surety_name` and `penal_sum_cents` still null, `available_balance_cents` at 0 and `drawn_total_cents` at 0."
    PRD §3.5: "What it must eventually be worth is decided at award and stored twice: as `required_bond_amount_cents` on the lease and, copied from it, as `required_amount_cents` on the bond."
    PRD §3.5: "Take one quarter of the lease's `minimum_annual_guarantee_cents`, rounded half up to whole cents; take one tenth of the lease's `capital_investment_obligation_cents`, also rounded half up to whole cents; then take whichever is greatest of those two rounded components and a hard floor of twenty-five thousand dollars."
    PRD §3.5: "For a term of ten years or fewer that greatest value is the requirement as it stands."

    Design: Corner/state_machines/award_mints_lease_and_pending_bond_with_all_computed_terms
    """
    ctx = X.setup_scored_proposal(api)
    X.set_clock(api, X.POST_DEADLINE_CLOCK)
    X.close_prospectus(api, ctx["prospectus_id"])

    response = api.award_prospectus(
        ctx["prospectus_id"], F.award_payload("2027-03-01"), X.award_officer_headers()
    )
    validate_success(response, 201)
    lease = get_success_data(response)
    assert_lease_state(lease, contract_status="PENDING_EXECUTION", compliance_status="COMPLIANT")
    assert_fields(
        lease,
        {
            "park_id": ctx["park_id"],
            "prospectus_id": ctx["prospectus_id"],
            "offeror_id": ctx["offeror_id"],
            "selected_proposal_id": ctx["proposal_id"],
            "predecessor_lease_id": None,
            "awarded_by_user_id": "officer-award-01",
            "executed_by_user_id": None,
            "term_years": 10,
            "term_start": "2027-03-01",
            "term_end": "2037-02-28",
            "agency_maintenance_scope": "STRUCTURAL_ONLY",
            "insurance_expires_on": None,
        },
    )
    assert_pct_equals(lease["base_fee_pct"], "5.00", "base_fee_pct")
    assert_cents_equals(
        lease["minimum_annual_guarantee_cents"], 6000000, "minimum_annual_guarantee_cents"
    )
    assert_cents_equals(
        lease["capital_investment_obligation_cents"],
        30000000,
        "capital_investment_obligation_cents",
    )
    assert_cents_equals(
        lease["required_bond_amount_cents"], 3000000, "required_bond_amount_cents"
    )
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )
    assert_cents_equals(
        lease["maintenance_reserve_balance_cents"], 0, "maintenance_reserve_balance_cents"
    )
    assert_cents_equals(
        lease["capital_investment_completed_cents"], 0, "capital_investment_completed_cents"
    )

    bond = get_success_data(
        api.get_bond(lease["performance_bond_id"], X.award_officer_headers())
    )
    assert_status(bond, "PENDING")
    assert bond["lease_id"] == lease["id"], bond["lease_id"]
    assert_cents_equals(bond["required_amount_cents"], 3000000, "required_amount_cents")
    assert_null(bond, "penal_sum_cents")
    assert_cents_equals(bond["available_balance_cents"], 0, "available_balance_cents")
    assert_cents_equals(bond["drawn_total_cents"], 0, "drawn_total_cents")

    prospectus = get_success_data(
        api.get_prospectus(ctx["prospectus_id"], X.award_officer_headers())
    )
    assert_status(prospectus, "AWARDED")
    proposal = get_success_data(
        api.get_proposal(ctx["proposal_id"], X.award_officer_headers())
    )
    assert_status(proposal, "SELECTED")
    opportunity = get_success_data(
        api.get_opportunity(ctx["opportunity_id"], X.award_officer_headers())
    )
    assert_status(opportunity, "AWARDED")


def test_a_new_capital_improvement_starts_proposed_with_null_approval_fields(api):
    """PRD §3.7: "The improvement is created in `PROPOSED`, `approved_cost_cents`, `actual_cost_cents`, `in_service_date`, `unamortized_value_cents` and `deficiency_note` all null, and `park_id` copied from the lease so that closure windows can be counted per park without walking the lease graph."
    PRD §3.1: "`open_closure_window_count` is the number of capital improvements on the park whose status is `APPROVED` — in other words, the number of construction closure windows the agency currently has reserved at that park."
    PRD §3.7: "`capital_investment_obligation_cents`, copied onto the lease from the winning bid, is the total the concessionaire has committed to spend over the term, and `capital_investment_completed_cents` is how much of that obligation it has actually discharged — the sum, over the lease's improvements that have reached `COMPLETED`, `VESTED_IN_AGENCY` or `COMPENSABLE`, of the lesser of each improvement's `actual_cost_cents` and its `approved_cost_cents`."
    PRD §2.5: "A newly created record has `version` 1 and `updated_at` equal to `created_at`; every subsequent mutation of that record advances `version` by exactly one and refreshes `updated_at` to the logical clock instant at which the mutation was applied."

    Design: Corner/state_machines/new_capital_improvement_starts_in_proposed_with_null_approval_fields
    """
    ctx = X.setup_active_lease(api)

    response = api.create_improvement(
        dict(ROOF_IMPROVEMENT, lease_id=ctx["lease_id"]),
        X.concessionaire_headers(ctx["offeror_id"]),
    )
    validate_success(response, 201)
    improvement = get_success_data(response)
    assert_status(improvement, "PROPOSED")
    assert improvement["lease_id"] == ctx["lease_id"], improvement["lease_id"]
    assert improvement["park_id"] == ctx["park_id"], improvement["park_id"]
    assert_null(
        improvement,
        "approved_cost_cents",
        "actual_cost_cents",
        "in_service_date",
        "unamortized_value_cents",
        "deficiency_note",
    )
    assert_version_is(improvement, 1)

    park = get_success_data(api.get_park(ctx["park_id"], X.award_officer_headers()))
    assert park["open_closure_window_count"] == 0, park["open_closure_window_count"]

    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["capital_investment_completed_cents"], 0, "capital_investment_completed_cents"
    )


def test_a_withdrawn_proposal_cannot_be_resubmitted(api):
    """PRD §3.3: "Withdrawal is the offeror's own exit and is available from `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED` and `SCORED`, in every case landing on `WITHDRAWN`, which is terminal."
    PRD §3.3: "`SELECTED`, `NOT_SELECTED` and `WITHDRAWN` are the proposal's three terminal states; nothing moves a proposal out of them."
    PRD §3.3: "The offeror closes the loop by resubmitting, moving `REVISION_REQUESTED → SUBMITTED` and overwriting exactly three fields from the request body: `offered_franchise_fee_pct`, `proposed_capital_investment_cents` and `proposed_annual_guarantee_cents`."
    PRD §2.9: "**The path resource's own status** — the addressed row's own state admits the requested transition, else that entity's status code: `ERR_OPPORTUNITY_STATUS_INVALID`, `ERR_PROSPECTUS_STATUS_INVALID`, `ERR_OFFEROR_STATUS_INVALID`, `ERR_PROPOSAL_STATUS_INVALID`, `ERR_LEASE_STATUS_INVALID`, `ERR_BOND_STATUS_INVALID`, `ERR_IMPROVEMENT_STATUS_INVALID`, `ERR_OPERATING_PLAN_STATUS_INVALID`, `ERR_REPORT_STATUS_INVALID`, `ERR_RECONCILIATION_STATUS_INVALID`, `ERR_AUDIT_STATUS_INVALID` or `ERR_COMPLIANCE_ACTION_STATUS_INVALID`, all HTTP 409."

    Design: Corner/state_machines/withdrawn_proposal_cannot_be_resubmitted
    """
    ctx = X.setup_issued_prospectus(api)
    proposal = X.submit_proposal(api, ctx["prospectus_id"], ctx["offeror_id"])
    owner_headers = X.concessionaire_headers(ctx["offeror_id"])
    validate_success(api.withdraw_proposal(proposal["id"], owner_headers), 200)

    response = api.resubmit_proposal(
        proposal["id"],
        F.resubmit_proposal_payload(
            offered_franchise_fee_pct=6.00,
            proposed_capital_investment_cents=32000000,
            proposed_annual_guarantee_cents=7000000,
        ),
        owner_headers,
    )
    validate_error(response, "ERR_PROPOSAL_STATUS_INVALID", 409)

    stored = get_success_data(api.get_proposal(proposal["id"], X.award_officer_headers()))
    assert_status(stored, "WITHDRAWN")
    assert_pct_equals(stored["offered_franchise_fee_pct"], "5.00", "offered_franchise_fee_pct")
    assert_cents_equals(
        stored["proposed_capital_investment_cents"],
        30000000,
        "proposed_capital_investment_cents",
    )
    assert stored["revision_round"] == 0, stored["revision_round"]


def test_a_second_debarment_on_an_already_debarred_offeror_is_refused(api):
    """PRD §3.3: "An `ELIGIBLE` offeror moves to `DEBARRED`, which is terminal; a second attempt on an already-debarred offeror is refused with `ERR_OFFEROR_STATUS_INVALID`."
    PRD §3.3: "The offeror's own `version` advances by one."
    PRD §2.5: "A newly created record has `version` 1 and `updated_at` equal to `created_at`; every subsequent mutation of that record advances `version` by exactly one and refreshes `updated_at` to the logical clock instant at which the mutation was applied."

    Design: Corner/state_machines/second_debar_on_an_already_debarred_offeror_is_rejected
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    offeror = X.register_offeror(api)
    validate_success(api.debar_offeror(offeror["id"], X.admin_headers()), 200)

    response = api.debar_offeror(offeror["id"], X.admin_headers())
    validate_error(response, "ERR_OFFEROR_STATUS_INVALID", 409)

    stored = get_success_data(api.get_offeror(offeror["id"], X.award_officer_headers()))
    assert_status(stored, "DEBARRED")
    assert_version_is(stored, 2)


def test_closing_a_draft_prospectus_reports_the_status_error_not_the_open_window(api):
    """PRD §2.9: "Checks are grouped into ordered bands, evaluated strictly from the lowest band upward, and **the lowest-numbered failing check is the one reported**."
    PRD §2.9: "**The path resource's own status** — the addressed row's own state admits the requested transition, else that entity's status code: `ERR_OPPORTUNITY_STATUS_INVALID`, `ERR_PROSPECTUS_STATUS_INVALID`, `ERR_OFFEROR_STATUS_INVALID`, `ERR_PROPOSAL_STATUS_INVALID`, `ERR_LEASE_STATUS_INVALID`, `ERR_BOND_STATUS_INVALID`, `ERR_IMPROVEMENT_STATUS_INVALID`, `ERR_OPERATING_PLAN_STATUS_INVALID`, `ERR_REPORT_STATUS_INVALID`, `ERR_RECONCILIATION_STATUS_INVALID`, `ERR_AUDIT_STATUS_INVALID` or `ERR_COMPLIANCE_ACTION_STATUS_INVALID`, all HTTP 409."
    PRD §2.9: "`ERR_SUBMISSION_WINDOW_OPEN` — the clock must be at or after `submission_deadline` before the solicitation may be closed."
    PRD §3.2: "Closing the window is the mirror image: an `ISSUED` prospectus moves to `CLOSED` only once the logical clock has reached or passed `submission_deadline`, and an attempt made while proposals could still legitimately arrive is refused with `ERR_SUBMISSION_WINDOW_OPEN`."

    Design: Corner/state_machines/prospectus_close_before_issue_returns_prospectus_status_invalid
    """
    ctx = _draft_prospectus_on_an_approved_opportunity(api)

    response = api.close_prospectus(ctx["prospectus_id"], X.specialist_headers())
    validate_error(response, "ERR_PROSPECTUS_STATUS_INVALID", 409)

    prospectus = get_success_data(
        api.get_prospectus(ctx["prospectus_id"], X.award_officer_headers())
    )
    assert_status(prospectus, "DRAFT")
    assert_version_is(prospectus, 1)

    opportunity = get_success_data(
        api.get_opportunity(ctx["opportunity_id"], X.award_officer_headers())
    )
    assert_status(opportunity, "APPROVED_FOR_SOLICITATION")


def test_returning_then_resubmitting_an_improvement_lands_it_back_in_proposed(api):
    """PRD §3.7: "The agency may return it instead, moving `PROPOSED → RETURNED` and persisting a `deficiency_note` that states what was wrong."
    PRD §3.7: "The concessionaire revises and resubmits, moving `RETURNED → PROPOSED` while overwriting `proposed_cost_cents`, `useful_life_years`, `construction_window_start` and `construction_window_end` from the request body and clearing `deficiency_note` back to null."
    PRD §3.7: "Resubmission is confined to the owning offeror, and the `PROPOSED → RETURNED → PROPOSED` cycle may repeat as often as the parties need."
    PRD §2.5: "A newly created record has `version` 1 and `updated_at` equal to `created_at`; every subsequent mutation of that record advances `version` by exactly one and refreshes `updated_at` to the logical clock instant at which the mutation was applied."

    Design: Corner/state_machines/improvement_return_and_resubmit_loop_returns_it_to_proposed
    """
    ctx = X.setup_active_lease(api)
    improvement = X.propose_improvement(
        api, ctx["lease_id"], ctx["offeror_id"], **ROOF_IMPROVEMENT
    )
    returned = get_success_data(
        api.return_improvement(
            improvement["id"],
            F.return_improvement_payload(
                deficiency_note=(
                    "Roof assembly lacks a snow-load calculation and the closure "
                    "window straddles the peak season."
                )
            ),
            X.award_officer_headers(),
        )
    )
    assert_status(returned, "RETURNED")

    response = api.resubmit_improvement(
        improvement["id"],
        F.resubmit_improvement_payload(
            proposed_cost_cents=5600000,
            useful_life_years=25,
            construction_window_start="2027-10-01",
            construction_window_end="2027-12-01",
        ),
        X.concessionaire_headers(ctx["offeror_id"]),
    )
    validate_success(response, 200)
    resubmitted = get_success_data(response)
    assert_status(resubmitted, "PROPOSED")
    assert_cents_equals(resubmitted["proposed_cost_cents"], 5600000, "proposed_cost_cents")
    assert resubmitted["useful_life_years"] == 25, resubmitted["useful_life_years"]
    assert_fields(
        resubmitted,
        {
            "construction_window_start": "2027-10-01",
            "construction_window_end": "2027-12-01",
            "deficiency_note": None,
            "approved_cost_cents": None,
        },
    )
    assert_version_is(resubmitted, 3)

    park = get_success_data(api.get_park(ctx["park_id"], X.award_officer_headers()))
    assert park["open_closure_window_count"] == 0, park["open_closure_window_count"]


def test_accepting_a_cure_clears_the_deficiency_only_once_no_notice_remains(api):
    """PRD §3.9: "The action is created in `NOTICE_ISSUED` with `origin` set to `AGENCY_ISSUED` — the value that distinguishes an officer's notice from the `SYSTEM_ISSUED` notices the audit cascade of §3.8 mints — and the lease's `compliance_status` moves `COMPLIANT → DEFICIENT` with its `version` advancing by one."
    PRD §3.9: "A lease may carry several notices at once, and this is why the return to compliance is conditional."
    PRD §3.9: "When the officer accepts a cure, moving the action `NOTICE_ISSUED → CURE_ACCEPTED` and persisting a `cure_note`, the lease returns `DEFICIENT → COMPLIANT` only if no other compliance action on that lease is still in `NOTICE_ISSUED`; if one is, the action closes but the lease stays deficient and its `version` does not move."
    PRD §3.9: "Note also what deficiency does *not* do: a `DEFICIENT` lease is still `ACTIVE`, so it may still file reports, submit operating plans, propose improvements and be reconciled."

    Design: Corner/state_machines/accept_cure_clears_the_deficiency_only_when_no_other_notice_remains
    """
    ctx = X.setup_active_lease(api)
    first = X.issue_compliance_action(
        api,
        ctx["lease_id"],
        action_type="OPERATING_STANDARD",
        deficiency_note="Posted lodging rates exceeded the approved schedule.",
        cure_deadline="2027-04-01T00:00:00Z",
    )
    second = X.issue_compliance_action(
        api,
        ctx["lease_id"],
        action_type="INSURANCE_LAPSE",
        deficiency_note="Marina annex is missing from the certificate on file.",
        cure_deadline="2027-04-01T00:00:00Z",
    )
    assert first["origin"] == "AGENCY_ISSUED", first["origin"]
    assert second["origin"] == "AGENCY_ISSUED", second["origin"]

    response = api.accept_cure(
        first["id"],
        F.accept_cure_payload(
            cure_note="Rate card corrected and re-posted at every trailhead kiosk."
        ),
        X.exec_officer_headers(),
    )
    validate_success(response, 200)
    assert_status(get_success_data(response), "CURE_ACCEPTED")
    assert_lease_state(
        X.read_lease(api, ctx["lease_id"]),
        contract_status="ACTIVE",
        compliance_status="DEFICIENT",
    )

    response = api.accept_cure(
        second["id"],
        F.accept_cure_payload(
            cure_note="Marina annex certificate filed and verified with the carrier."
        ),
        X.exec_officer_headers(),
    )
    validate_success(response, 200)
    assert_status(get_success_data(response), "CURE_ACCEPTED")
    assert_lease_state(
        X.read_lease(api, ctx["lease_id"]),
        contract_status="ACTIVE",
        compliance_status="COMPLIANT",
    )


def test_accepting_a_report_moves_the_three_lease_ledgers_at_once(api):
    """PRD §3.8: "Acceptance is a `ContractingOfficer` act moving a report `SUBMITTED → ACCEPTED`, and it logs the cash: `remittance_received_cents` must equal the report's `assessed_fee_cents` to the cent, else `ERR_REMITTANCE_MISMATCH`."
    PRD §3.8: "On success the remittance is persisted and three lease ledger fields move at once — `reported_receipts_ytd_cents` rises by the report's `total_receipts_cents`, `remitted_fee_ytd_cents` rises by the logged remittance, and `maintenance_reserve_balance_cents` rises by `maintenance_reserve_due_cents` — with the report and the lease each advancing their `version` by one."
    PRD §3.8: "Exactly one `APPROVED` operating plan on the same lease must have a closed season window `season_start` through `season_end` that covers every calendar day of the half-open reporting period; that plan's identifier is written onto the report as `operating_plan_id`, and if no approved season covers the period the filing is refused with `ERR_NO_APPROVED_OPERATING_PLAN`."
    PRD §3.8: "**The evaluation order is pinned**: for each of the four categories, multiply that category's receipts by that category's rate, divide by one hundred, and round half up to whole cents; then add the four rounded category fees together in the order lodging, food and beverage, retail, activities."
    PRD §3.8: "`maintenance_reserve_due_cents` is one half of one percent of `total_receipts_cents`, rounded half up to whole cents."

    Design: Corner/state_machines/accepting_a_report_accrues_the_maintenance_reserve_into_the_lease
    """
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-05-02T00:00:00Z")
    report = X.file_report(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        period_start="2027-04-01",
        period_end="2027-05-01",
        **MONTHLY_RECEIPTS,
    )
    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(lease["reported_receipts_ytd_cents"], 0, "reported_receipts_ytd_cents")
    assert_cents_equals(lease["remitted_fee_ytd_cents"], 0, "remitted_fee_ytd_cents")
    assert_cents_equals(
        lease["maintenance_reserve_balance_cents"], 0, "maintenance_reserve_balance_cents"
    )

    response = api.accept_report(
        report["id"], F.accept_report_payload(2150000), X.exec_officer_headers()
    )
    validate_success(response, 200)
    accepted = get_success_data(response)
    assert_status(accepted, "ACCEPTED")
    assert accepted["operating_plan_id"] == ctx["plan_id"], accepted["operating_plan_id"]
    assert_cents_equals(accepted["total_receipts_cents"], 40000000, "total_receipts_cents")
    assert_cents_equals(accepted["assessed_fee_cents"], 2150000, "assessed_fee_cents")
    assert_cents_equals(
        accepted["maintenance_reserve_due_cents"], 200000, "maintenance_reserve_due_cents"
    )
    assert_cents_equals(
        accepted["remittance_received_cents"], 2150000, "remittance_received_cents"
    )

    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["reported_receipts_ytd_cents"], 40000000, "reported_receipts_ytd_cents"
    )
    assert_cents_equals(lease["remitted_fee_ytd_cents"], 2150000, "remitted_fee_ytd_cents")
    assert_cents_equals(
        lease["maintenance_reserve_balance_cents"], 200000, "maintenance_reserve_balance_cents"
    )
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )
