"""Priority pairs: when two rules fail at once, the earlier cascade stage wins."""

from test_helpers import (
    account_with_contract,
    create_approved_grant,
    create_approved_segment,
    get_success_data,
    ingest_category_households,
    make_data_steward_headers,
    validate_error,
)
from test_helpers import ApiErrorId, factories
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]


def _revoked_grant_world(api):
    """Grant approved and then revoked, ready to receive a query."""
    world = account_with_contract(api, name="Eta Eggs")
    grant = create_approved_grant(api, world["account"]["id"], steward_user_id="steward-pp1")
    get_success_data(api.revoke_grant(grant["id"], make_data_steward_headers("steward-pp1")))
    return world, grant


def test_revoked_grant_query_reports_state_error_not_suppression(api):
    """A query on a revoked grant fails the state gate even though its rows fall below the privacy floor.

    PRD: "Every request passes through a fixed validation cascade, evaluated in this order. Earlier failures mask later ones — a request rejected at an earlier stage never surfaces a later stage's error."
    PRD: "**State preconditions.** The target resource must be in a legal state for the operation (the family of state errors such as `ERR_CONTRACT_NOT_ACTIVE`, `ERR_GRANT_NOT_QUERYABLE`, `ERR_INVALID_STATE`, and their peers)."
    Design: Difficulty/priority_pair_validation_conflict/grant_state_error_beats_cell_suppression
    """
    world, grant = _revoked_grant_world(api)
    resp = api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES"], estimated_rows=5),
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.GRANT_NOT_QUERYABLE.value, 409)


def test_revoked_grant_never_evaluates_the_privacy_floor(api):
    """The sub-minimum result rows never surface a suppression outcome once the state gate fires.

    PRD: "The grant must be `APPROVED` (else `ERR_GRANT_NOT_QUERYABLE`) and the logical clock must be before `valid_until`"
    PRD: "Queries that fail the grant or budget gates are `REJECTED` rather than executed."
    Design: Difficulty/priority_pair_validation_conflict/grant_state_error_beats_cell_suppression
    """
    world, grant = _revoked_grant_world(api)
    resp = api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES"], estimated_rows=5),
        world["analyst_headers"],
    )
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_GRANT_NOT_QUERYABLE"
    assert resp.status_code == 409


def _out_of_scope_world(api):
    """APPROVED segment whose category is then removed from the contract's scope."""
    world = account_with_contract(
        api, name="Theta Tea", activation_budget_cents=10, scope_category="SNACKS", scope_brands=["ACME"]
    )
    ingest_category_households(api, 25, "t")
    segment = create_approved_segment(api, world["contract"]["id"], world["analyst_headers"], segment_name="Tea Snackers")
    amended = get_success_data(api.amend_contract(
        world["contract"]["id"],
        factories.amend_payload(world["contract"]["version"], remove_category_codes=["SNACKS"]),
        ADMIN,
    ))
    return world, segment, amended


def test_activation_out_of_scope_shadows_budget_shortfall(api):
    """With the category removed and the budget too small, the referential error surfaces first.

    PRD: "its `category_code` must still be in the sponsoring contract's scope at both creation and launch time (else `ERR_CATEGORY_OUT_OF_SCOPE`)"
    PRD: "**Referential business rules.** Category scope, tier permission, the one-active-contract-per-account rule, and modeled-derivation permission (`ERR_CATEGORY_OUT_OF_SCOPE`, `ERR_TIER_INSUFFICIENT`, `ERR_ACCOUNT_HAS_ACTIVE_CONTRACT`, `ERR_MODELED_DERIVATION_FORBIDDEN`)."
    Design: Difficulty/priority_pair_validation_conflict/scope_error_beats_activation_budget
    """
    world, segment, _ = _out_of_scope_world(api)
    resp = api.create_activation(
        segment["id"],
        factories.activation_payload(segment["version"], channels=["COUPON"]),
        world["analyst_headers"],
    )
    validate_error(resp, ApiErrorId.CATEGORY_OUT_OF_SCOPE.value, 422)


def test_activation_scope_check_precedes_the_fiscal_gate(api):
    """The fiscal stage never reports when the referential stage has already failed.

    PRD: "Every request passes through a fixed validation cascade, evaluated in this order. Earlier failures mask later ones — a request rejected at an earlier stage never surfaces a later stage's error."
    PRD: "**Fiscal rules.** Credit, allowance, activation budget, and query budget sufficiency (`ERR_INSUFFICIENT_REPORT_CREDITS`, `ERR_ALLOWANCE_BELOW_CONSUMED`, `ERR_ACTIVATION_BUDGET_EXCEEDED`, `ERR_INSUFFICIENT_QUERY_BUDGET`)."
    Design: Difficulty/priority_pair_validation_conflict/scope_error_beats_activation_budget
    """
    world, segment, _ = _out_of_scope_world(api)
    resp = api.create_activation(
        segment["id"],
        factories.activation_payload(segment["version"], channels=["COUPON"]),
        world["analyst_headers"],
    )
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_CATEGORY_OUT_OF_SCOPE"
    assert resp.status_code == 422
