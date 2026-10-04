"""Optimistic concurrency control on the order and fund transition endpoints."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    close_claims_window,
    consent_order_transition_payload,
    get_fund,
    get_order,
    get_success_data,
    propose_consent_order,
    redress_fund_transition_payload,
    setup_draft_order,
    setup_open_fund,
    validate_error,
    validate_success,
    withdraw_consent_order,
)

_ATTORNEY = TEST_USERS["staff_attorney_headers"]
_ADMIN = TEST_USERS["fund_administrator_headers"]  # fa-1


def test_order_transition_with_stale_version_returns_412():
    """PRD section 2.6: "A request to `POST
    /enforcement/consent-orders/{orderId}/transition` must carry
    `expected_consent_order_version`, holding the client's last observed
    `version` of the target consent order. If that value no longer matches
    the order's current `version` — because the client's view predates a
    committed transition, such as a withdrawal-and-reproposal that already
    advanced the version — the request is rejected with
    `ERR_STALE_ORDER_VERSION` (HTTP 412) rather than applied on a moved base."
    PRD section 2.8: "the version check fires only after the request has
    survived the state-legality check".

    Design: Corner/cross_cutting_layers/order_transition_with_stale_version_returns_412
    """
    bundle = setup_draft_order()
    order_id = bundle["order"]["id"]
    version_at_create = bundle["order"]["version"]

    proposed = propose_consent_order(order_id)
    withdrawn = withdraw_consent_order(order_id)
    assert withdrawn["status"] == "DRAFT"
    current_version = withdrawn["version"]

    # DRAFT -> IN_PUBLIC_COMMENT is legal from here; only the OCC token is stale.
    stale = api_client.transition_consent_order(
        order_id,
        consent_order_transition_payload("IN_PUBLIC_COMMENT", version_at_create),
        _ATTORNEY,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ORDER_VERSION)

    reproposed = validate_success(
        api_client.transition_consent_order(
            order_id,
            consent_order_transition_payload("IN_PUBLIC_COMMENT", current_version),
            _ATTORNEY,
        ),
        200,
    )
    assert reproposed["status"] == "IN_PUBLIC_COMMENT"
    assert reproposed["version"] == current_version + 1, (
        "each committed transition advances the version by exactly 1"
    )

    # The failed OCC attempt created no period: round 1 VOIDED, round 2 OPEN.
    periods = get_success_data(api_client.list_comment_periods(order_id, _ATTORNEY))
    assert len(periods) == 2
    assert periods[0]["round"] == 1 and periods[0]["status"] == "VOIDED"
    assert periods[1]["round"] == 2 and periods[1]["status"] == "OPEN"


def test_fund_transition_with_stale_version_returns_412():
    """PRD section 2.6: "A request to `POST
    /enforcement/redress-funds/{fundId}/transition` must carry
    `expected_redress_fund_version`, holding the client's last observed
    `version` of the target redress fund. Claim approvals and payment-cascade
    ledger syncs advance the fund's `version` between an administrator's last
    read and the transition call; a mismatch proves the administrator's view
    is out of date, and the request is rejected with `ERR_STALE_FUND_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/fund_transition_with_stale_version_returns_412
    """
    bundle = setup_open_fund(
        judgment_amount_cents=1_500_000,
        monetary_relief_cents=1_500_000,
        claimant_specs=None,
    )
    fund_id = bundle["fund"]["id"]
    stale_version = get_fund(fund_id)["version"]

    close_claims_window(fund_id)  # commits, advancing the fund's version

    stale = api_client.transition_redress_fund(
        fund_id,
        redress_fund_transition_payload("DISBURSING", stale_version),
        _ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_FUND_VERSION)

    assert get_fund(fund_id)["status"] == "CLAIMS_CLOSED"
    # Sanity: the same legal transition succeeds with the fresh version.
    fresh = get_fund(fund_id)["version"]
    ok = validate_success(
        api_client.transition_redress_fund(
            fund_id,
            redress_fund_transition_payload("DISBURSING", fresh),
            _ADMIN,
        ),
        200,
    )
    assert ok["status"] == "DISBURSING"
