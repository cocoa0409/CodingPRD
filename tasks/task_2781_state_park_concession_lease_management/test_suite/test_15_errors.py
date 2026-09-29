"""Error-catalogue coverage: the shared envelope, one not-found id per entity,
one status-invalid id per entity, and the amount guards that bound money."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
    assert_null,
    assert_status,
)
from test_helpers.test_users import (
    PANELIST_ONE_USER_ID,
    PANELIST_THREE_USER_ID,
    PANELIST_TWO_USER_ID,
)

DECLARED_ERROR_IDS = {member.value for member in ApiErrorId}
MONTHLY_RECEIPTS = {
    "lodging_receipts_cents": 10000000,
    "food_beverage_receipts_cents": 20000000,
    "retail_receipts_cents": 8000000,
    "activity_receipts_cents": 2000000,
}
MONTHS = (
    {"period_start": "2027-04-01", "period_end": "2027-05-01"},
    {"period_start": "2027-05-01", "period_end": "2027-06-01"},
    {"period_start": "2027-06-01", "period_end": "2027-07-01"},
)


def _refusal(response, expected_error_id: str, expected_status: int) -> str:
    """Asserts the shared error envelope and returns the reported error_id."""
    assert response.status_code == expected_status, (
        f"expected HTTP {expected_status} for {expected_error_id}, "
        f"got {response.status_code}"
    )
    body = response.json()
    assert set(body) == {"meta", "response_type", "data"}, f"envelope keys: {sorted(body)}"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta keys: {sorted(body['meta'])}"
    )
    assert set(body["data"]) == {"error_id", "message"}, (
        f"error data keys: {sorted(body['data'])}"
    )
    error = validate_error(response, expected_error_id, expected_status)
    assert error["error_id"] in DECLARED_ERROR_IDS, error["error_id"]
    return error["error_id"]


def _total(response) -> int:
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_the_error_envelope_is_identical_for_a_404_a_403_and_a_422(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format:"
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §5: "Every failure response carries one of the following `error_id` values with the paired HTTP status code, in the error envelope of §2.2."
    PRD §2.9: "All are HTTP 404 and each covers the single-resource read plus every action route hanging off that resource."
    PRD §2.9: "**Role authorization** — the acting role appears in the endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`. Applies to every endpoint."
    PRD §2.9: "`ERR_OPPORTUNITY_NOT_VIABLE` (HTTP 422) — the projected receipts are below the viability floor."
    PRD §3.3: "Before anyone can bid, a `ProgramAdministrator` registers the bidder."
    PRD §3.1: "The projection itself is deliberately simple: `estimated_annual_gross_receipts_cents` is the comparable's receipts multiplied by `market_capture_pct` and divided by one hundred, with the result rounded half up to whole cents."
    PRD §3.1: "It takes no payload and enforces one substantive test: the projected annual gross receipts must be at least one hundred thousand dollars."
    PRD §3.1: "A projection strictly below that viability floor is rejected with `ERR_OPPORTUNITY_NOT_VIABLE`; a projection exactly at the floor passes."

    Design: Corner/errors/error_envelope_shape_is_uniform_across_the_404_403_and_422_families
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    park = X.register_park(api)
    opportunity = X.create_opportunity(api, park["id"])
    analysed = X.record_market_analysis(
        api,
        opportunity["id"],
        comparable_gross_receipts_cents=100000000,
        market_capture_pct=9.00,
    )
    assert_status(analysed, "ANALYSIS_COMPLETE")
    assert_cents_equals(
        analysed["estimated_annual_gross_receipts_cents"],
        9000000,
        "estimated_annual_gross_receipts_cents",
    )

    missing = _refusal(
        api.get_lease(NON_EXISTENT_UUID, X.award_officer_headers()),
        "ERR_LEASE_NOT_FOUND",
        404,
    )

    offerors_before = _total(api.list_offerors(X.admin_headers()))
    forbidden = _refusal(
        api.create_offeror(F.offeror_payload(), X.specialist_headers()),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    assert _total(api.list_offerors(X.admin_headers())) == offerors_before, (
        "a role refusal must not create the offeror"
    )

    unviable = _refusal(
        api.approve_solicitation(opportunity["id"], X.award_officer_headers()),
        "ERR_OPPORTUNITY_NOT_VIABLE",
        422,
    )
    assert len({missing, forbidden, unviable}) == 3, (missing, forbidden, unviable)

    stored = get_success_data(
        api.get_opportunity(opportunity["id"], X.specialist_headers())
    )
    assert_status(stored, "ANALYSIS_COMPLETE")
    assert_cents_equals(
        stored["estimated_annual_gross_receipts_cents"],
        9000000,
        "estimated_annual_gross_receipts_cents",
    )


def test_each_collection_answers_a_missing_reference_with_its_own_not_found_id(api):
    """PRD §2.9: "**Path resource existence** — the `{id}` path segment resolves to a row of the addressed collection, else the collection's own not-found code: `ERR_PARK_NOT_FOUND`, `ERR_OPPORTUNITY_NOT_FOUND`, `ERR_PROSPECTUS_NOT_FOUND`, `ERR_OFFEROR_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_IMPROVEMENT_NOT_FOUND`, `ERR_OPERATING_PLAN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_RECONCILIATION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND` or `ERR_COMPLIANCE_ACTION_NOT_FOUND`."
    PRD §2.9: "All are HTTP 404 and each covers the single-resource read plus every action route hanging off that resource."
    PRD §2.9: "**Body foreign-key existence** — every reference carried in the request body resolves, and references are resolved left to right in the order the fields are listed for that endpoint."
    PRD §2.9: "A `park_id` that does not resolve on opportunity creation yields `ERR_PARK_NOT_FOUND`; an `opportunity_id` on prospectus creation yields `ERR_OPPORTUNITY_NOT_FOUND`; on proposal creation `prospectus_id` is resolved first and yields `ERR_PROSPECTUS_NOT_FOUND`, and only then is `offeror_id` resolved, yielding `ERR_OFFEROR_NOT_FOUND`; a `lease_id` on capital-improvement, operating-plan, gross-receipts-report, fee-reconciliation, audit-engagement or compliance-action creation yields `ERR_LEASE_NOT_FOUND`; a supplied `reconciliation_id` on compliance-action creation must resolve to a reconciliation whose `lease_id` equals the body's `lease_id`, else `ERR_RECONCILIATION_NOT_FOUND`; a supplied `successor_lease_id` at close-out must resolve to a lease other than the one in the path, else `ERR_LEASE_NOT_FOUND`."
    PRD §2.9: "**Resource ownership** — when the acting role is `Concessionaire`, `X-User-ID` must equal the owning offeror's `id`, else `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/errors/every_missing_reference_returns_its_own_not_found_error_id
    """
    ctx = X.setup_issued_prospectus(api)
    officer = X.exec_officer_headers()
    reported = []

    for response, expected in (
        (api.get_opportunity(NON_EXISTENT_UUID, X.specialist_headers()),
         "ERR_OPPORTUNITY_NOT_FOUND"),
        (api.get_prospectus(NON_EXISTENT_UUID, X.specialist_headers()),
         "ERR_PROSPECTUS_NOT_FOUND"),
        (api.get_offeror(NON_EXISTENT_UUID, X.admin_headers()), "ERR_OFFEROR_NOT_FOUND"),
        (api.get_proposal(NON_EXISTENT_UUID, X.specialist_headers()),
         "ERR_PROPOSAL_NOT_FOUND"),
        (api.get_proposal_evaluation(NON_EXISTENT_UUID, X.panelist_headers()),
         "ERR_EVALUATION_NOT_FOUND"),
        (api.get_bond(NON_EXISTENT_UUID, officer), "ERR_BOND_NOT_FOUND"),
        (api.get_improvement(NON_EXISTENT_UUID, officer), "ERR_IMPROVEMENT_NOT_FOUND"),
        (api.get_operating_plan(NON_EXISTENT_UUID, officer),
         "ERR_OPERATING_PLAN_NOT_FOUND"),
        (api.get_report(NON_EXISTENT_UUID, officer), "ERR_REPORT_NOT_FOUND"),
        (api.get_reconciliation(NON_EXISTENT_UUID, officer),
         "ERR_RECONCILIATION_NOT_FOUND"),
        (api.get_audit(NON_EXISTENT_UUID, X.auditor_headers()), "ERR_AUDIT_NOT_FOUND"),
        (api.get_compliance_action(NON_EXISTENT_UUID, officer),
         "ERR_COMPLIANCE_ACTION_NOT_FOUND"),
    ):
        reported.append(_refusal(response, expected, 404))

    assert len(set(reported)) == 12, f"the twelve not-found ids must differ: {reported}"

    _refusal(
        api.create_proposal(
            F.proposal_payload(NON_EXISTENT_UUID, ctx["offeror_id"]),
            X.concessionaire_headers(ctx["offeror_id"]),
        ),
        "ERR_PROSPECTUS_NOT_FOUND",
        404,
    )
    _refusal(
        api.create_proposal(
            F.proposal_payload(ctx["prospectus_id"], NON_EXISTENT_UUID),
            X.concessionaire_headers(NON_EXISTENT_UUID),
        ),
        "ERR_OFFEROR_NOT_FOUND",
        404,
    )
    assert _total(
        api.list_proposals(X.specialist_headers(), {"prospectus_id": ctx["prospectus_id"]})
    ) == 0, "a rejected submission must not leave a proposal behind"


def test_replaying_a_completed_transition_names_the_blocking_entity(api):
    """PRD §2.9: "**The path resource's own status** — the addressed row's own state admits the requested transition, else that entity's status code: `ERR_OPPORTUNITY_STATUS_INVALID`, `ERR_PROSPECTUS_STATUS_INVALID`, `ERR_OFFEROR_STATUS_INVALID`, `ERR_PROPOSAL_STATUS_INVALID`, `ERR_LEASE_STATUS_INVALID`, `ERR_BOND_STATUS_INVALID`, `ERR_IMPROVEMENT_STATUS_INVALID`, `ERR_OPERATING_PLAN_STATUS_INVALID`, `ERR_REPORT_STATUS_INVALID`, `ERR_RECONCILIATION_STATUS_INVALID`, `ERR_AUDIT_STATUS_INVALID` or `ERR_COMPLIANCE_ACTION_STATUS_INVALID`, all HTTP 409."
    PRD §3.1: "Clearing the opportunity for solicitation is a `ContractingOfficer` decision and moves `ANALYSIS_COMPLETE` to `APPROVED_FOR_SOLICITATION`."
    PRD §3.4: "Finally the opportunity moves `SOLICITED → AWARDED` and the prospectus itself moves `CLOSED → AWARDED`, which is terminal for both."
    PRD §3.2: "Issuing a `DRAFT` prospectus takes no payload and enforces two conditions in ladder order: the opportunity behind it must have reached `APPROVED_FOR_SOLICITATION`, else `ERR_OPPORTUNITY_NOT_APPROVED`, and the logical clock must be strictly before `submission_deadline`, else `ERR_SUBMISSION_WINDOW_CLOSED` — the agency does not publish a solicitation nobody can answer."
    PRD §3.5: "The concessionaire posts the bond, moving it `PENDING → ACTIVE`."
    PRD §3.5: "Execution is a `ContractingOfficer` act taking a lease from `PENDING_EXECUTION` to `ACTIVE`, and it carries the terms of the physical relationship: `insurance_expires_on`, the expiry date of the certificate of insurance on file; `carrier_name`, the insurer of record; and `agency_maintenance_scope`, the portion of physical maintenance the agency retains, which is `NONE`, `STRUCTURAL_ONLY` or `STRUCTURAL_AND_UTILITIES` and defaults to `STRUCTURAL_ONLY`."
    PRD §3.6: "Approval belongs to a `ContractingOfficer` and moves the plan `SUBMITTED → APPROVED`."
    PRD §3.7: "Approval is where the money and the park calendar are actually committed, and it is a `ContractingOfficer` act moving the improvement `PROPOSED → APPROVED`."
    PRD §3.8: "Acceptance is a `ContractingOfficer` act moving a report `SUBMITTED → ACCEPTED`, and it logs the cash: `remittance_received_cents` must equal the report's `assessed_fee_cents` to the cent, else `ERR_REMITTANCE_MISMATCH`."
    PRD §3.8: "On success the remittance is persisted and three lease ledger fields move at once — `reported_receipts_ytd_cents` rises by the report's `total_receipts_cents`, `remitted_fee_ytd_cents` rises by the logged remittance, and `maintenance_reserve_balance_cents` rises by `maintenance_reserve_due_cents` — with the report and the lease each advancing their `version` by one."

    Design: Corner/errors/repeating_a_completed_transition_returns_that_entity_s_own_status_invalid_error
    """
    ctx = X.setup_lease_with_season(api)
    improvement = X.propose_improvement(api, ctx["lease_id"], ctx["offeror_id"])
    X.approve_improvement(api, improvement["id"], 6000000)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    report = X.file_report(
        api, ctx["lease_id"], ctx["offeror_id"], **dict(MONTHS[0], **MONTHLY_RECEIPTS)
    )
    X.accept_report(api, report["id"], 2150000)
    officer = X.exec_officer_headers()

    reported = [
        _refusal(
            api.approve_solicitation(ctx["opportunity_id"], X.award_officer_headers()),
            "ERR_OPPORTUNITY_STATUS_INVALID",
            409,
        ),
        _refusal(
            api.issue_prospectus(ctx["prospectus_id"], X.specialist_headers()),
            "ERR_PROSPECTUS_STATUS_INVALID",
            409,
        ),
        _refusal(
            api.post_bond(
                ctx["bond_id"],
                F.post_bond_payload(3000000),
                X.concessionaire_headers(ctx["offeror_id"]),
            ),
            "ERR_BOND_STATUS_INVALID",
            409,
        ),
        _refusal(
            api.approve_operating_plan(ctx["plan_id"], officer),
            "ERR_OPERATING_PLAN_STATUS_INVALID",
            409,
        ),
        _refusal(
            api.approve_improvement(
                improvement["id"], F.approve_improvement_payload(6000000), officer
            ),
            "ERR_IMPROVEMENT_STATUS_INVALID",
            409,
        ),
        _refusal(
            api.accept_report(report["id"], F.accept_report_payload(2150000), officer),
            "ERR_REPORT_STATUS_INVALID",
            409,
        ),
        _refusal(
            api.execute_lease(
                ctx["lease_id"],
                F.execute_lease_payload(insurance_expires_on="2029-06-30"),
                officer,
            ),
            "ERR_LEASE_STATUS_INVALID",
            409,
        ),
    ]
    assert len(set(reported)) == 7, f"each entity needs its own status id: {reported}"

    assert_status(
        get_success_data(api.get_opportunity(ctx["opportunity_id"], X.specialist_headers())),
        "AWARDED",
    )
    assert_status(
        get_success_data(api.get_prospectus(ctx["prospectus_id"], X.specialist_headers())),
        "AWARDED",
    )
    bond = get_success_data(api.get_bond(ctx["bond_id"], officer))
    assert_status(bond, "ACTIVE")
    assert_cents_equals(bond["penal_sum_cents"], 3000000, "penal_sum_cents")
    assert_cents_equals(bond["available_balance_cents"], 3000000, "available_balance_cents")
    assert_status(get_success_data(api.get_operating_plan(ctx["plan_id"], officer)), "APPROVED")
    stored_improvement = get_success_data(api.get_improvement(improvement["id"], officer))
    assert_status(stored_improvement, "APPROVED")
    assert_cents_equals(
        stored_improvement["approved_cost_cents"], 6000000, "approved_cost_cents"
    )
    assert_status(get_success_data(api.get_report(report["id"], officer)), "ACCEPTED")

    lease = X.read_lease(api, ctx["lease_id"])
    assert_lease_state(lease, contract_status="ACTIVE")
    assert_fields(lease, {"insurance_expires_on": "2028-06-30"})
    assert_cents_equals(
        lease["reported_receipts_ytd_cents"], 40000000, "reported_receipts_ytd_cents"
    )
    assert_cents_equals(lease["remitted_fee_ytd_cents"], 2150000, "remitted_fee_ytd_cents")
    assert_cents_equals(
        lease["capital_investment_completed_cents"], 0, "capital_investment_completed_cents"
    )


def test_duplicate_and_capacity_guards_are_distinct_from_one_another(api):
    """PRD §2.9: "`ERR_DUPLICATE_PROPOSAL` — an offeror may hold only one live proposal per prospectus."
    PRD §2.9: "`ERR_DUPLICATE_PANELIST_EVALUATION` — a panelist may file only one score sheet per proposal."
    PRD §2.9: "**Evaluation not yet started** — `ERR_EVALUATION_ALREADY_STARTED` when a revision is requested on a proposal that already carries at least one score sheet."
    PRD §2.9: "**Panel capacity** — `ERR_PANEL_ALREADY_COMPLETE` when a score sheet is filed on a proposal whose panel is already complete."
    PRD §3.4: "Two guards apply after the proposal's own status is checked: the panel must not already be complete — a proposal that already carries two sheets rejects a third with `ERR_PANEL_ALREADY_COMPLETE` — and the acting panelist must not already have filed on this proposal, else `ERR_DUPLICATE_PANELIST_EVALUATION`."
    PRD §3.4: "Filing a sheet raises the proposal's `evaluation_count` by one and advances the proposal's `version` by one."
    PRD §3.4: "The panel is complete at two sheets, and the second sheet is the one that scores the proposal: `composite_score` is computed and the proposal moves `UNDER_REVIEW → SCORED` in the same request."
    PRD §3.3: "Three conditions guard that move, in order: the proposal's `evaluation_count` must still be 0, because once any panelist has filed a score sheet the bid is frozen and the attempt fails with `ERR_EVALUATION_ALREADY_STARTED`; the prospectus must still be `ISSUED`, since a revision is pointless once the window has closed; and `revision_round` must be strictly below two, else `ERR_REVISION_LIMIT_REACHED` — an offeror gets two bites and no more."
    PRD §2.5: "Nothing in the system ever rewrites a filed score sheet."

    Design: Corner/errors/duplicate_and_panel_capacity_guards_are_distinct_from_the_status_guards
    """
    ctx = X.setup_issued_prospectus(api)
    owner = X.concessionaire_headers(ctx["offeror_id"])
    proposal = X.submit_proposal(api, ctx["prospectus_id"], ctx["offeror_id"])
    X.begin_review(api, proposal["id"])
    first_sheet = X.file_evaluation(
        api, proposal["id"], PANELIST_ONE_USER_ID, **X.PANEL_SCORES_ONE
    )

    _refusal(
        api.create_proposal(
            F.proposal_payload(
                ctx["prospectus_id"],
                ctx["offeror_id"],
                offered_franchise_fee_pct=5.50,
                proposed_capital_investment_cents=31000000,
                proposed_annual_guarantee_cents=6500000,
            ),
            owner,
        ),
        "ERR_DUPLICATE_PROPOSAL",
        409,
    )
    _refusal(
        api.file_evaluation(
            proposal["id"],
            F.evaluation_payload(
                score_experience=90,
                score_operating_plan=90,
                score_capital_investment=90,
                score_financial_capacity=90,
                score_fee_offer=90,
            ),
            X.panelist_headers(PANELIST_ONE_USER_ID),
        ),
        "ERR_DUPLICATE_PANELIST_EVALUATION",
        409,
    )
    _refusal(
        api.request_revision(proposal["id"], X.specialist_headers()),
        "ERR_EVALUATION_ALREADY_STARTED",
        409,
    )

    X.file_evaluation(api, proposal["id"], PANELIST_TWO_USER_ID, **X.PANEL_SCORES_TWO)
    scored = get_success_data(api.get_proposal(proposal["id"], X.specialist_headers()))
    assert_status(scored, "SCORED")
    assert scored["evaluation_count"] == 2, scored["evaluation_count"]

    # PRD §3.4 names ERR_PANEL_ALREADY_COMPLETE for a third sheet, but the second
    # sheet has already moved the proposal UNDER_REVIEW → SCORED, and §2.9 places
    # "the path resource's own status" (band 10) below "panel capacity" (band 21)
    # while §3.4 says the two panel guards "apply after the proposal's own status is
    # checked" — so ERR_PROPOSAL_STATUS_INVALID is equally derivable here. Both are
    # HTTP 409.
    third_sheet = api.file_evaluation(
        proposal["id"],
        F.evaluation_payload(
            score_experience=60,
            score_operating_plan=60,
            score_capital_investment=60,
            score_financial_capacity=60,
            score_fee_offer=60,
        ),
        X.panelist_headers(PANELIST_THREE_USER_ID),
    )
    assert third_sheet.status_code == 409, (
        f"a third score sheet must be refused with HTTP 409, got {third_sheet.status_code}"
    )
    validate_error_is_one_of(
        third_sheet, ["ERR_PANEL_ALREADY_COMPLETE", "ERR_PROPOSAL_STATUS_INVALID"]
    )

    assert _total(
        api.list_proposals(X.specialist_headers(), {"prospectus_id": ctx["prospectus_id"]})
    ) == 1, "the duplicate submission must not have landed"
    rows, meta = validate_paginated(
        api.list_proposal_evaluations(
            X.specialist_headers(), {"proposal_id": proposal["id"]}
        )
    )
    assert meta["total_count"] == 2, meta["total_count"]
    assert {row["panelist_user_id"] for row in rows} == {
        PANELIST_ONE_USER_ID,
        PANELIST_TWO_USER_ID,
    }, rows
    stored_sheet = get_success_data(
        api.get_proposal_evaluation(first_sheet["id"], X.panelist_headers())
    )
    assert_fields(stored_sheet, X.PANEL_SCORES_ONE)


def test_bond_posting_separates_the_required_floor_from_the_attested_capacity(api):
    """PRD §2.9: "`ERR_BOND_INSUFFICIENT` (HTTP 422) — the posted penal sum is below the required amount."
    PRD §2.9: "`ERR_BOND_EXCEEDS_CAPACITY` (HTTP 422) — the posted penal sum exceeds the offeror's attested capacity."
    PRD §3.5: "The bond row is created by the award itself, in status `PENDING`, with `lease_id` pointing at the new lease, `surety_name` and `penal_sum_cents` still null, `available_balance_cents` at 0 and `drawn_total_cents` at 0."
    PRD §3.5: "Beyond ownership, two bounds apply in order: the penal sum must be at least `required_amount_cents`, with equality passing, else `ERR_BOND_INSUFFICIENT`; and it must not exceed the lease-holding offeror's attested `bond_capacity_cents`, else `ERR_BOND_EXCEEDS_CAPACITY`."
    PRD §3.5: "On success the penal sum and surety are persisted, `available_balance_cents` is set equal to `penal_sum_cents`, `drawn_total_cents` is set to 0, and the bond's `version` advances by one."

    Design: Corner/errors/bond_posting_errors_distinguish_the_required_floor_from_the_attested_capacity
    """
    ctx = X.setup_awarded_lease(api)
    owner = X.concessionaire_headers(ctx["offeror_id"])

    _refusal(
        api.post_bond(ctx["bond_id"], F.post_bond_payload(2999999), owner),
        "ERR_BOND_INSUFFICIENT",
        422,
    )
    _refusal(
        api.post_bond(ctx["bond_id"], F.post_bond_payload(50000001), owner),
        "ERR_BOND_EXCEEDS_CAPACITY",
        422,
    )

    untouched = get_success_data(api.get_bond(ctx["bond_id"], owner))
    assert_status(untouched, "PENDING")
    assert_null(untouched, "penal_sum_cents", "surety_name")
    assert_cents_equals(
        untouched["available_balance_cents"], 0, "available_balance_cents"
    )
    assert_cents_equals(untouched["drawn_total_cents"], 0, "drawn_total_cents")
    assert_cents_equals(untouched["required_amount_cents"], 3000000, "required_amount_cents")
    assert_lease_state(X.read_lease(api, ctx["lease_id"]), contract_status="PENDING_EXECUTION")

    response = api.post_bond(ctx["bond_id"], F.post_bond_payload(3000000), owner)
    validate_success(response, 200)
    posted = get_success_data(response)
    assert_status(posted, "ACTIVE")
    assert_cents_equals(posted["penal_sum_cents"], 3000000, "penal_sum_cents")
    assert_cents_equals(posted["available_balance_cents"], 3000000, "available_balance_cents")
    assert_cents_equals(posted["drawn_total_cents"], 0, "drawn_total_cents")
    assert_lease_state(X.read_lease(api, ctx["lease_id"]), contract_status="PENDING_EXECUTION")


def test_draw_and_reinstatement_amounts_are_bounded_by_the_live_bond(api):
    """PRD §2.9: "`ERR_DRAW_EXCEEDS_BOND` (HTTP 422) — the ordered draw exceeds the bond's available balance."
    PRD §2.9: "`ERR_REINSTATEMENT_EXCEEDS_DRAWN` (HTTP 422) — the reinstatement is not strictly positive, or exceeds what was drawn."
    PRD §3.9: "Three conditions are checked in order: the lease's bond must be in `ACTIVE` or `PARTIALLY_DRAWN`, else `ERR_BOND_NOT_ACTIVE`; the logical clock must be strictly after the action's `cure_deadline`, else `ERR_CURE_PERIOD_OPEN` — a draw ordered at the very instant the deadline falls is premature; and the requested `draw_amount_cents` must not exceed the bond's current `available_balance_cents`, else `ERR_DRAW_EXCEEDS_BOND`, which is tested against the live balance so that a second draw sees what the first one left."
    PRD §3.9: "If the remaining `available_balance_cents` is at or above that floor the bond lands in `PARTIALLY_DRAWN`, and the agency's security is still adequate; if it falls strictly below the floor the bond lands in `INSUFFICIENT`."
    PRD §3.9: "A reinstatement names a `reinstatement_amount_cents` that must be strictly positive and no greater than the bond's current `drawn_total_cents`, else `ERR_REINSTATEMENT_EXCEEDS_DRAWN`."
    PRD §3.9: "`available_balance_cents` rises and `drawn_total_cents` falls by that amount, `penal_sum_cents` again untouched."
    PRD §3.9: "A **full** reinstatement — one whose amount equals `drawn_total_cents`, bringing it to zero — returns the bond to `ACTIVE` from either `PARTIALLY_DRAWN` or `INSUFFICIENT`; a **partial** one leaves the bond in `PARTIALLY_DRAWN` as a self-loop."
    PRD §3.9: "Critically, restoring the bond does not restore the lease: a lease already in `DEFAULT` and `TERMINATED_DEFAULT` stays there, both dimensions unchanged, no matter how completely the bond is made whole."

    Design: Corner/errors/draw_and_reinstatement_amounts_are_bounded_by_the_live_bond_and_rejected_otherwise
    """
    ctx = X.setup_active_lease(api)
    owner = X.concessionaire_headers(ctx["offeror_id"])
    action = X.issue_compliance_action(
        api,
        ctx["lease_id"],
        action_type="OPERATING_STANDARD",
        deficiency_note="Concession hours not maintained through the posted season.",
        cure_deadline="2027-03-04T00:00:00Z",
    )
    X.set_clock(api, "2027-03-05T00:00:00Z")

    _refusal(
        api.order_bond_draw(
            action["id"], F.order_bond_draw_payload(3000001), X.exec_officer_headers()
        ),
        "ERR_DRAW_EXCEEDS_BOND",
        422,
    )
    still_whole = get_success_data(api.get_bond(ctx["bond_id"], owner))
    assert_status(still_whole, "ACTIVE")
    assert_cents_equals(
        still_whole["available_balance_cents"], 3000000, "available_balance_cents"
    )
    assert_cents_equals(still_whole["drawn_total_cents"], 0, "drawn_total_cents")
    assert_null(get_success_data(api.get_compliance_action(action["id"], owner)), "draw_amount_cents")

    X.order_bond_draw(api, action["id"], 1000000, X.exec_officer_headers())
    drawn = get_success_data(api.get_bond(ctx["bond_id"], owner))
    assert_status(drawn, "PARTIALLY_DRAWN")
    assert_cents_equals(drawn["available_balance_cents"], 2000000, "available_balance_cents")
    assert_cents_equals(drawn["drawn_total_cents"], 1000000, "drawn_total_cents")
    assert_cents_equals(drawn["penal_sum_cents"], 3000000, "penal_sum_cents")

    for amount in (1000001, 0):
        _refusal(
            api.reinstate_bond(ctx["bond_id"], F.reinstate_bond_payload(amount), owner),
            "ERR_REINSTATEMENT_EXCEEDS_DRAWN",
            422,
        )
    unmoved = get_success_data(api.get_bond(ctx["bond_id"], owner))
    assert_status(unmoved, "PARTIALLY_DRAWN")
    assert_cents_equals(unmoved["available_balance_cents"], 2000000, "available_balance_cents")
    assert_cents_equals(unmoved["drawn_total_cents"], 1000000, "drawn_total_cents")

    response = api.reinstate_bond(
        ctx["bond_id"], F.reinstate_bond_payload(1000000), owner
    )
    validate_success(response, 200)
    restored = get_success_data(response)
    assert_status(restored, "ACTIVE")
    assert_cents_equals(
        restored["available_balance_cents"], 3000000, "available_balance_cents"
    )
    assert_cents_equals(restored["drawn_total_cents"], 0, "drawn_total_cents")
    assert_cents_equals(restored["penal_sum_cents"], 3000000, "penal_sum_cents")
    assert_lease_state(
        X.read_lease(api, ctx["lease_id"]),
        contract_status="ACTIVE",
        compliance_status="DEFICIENT",
    )


def test_window_standing_and_responsiveness_guards_each_return_their_own_error(api):
    """PRD §2.9: "**Offeror standing** — `ERR_OFFEROR_DEBARRED` when the offeror named in a new proposal is not `ELIGIBLE`."
    PRD §2.9: "**Responsiveness** — `ERR_NO_RESPONSIVE_PROPOSAL` (HTTP 422) when an award is attempted and the candidate set is empty."
    PRD §2.9: "`ERR_SUBMISSION_WINDOW_CLOSED` — the clock must be strictly before the prospectus `submission_deadline` to issue the prospectus, to submit a proposal, or to resubmit one."
    PRD §2.9: "`ERR_SUBMISSION_WINDOW_OPEN` — the clock must be at or after `submission_deadline` before the solicitation may be closed."
    PRD §2.9: "`ERR_GUARANTEE_BELOW_MINIMUM` (HTTP 422) — on proposal submission and resubmission."
    PRD §3.3: "Resubmission is confined to the owning offeror, requires the prospectus to still be `ISSUED`, requires the logical clock to still be strictly before `submission_deadline`, and re-applies both fiscal floors — a revised fee below `minimum_franchise_fee_pct` earns `ERR_FEE_BELOW_MINIMUM` and a revised guarantee below `minimum_annual_guarantee_cents` earns `ERR_GUARANTEE_BELOW_MINIMUM`."
    PRD §3.3: "An `ELIGIBLE` offeror moves to `DEBARRED`, which is terminal; a second attempt on an already-debarred offeror is refused with `ERR_OFFEROR_STATUS_INVALID`."
    PRD §3.2: "Closing the window is the mirror image: an `ISSUED` prospectus moves to `CLOSED` only once the logical clock has reached or passed `submission_deadline`, and an attempt made while proposals could still legitimately arrive is refused with `ERR_SUBMISSION_WINDOW_OPEN`."
    PRD §3.4: "The candidate set must be non-empty, else `ERR_NO_RESPONSIVE_PROPOSAL` and nothing at all is changed."

    Design: Corner/errors/submission_window_and_responsiveness_guards_each_return_their_own_error
    """
    ctx = X.setup_issued_prospectus(api)
    owner = X.concessionaire_headers(ctx["offeror_id"])
    rival = X.register_offeror(api, legal_name="Ridgeline Outfitters Inc")
    debarred = get_success_data(api.debar_offeror(rival["id"], X.admin_headers()))
    assert_status(debarred, "DEBARRED")

    _refusal(
        api.create_proposal(
            F.proposal_payload(
                ctx["prospectus_id"],
                ctx["offeror_id"],
                proposed_annual_guarantee_cents=5999999,
            ),
            owner,
        ),
        "ERR_GUARANTEE_BELOW_MINIMUM",
        422,
    )
    _refusal(
        api.create_proposal(
            F.proposal_payload(ctx["prospectus_id"], rival["id"]),
            X.concessionaire_headers(rival["id"]),
        ),
        "ERR_OFFEROR_DEBARRED",
        409,
    )
    _refusal(
        api.close_prospectus(ctx["prospectus_id"], X.specialist_headers()),
        "ERR_SUBMISSION_WINDOW_OPEN",
        409,
    )

    X.set_clock(api, "2027-02-01T00:00:00Z")
    _refusal(
        api.create_proposal(
            F.proposal_payload(ctx["prospectus_id"], ctx["offeror_id"]), owner
        ),
        "ERR_SUBMISSION_WINDOW_CLOSED",
        409,
    )

    closed = X.close_prospectus(api, ctx["prospectus_id"])
    assert_status(closed, "CLOSED")
    _refusal(
        api.award_prospectus(
            ctx["prospectus_id"], F.award_payload("2027-03-01"), X.award_officer_headers()
        ),
        "ERR_NO_RESPONSIVE_PROPOSAL",
        422,
    )

    assert _total(
        api.list_proposals(X.specialist_headers(), {"prospectus_id": ctx["prospectus_id"]})
    ) == 0, "no refused submission may have created a proposal"
    assert _total(
        api.list_leases(X.award_officer_headers(), {"prospectus_id": ctx["prospectus_id"]})
    ) == 0, "a refused award mints no lease"
    assert_status(
        get_success_data(api.get_prospectus(ctx["prospectus_id"], X.specialist_headers())),
        "CLOSED",
    )
    assert_status(
        get_success_data(api.get_opportunity(ctx["opportunity_id"], X.specialist_headers())),
        "SOLICITED",
    )


def _quarter_reported_lease(api):
    """An ACTIVE lease whose first quarter is fully reported and paid: three
    accepted months of 40,000,000 each at 2,150,000 of franchise fee."""
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    for period in MONTHS:
        report = X.file_report(
            api, ctx["lease_id"], ctx["offeror_id"], **dict(period, **MONTHLY_RECEIPTS)
        )
        X.accept_report(api, report["id"], 2150000)
    return ctx


def test_settlement_amount_and_settlement_status_guards_are_distinct(api):
    """PRD §2.9: "`ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422) — the settlement payment does not equal the amount due."
    PRD §3.8: "The concessionaire clears the invoice by settling it, moving `PENDING_PAYMENT → SETTLED`, and the payment must be exact: `payment_amount_cents` must equal `additional_fee_due_cents`, else `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD §3.8: "Settlement recomputes the lease's outstanding balance, and if the reconciliation carries an `audit_engagement_id` whose audit is in `FINAL`, that audit is closed out in the same request, moving `FINAL → CLOSED`."
    PRD §3.8: "`SETTLED` and `VOIDED` are the reconciliation's terminal states."
    PRD §3.8: "The lease's `outstanding_fee_balance_cents` — the sum of `additional_fee_due_cents` over the lease's reconciliations still in `PENDING_PAYMENT` — is recomputed, and the lease's `version` advances by one."
    PRD §2.9: "**The path resource's own status** — the addressed row's own state admits the requested transition, else that entity's status code: `ERR_OPPORTUNITY_STATUS_INVALID`, `ERR_PROSPECTUS_STATUS_INVALID`, `ERR_OFFEROR_STATUS_INVALID`, `ERR_PROPOSAL_STATUS_INVALID`, `ERR_LEASE_STATUS_INVALID`, `ERR_BOND_STATUS_INVALID`, `ERR_IMPROVEMENT_STATUS_INVALID`, `ERR_OPERATING_PLAN_STATUS_INVALID`, `ERR_REPORT_STATUS_INVALID`, `ERR_RECONCILIATION_STATUS_INVALID`, `ERR_AUDIT_STATUS_INVALID` or `ERR_COMPLIANCE_ACTION_STATUS_INVALID`, all HTTP 409."

    Design: Corner/errors/settlement_amount_and_settlement_status_guards_return_distinct_errors
    """
    ctx = _quarter_reported_lease(api)
    owner = X.concessionaire_headers(ctx["offeror_id"])
    X.set_clock(api, "2028-03-05T00:00:00Z")
    recon = X.create_reconciliation(
        api, ctx["lease_id"], lease_year_start="2027-03-01", lease_year_end="2028-02-29"
    )
    assert_cents_equals(
        recon["additional_fee_due_cents"], 1300000, "additional_fee_due_cents"
    )

    _refusal(
        api.settle_reconciliation(recon["id"], F.settle_payload(1299999), owner),
        "ERR_PAYMENT_AMOUNT_MISMATCH",
        422,
    )
    unpaid = get_success_data(api.get_reconciliation(recon["id"], owner))
    assert_status(unpaid, "PENDING_PAYMENT")
    assert_null(unpaid, "payment_amount_cents")
    assert_cents_equals(
        X.read_lease(api, ctx["lease_id"])["outstanding_fee_balance_cents"],
        1300000,
        "outstanding_fee_balance_cents",
    )

    response = api.settle_reconciliation(recon["id"], F.settle_payload(1300000), owner)
    validate_success(response, 200)
    settled = get_success_data(response)
    assert_status(settled, "SETTLED")
    assert_cents_equals(settled["payment_amount_cents"], 1300000, "payment_amount_cents")
    assert_cents_equals(
        X.read_lease(api, ctx["lease_id"])["outstanding_fee_balance_cents"],
        0,
        "outstanding_fee_balance_cents",
    )

    _refusal(
        api.settle_reconciliation(recon["id"], F.settle_payload(1300000), owner),
        "ERR_RECONCILIATION_STATUS_INVALID",
        409,
    )
    assert_status(get_success_data(api.get_reconciliation(recon["id"], owner)), "SETTLED")
    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )
    assert_cents_equals(lease["remitted_fee_ytd_cents"], 6450000, "remitted_fee_ytd_cents")
    assert _total(
        api.list_reconciliations(X.award_officer_headers(), {"lease_id": ctx["lease_id"]})
    ) == 1, "a refused settlement mints no second invoice"


def test_report_filing_and_acceptance_guards_are_distinct(api):
    """PRD §2.9: "**Season coverage** — `ERR_NO_APPROVED_OPERATING_PLAN` when a reporting period is not fully covered by an `APPROVED` season on the same lease."
    PRD §2.9: "`ERR_REMITTANCE_MISMATCH` (HTTP 422) — the logged remittance does not equal the period's assessed fee."
    PRD §3.8: "Exactly one `APPROVED` operating plan on the same lease must have a closed season window `season_start` through `season_end` that covers every calendar day of the half-open reporting period; that plan's identifier is written onto the report as `operating_plan_id`, and if no approved season covers the period the filing is refused with `ERR_NO_APPROVED_OPERATING_PLAN`."
    PRD §3.8: "Acceptance is a `ContractingOfficer` act moving a report `SUBMITTED → ACCEPTED`, and it logs the cash: `remittance_received_cents` must equal the report's `assessed_fee_cents` to the cent, else `ERR_REMITTANCE_MISMATCH`."
    PRD §3.8: "There is no tolerance and no partial acceptance."
    PRD §3.8: "On success the remittance is persisted and three lease ledger fields move at once — `reported_receipts_ytd_cents` rises by the report's `total_receipts_cents`, `remitted_fee_ytd_cents` rises by the logged remittance, and `maintenance_reserve_balance_cents` rises by `maintenance_reserve_due_cents` — with the report and the lease each advancing their `version` by one."
    PRD §3.8: "`total_receipts_cents` is simply the four category amounts added together."
    PRD §3.8: "`maintenance_reserve_due_cents` is one half of one percent of `total_receipts_cents`, rounded half up to whole cents."

    Design: Corner/errors/report_filing_and_acceptance_guards_return_distinct_errors
    """
    ctx = X.setup_lease_with_season(api)
    owner = X.concessionaire_headers(ctx["offeror_id"])
    officer = X.exec_officer_headers()
    X.set_clock(api, "2027-07-02T00:00:00Z")

    _refusal(
        api.create_report(
            F.report_payload(
                ctx["lease_id"],
                period_start="2028-01-01",
                period_end="2028-02-01",
                **MONTHLY_RECEIPTS,
            ),
            owner,
        ),
        "ERR_NO_APPROVED_OPERATING_PLAN",
        409,
    )
    assert _total(
        api.list_reports(officer, {"lease_id": ctx["lease_id"]})
    ) == 0, "an uncovered period files nothing"

    report = X.file_report(
        api, ctx["lease_id"], ctx["offeror_id"], **dict(MONTHS[0], **MONTHLY_RECEIPTS)
    )
    assert_status(report, "SUBMITTED")
    assert_fields(report, {"operating_plan_id": ctx["plan_id"]})
    assert_cents_equals(report["total_receipts_cents"], 40000000, "total_receipts_cents")
    assert_cents_equals(report["assessed_fee_cents"], 2150000, "assessed_fee_cents")
    assert_cents_equals(
        report["maintenance_reserve_due_cents"], 200000, "maintenance_reserve_due_cents"
    )

    _refusal(
        api.accept_report(report["id"], F.accept_report_payload(2140000), officer),
        "ERR_REMITTANCE_MISMATCH",
        422,
    )
    unaccepted = get_success_data(api.get_report(report["id"], officer))
    assert_status(unaccepted, "SUBMITTED")
    assert_null(unaccepted, "remittance_received_cents")
    idle = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        idle["reported_receipts_ytd_cents"], 0, "reported_receipts_ytd_cents"
    )
    assert_cents_equals(idle["remitted_fee_ytd_cents"], 0, "remitted_fee_ytd_cents")
    assert_cents_equals(
        idle["maintenance_reserve_balance_cents"], 0, "maintenance_reserve_balance_cents"
    )

    accepted = X.accept_report(api, report["id"], 2150000)
    assert_status(accepted, "ACCEPTED")
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
