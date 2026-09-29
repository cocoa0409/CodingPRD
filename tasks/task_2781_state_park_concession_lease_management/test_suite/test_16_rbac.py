"""Identity coverage: the authentication and authorization rungs, the
concessionaire ownership hop, and the two segregation-of-duties comparisons."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
    assert_null,
    assert_status,
)
from test_helpers.test_users import (
    OFFICER_AWARD_USER_ID,
    PANELIST_ONE_USER_ID,
    headers_missing_user,
    officer_headers,
    panelist_headers,
)
from test_helpers.types import UserRole

DUAL_ROLE_USER_ID = "officer-dual-07"
MONTHLY_RECEIPTS = {
    "lodging_receipts_cents": 10000000,
    "food_beverage_receipts_cents": 20000000,
    "retail_receipts_cents": 8000000,
    "activity_receipts_cents": 2000000,
}


def _refusal(response, expected_error_id: str, expected_status: int) -> None:
    assert response.status_code == expected_status, (
        f"expected HTTP {expected_status} for {expected_error_id}, "
        f"got {response.status_code}"
    )
    validate_error(response, expected_error_id, expected_status)


def _total(response) -> int:
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_award_is_closed_to_the_specialist_who_ran_the_solicitation(api):
    """PRD §2.1: "If both headers are well-formed but the named role is not authorized for the endpoint being called — the authorized roles for each endpoint are listed in §4 — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "Authentication is always evaluated before authorization, and both are evaluated before anything else in the request is examined."
    PRD §2.1: "A `ConcessionSpecialist` is program staff — it identifies opportunities, performs the market analysis, drafts and issues the prospectus, closes the solicitation, and shepherds proposals through review; it can neither approve an opportunity for solicitation nor award one."
    PRD §2.9: "**Role authorization** — the acting role appears in the endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`. Applies to every endpoint."
    PRD §3.4: "Awarding is a `ContractingOfficer` act on a `CLOSED` prospectus and is the single busiest operation in the system."

    Design: Corner/rbac/award_attempted_by_a_concession_specialist_returns_forbidden
    """
    ctx = X.setup_scored_proposal(api)
    X.set_clock(api, X.POST_DEADLINE_CLOCK)
    X.close_prospectus(api, ctx["prospectus_id"])

    _refusal(
        api.award_prospectus(
            ctx["prospectus_id"], F.award_payload("2027-03-01"), X.specialist_headers()
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    assert_status(
        get_success_data(api.get_prospectus(ctx["prospectus_id"], X.specialist_headers())),
        "CLOSED",
    )
    assert_status(
        get_success_data(api.get_proposal(ctx["proposal_id"], X.specialist_headers())),
        "SCORED",
    )
    assert _total(
        api.list_leases(X.award_officer_headers(), {"prospectus_id": ctx["prospectus_id"]})
    ) == 0, "a refused award mints neither a lease nor its bond"


def test_score_sheets_are_readable_by_the_agency_but_closed_to_the_offeror(api):
    """PRD §2.1: "Every role may call every `GET` endpoint, with one exception: the two score-sheet read endpoints are closed to `Concessionaire` — panel score sheets are not disclosed to offerors — while `ProgramAdministrator`, `ConcessionSpecialist`, `ContractingOfficer`, `EvaluationPanelist` and `AuditorGeneral` may all read them."
    PRD §2.1: "An `AuditorGeneral` is the independent auditor exercising the lease's audit-rights clause."
    PRD §2.9: "**Role authorization** — the acting role appears in the endpoint's authorized list, else `ERR_FORBIDDEN_ROLE`. Applies to every endpoint."
    PRD §3.4: "The panel is complete at two sheets, and the second sheet is the one that scores the proposal: `composite_score` is computed and the proposal moves `UNDER_REVIEW → SCORED` in the same request."

    Design: Corner/rbac/score_sheets_are_shared_with_the_agency_roles_but_hidden_from_the_offeror
    """
    ctx = X.setup_scored_proposal(api)
    owner = X.concessionaire_headers(ctx["offeror_id"])

    auditor_read = api.list_proposal_evaluations(
        X.auditor_headers(), {"proposal_id": ctx["proposal_id"]}
    )
    validate_success(auditor_read, 200)
    assert _total(auditor_read) == 2, "the panel's two sheets are open to the auditor"

    _refusal(
        api.list_proposal_evaluations(owner, {"proposal_id": ctx["proposal_id"]}),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    own_bids = api.list_proposals(owner, {"prospectus_id": ctx["prospectus_id"]})
    validate_success(own_bids, 200)
    assert _total(own_bids) == 1, "the proposal collection itself stays open to the offeror"


def test_a_report_filed_against_another_offerors_lease_is_refused_on_ownership(api):
    """PRD §2.1: "For `Concessionaire`, `X-User-ID` is the `id` of the acting `Offeror`."
    PRD §2.1: "Ownership checks compare that value to the offeror that owns the target resource: for proposal routes, the proposal's `offeror_id`; for a performance bond, capital improvement, operating plan, gross receipts report, fee reconciliation or audit engagement, the `offeror_id` of the lease reached through the resource's `lease_id`."
    PRD §2.1: "Ownership is checked after role authorization but before the request body is validated, so a `Concessionaire` reaching for another offeror's lease is turned away regardless of what it sent."
    PRD §2.9: "**Resource ownership** — when the acting role is `Concessionaire`, `X-User-ID` must equal the owning offeror's `id`, else `ERR_NOT_RESOURCE_OWNER`. This band guards proposal creation, resubmission and withdrawal, bond posting and reinstatement, capital-improvement creation, resubmission and place-in-service, operating-plan creation and resubmission, gross-receipts-report creation and amendment, reconciliation settlement, and the contesting of audit findings."

    Design: Corner/rbac/report_filed_against_another_offerors_lease_returns_forbidden
    """
    ctx = X.setup_awarded_lease(api)
    rival = X.register_offeror(api, legal_name="Ridgeline Outfitters Inc")

    _refusal(
        api.create_report(
            F.report_payload(
                ctx["lease_id"],
                period_start="2027-04-01",
                period_end="2027-05-01",
                **MONTHLY_RECEIPTS,
            ),
            X.concessionaire_headers(rival["id"]),
        ),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )

    assert _total(
        api.list_reports(X.award_officer_headers(), {"lease_id": ctx["lease_id"]})
    ) == 0, "a stranger's filing must not land on the lease"
    lease = X.read_lease(api, ctx["lease_id"])
    assert_fields(lease, {"offeror_id": ctx["offeror_id"]})
    assert_lease_state(lease, contract_status="PENDING_EXECUTION")


def test_report_creation_without_a_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role that user is acting under."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "**Authentication** — both headers present and `X-User-Role` a declared role, else `ERR_UNAUTHENTICATED`. Applies to every endpoint."

    Design: Corner/rbac/report_creation_missing_x_user_id_header_returns_unauthenticated
    """
    ctx = X.setup_awarded_lease(api)

    _refusal(
        api.create_report(
            F.report_payload(
                ctx["lease_id"],
                period_start="2027-04-01",
                period_end="2027-05-01",
                **MONTHLY_RECEIPTS,
            ),
            headers_missing_user(UserRole.CONCESSIONAIRE),
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )

    assert _total(
        api.list_reports(X.award_officer_headers(), {"lease_id": ctx["lease_id"]})
    ) == 0, "an unauthenticated filing must not land on the lease"


def test_execution_by_the_awarding_officer_is_refused(api):
    """PRD §2.9: "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` when the acting officer performed the paired step: at award, when any score sheet on any proposal of that prospectus carries `panelist_user_id` equal to the acting `X-User-ID`; at execution, when `awarded_by_user_id` equals the acting `X-User-ID`."
    PRD §3.5: "The officer who awarded may never be the officer who executes."
    PRD §2.1: "It is nevertheless recorded where a transition says so: the officer who awards a lease is stored as `awarded_by_user_id`, the officer who executes it as `executed_by_user_id`, and the panelist who files a score sheet as `panelist_user_id`."
    PRD §2.5: "Computed and system fields that have not yet been established are returned as null rather than omitted."
    PRD §3.5: "The concessionaire posts the bond, moving it `PENDING → ACTIVE`."

    Design: Corner/rbac/execution_by_the_awarding_officer_is_rejected
    """
    ctx = X.setup_awarded_lease(api)
    bond = X.post_bond(api, ctx["bond_id"], ctx["offeror_id"], 3000000)
    assert_status(bond, "ACTIVE")
    assert_fields(
        X.read_lease(api, ctx["lease_id"]), {"awarded_by_user_id": OFFICER_AWARD_USER_ID}
    )

    _refusal(
        api.execute_lease(
            ctx["lease_id"],
            F.execute_lease_payload(insurance_expires_on="2028-06-30"),
            X.award_officer_headers(),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )

    lease = X.read_lease(api, ctx["lease_id"])
    assert_lease_state(lease, contract_status="PENDING_EXECUTION", compliance_status="COMPLIANT")
    assert_null(lease, "executed_by_user_id", "insurance_expires_on", "carrier_name")
    still_active = get_success_data(api.get_bond(ctx["bond_id"], X.award_officer_headers()))
    assert_status(still_active, "ACTIVE")
    assert_cents_equals(
        still_active["available_balance_cents"], 3000000, "available_balance_cents"
    )


def test_award_by_an_officer_who_filed_a_score_sheet_is_refused(api):
    """PRD §2.9: "**Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` when the acting officer performed the paired step: at award, when any score sheet on any proposal of that prospectus carries `panelist_user_id` equal to the acting `X-User-ID`; at execution, when `awarded_by_user_id` equals the acting `X-User-ID`."
    PRD §3.4: "And the acting officer must be clean of the scoring: if any score sheet on any proposal of this prospectus carries a `panelist_user_id` equal to the acting `X-User-ID`, the award is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.4: "A panelist who has scored one bid can never award that solicitation, even for a different bid."
    PRD §2.1: "For `ProgramAdministrator`, `ConcessionSpecialist`, `ContractingOfficer`, `EvaluationPanelist` and `AuditorGeneral`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any row's `id`."
    PRD §3.2: "Closing has one cascade, and it is narrow."

    Design: Corner/rbac/award_by_an_officer_who_filed_a_score_sheet_is_rejected
    """
    ctx = X.setup_issued_prospectus(api)
    proposal = X.submit_proposal(api, ctx["prospectus_id"], ctx["offeror_id"])
    X.begin_review(api, proposal["id"])
    X.file_evaluation(api, proposal["id"], PANELIST_ONE_USER_ID, **X.PANEL_SCORES_ONE)
    X.file_evaluation(api, proposal["id"], DUAL_ROLE_USER_ID, **X.PANEL_SCORES_TWO)
    scored = get_success_data(api.get_proposal(proposal["id"], X.specialist_headers()))
    assert_status(scored, "SCORED")

    X.set_clock(api, X.POST_DEADLINE_CLOCK)
    X.close_prospectus(api, ctx["prospectus_id"])

    _refusal(
        api.award_prospectus(
            ctx["prospectus_id"],
            F.award_payload("2027-03-01"),
            officer_headers(DUAL_ROLE_USER_ID),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )

    assert_status(
        get_success_data(api.get_prospectus(ctx["prospectus_id"], panelist_headers())),
        "CLOSED",
    )
    assert_status(
        get_success_data(api.get_opportunity(ctx["opportunity_id"], X.specialist_headers())),
        "SOLICITED",
    )
    assert _total(
        api.list_leases(X.award_officer_headers(), {"prospectus_id": ctx["prospectus_id"]})
    ) == 0, "a refused award mints no lease"
