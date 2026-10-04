"""Validation corners: auth headers, role and ownership checks, tier and scope
gating, one active contract, self-approval, and fiscal guardrails."""

from test_helpers import (
    account_with_contract,
    build_user_headers,
    create_account,
    create_approved_grant,
    create_grant,
    create_ready_report,
    create_report,
    create_segment,
    get_success_data,
    ingest_category_households,
    make_data_steward_headers,
    make_supplier_analyst_headers,
    read_contract,
    read_grant,
    submit_segment,
    validate_error,
)
from test_helpers import ApiErrorId, factories
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]
SCIENTIST = TEST_USERS["insights_scientist_headers"]


def test_missing_auth_header_rejected(api):
    """A request without the role header fails the authentication-context gate.

    PRD: "A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    Design: Corner/validations/missing_auth_header_rejected
    """
    resp = api.create_supplier_account(
        factories.supplier_account_payload(account_name="No Header"),
        {"X-User-ID": "someone", "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400)


def test_analyst_cannot_create_cycle(api):
    """Cycle creation is not among the supplier analyst's permitted operations.

    PRD: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    Design: Corner/validations/analyst_cannot_create_cycle
    """
    resp = api.create_cycle(
        factories.cycle_payload(),
        make_supplier_analyst_headers("analyst-orphan-1"),
    )
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value, 403)


def test_analyst_cannot_use_foreign_contract(api):
    """An analyst presenting account A's identity may not spend account B's credits.

    PRD: "for any `SupplierAnalyst` write operation, the `X-User-ID` must equal the owning supplier account `id` of the target resource — a report, segment, activation, or grant belonging to a different supplier account is rejected with `ERR_FORBIDDEN_ROLE`."
    Design: Corner/validations/analyst_cannot_use_foreign_contract
    """
    acct_a = create_account(api, name="Owner A", region="NW")
    from test_helpers import create_contract

    create_contract(api, acct_a["id"])
    acct_b = create_account(api, name="Owner B", region="SE")
    contract_b = create_contract(api, acct_b["id"])
    resp = api.create_insight_report(
        factories.insight_report_payload(contract_b["id"]),
        make_supplier_analyst_headers(acct_a["id"]),
    )
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value, 403)


def test_tier_insufficient_for_brand_report(api):
    """A TIER_CATEGORY contract cannot order a BRAND_OWN report even in scope.

    PRD: "then the `report_type` must be permitted by the contract's tier, else `ERR_TIER_INSUFFICIENT`."
    Design: Corner/validations/tier_insufficient_for_brand_report
    """
    world = account_with_contract(api, name="Tier Ltd", scope_category="SNACKS", scope_brands=["ACME"])
    resp = api.create_insight_report(
        factories.insight_report_payload(world["contract"]["id"], report_type="BRAND_OWN"),
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.TIER_INSUFFICIENT.value, 422)


def test_scope_checked_before_tier(api):
    """A report both out of scope and above tier fails with the scope error.

    PRD: "first the `category_code` must be covered by one of the contract's category scopes, else the request fails with `ERR_CATEGORY_OUT_OF_SCOPE`; then the `report_type` must be permitted by the contract's tier, else `ERR_TIER_INSUFFICIENT`."
    PRD: "The scope check precedes the tier check so that a supplier probing categories it was never granted learns nothing about tier boundaries."
    Design: Corner/validations/scope_checked_before_tier
    """
    world = account_with_contract(api, name="Order Ltd", scope_category="SNACKS", scope_brands=["ACME"])
    resp = api.create_insight_report(
        factories.insight_report_payload(
            world["contract"]["id"], report_type="COMPETITOR_BLIND", category_code="DAIRY"
        ),
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.CATEGORY_OUT_OF_SCOPE.value, 422)


def test_second_active_contract_rejected(api):
    """An account already holding an ACTIVE contract cannot take a second one.

    PRD: "An account may hold at most one `ACTIVE` contract at a time: creating a second contract while one is still `ACTIVE` is rejected with `ERR_ACCOUNT_HAS_ACTIVE_CONTRACT`."
    Design: Corner/validations/second_active_contract_rejected
    """
    from test_helpers import create_contract

    account = create_account(api, name="One Contract Co")
    create_contract(api, account["id"])
    resp = api.create_subscription_contract(
        account["id"],
        factories.subscription_contract_payload(tier="TIER_PORTFOLIO", report_credit_allowance=20),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ACCOUNT_HAS_ACTIVE_CONTRACT.value, 422)


def test_self_approval_forbidden(api):
    """A steward whose identity equals the requesting analyst's account id cannot approve.

    PRD: "requires the approving steward's `X-User-ID` to differ from the grant's `requested_by_user_id` — a requester who also holds a steward credential cannot approve their own request, and the attempt is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`."
    Design: Corner/validations/self_approval_forbidden
    """
    world = account_with_contract(api, name="SoD Co")
    grant = create_grant(api, world["account"]["id"])
    resp = api.approve_grant(grant["id"], make_data_steward_headers(world["account"]["id"]))
    validate_error(resp, ApiErrorId.SELF_APPROVAL_FORBIDDEN.value, 403)
    observed = read_grant(api, grant["id"])
    assert observed["status"] == "REQUESTED"


def test_insufficient_report_credits_rejected(api):
    """A COMPETITOR_BLIND report against an allowance of two reserves nothing and fails.

    PRD: "the reservation requires `report_credits_available` to be at least `credit_cost`, failing with `ERR_INSUFFICIENT_REPORT_CREDITS` otherwise."
    Design: Corner/validations/insufficient_report_credits_rejected
    """
    world = account_with_contract(
        api,
        name="Broke Co",
        tier="TIER_PORTFOLIO",
        report_credit_allowance=2,
        scope_category="SNACKS",
        scope_brands=["ACME"],
    )
    resp = api.create_insight_report(
        factories.insight_report_payload(world["contract"]["id"], report_type="COMPETITOR_BLIND"),
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.INSUFFICIENT_REPORT_CREDITS.value, 402)
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credits_reserved"] == 0


def test_amend_below_consumed_rejected(api):
    """An amendment dropping the allowance below consumed plus reserved is refused.

    PRD: "an amendment that would push the new allowance below the sum of already-consumed and currently-reserved credits is rejected with `ERR_ALLOWANCE_BELOW_CONSUMED` — commitments already made must remain fundable."
    Design: Corner/validations/amend_below_consumed_rejected
    """
    world = account_with_contract(api, name="Amend Co", scope_category="SNACKS", scope_brands=["ACME"])
    ingest_category_households(api, 20, "m")
    create_ready_report(api, world["contract"]["id"], world["analyst_headers"])
    current = read_contract(api, world["contract"]["id"])
    resp = api.amend_contract(
        world["contract"]["id"],
        factories.amend_payload(current["version"], credit_allowance_delta=-10),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ALLOWANCE_BELOW_CONSUMED.value, 402)
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credit_allowance"] == 10


def test_query_budget_exhaustion_boundary(api):
    """A query costing exactly the remaining budget succeeds; the next is refused.

    PRD: "The `query_cost` must not exceed `query_budget_remaining` (else `ERR_INSUFFICIENT_QUERY_BUDGET`)."
    Design: Corner/validations/query_budget_exhaustion_boundary
    """
    world = account_with_contract(api, name="Exact Co")
    grant = create_approved_grant(
        api, world["account"]["id"], steward_user_id="steward-11", query_budget_total=6
    )
    first = get_success_data(api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES"], estimated_rows=5200),
        world["analyst_headers"],
    ))
    assert first["status"] == "EXECUTED"
    assert first["query_cost"] == 6
    observed = read_grant(api, grant["id"])
    assert observed["query_budget_remaining"] == 0
    validate_error(
        api.submit_query(
            grant["id"],
            factories.query_payload(dataset_joins=["SALES"], estimated_rows=1000),
            world["analyst_headers"],
        ),
        ApiErrorId.INSUFFICIENT_QUERY_BUDGET.value,
        402,
    )


def test_segment_approve_minimum_boundary(api):
    """A segment of twenty-four fails approval; grown to exactly twenty-five it approves.

    PRD: "the steward may approve a segment only while it is `PENDING_APPROVAL` (else `ERR_INVALID_STATE`) and only when its `size` is at least the minimum segment size of twenty-five households; a smaller segment fails approval with `ERR_SEGMENT_BELOW_MINIMUM`."
    Design: Corner/validations/segment_approve_minimum_boundary
    """
    world = account_with_contract(api, name="Boundary Co", scope_category="SNACKS", scope_brands=["ACME"])
    ingest_category_households(api, 24, "g")
    segment = create_segment(api, world["contract"]["id"], world["analyst_headers"], segment_name="Boundary")
    submit_segment(api, segment["id"], world["analyst_headers"])
    steward = make_data_steward_headers("steward-12")
    resp = api.approve_segment(segment["id"], steward)
    validate_error(resp, ApiErrorId.SEGMENT_BELOW_MINIMUM.value, 422)
    observed = get_success_data(api.get_segment(segment["id"], world["analyst_headers"]))
    assert observed["status"] == "PENDING_APPROVAL"
    get_success_data(api.reject_segment(segment["id"], steward))
    ingest_category_households(api, 1, "g25x")
    resubmitted = submit_segment(api, segment["id"], world["analyst_headers"])
    assert resubmitted["size"] == 25
    approved = get_success_data(api.approve_segment(segment["id"], steward))
    assert approved["status"] == "APPROVED"
