"""Corner queue B: error envelope shape, RBAC gating, appeal identity, and
immediate consistency."""

from test_helpers import (
    ADMIN,
    FRAUD,
    NON_EXISTENT_UUID,
    OPS,
    PAY,
    complete_ride_end_to_end,
    create_driver,
    create_market,
    create_market_with_driver,
    file_eligibility_appeal,
    finalize_settlement,
    make_driver_headers,
    open_fraud_flag,
    read_statement,
    set_clock,
    setup_appeal_under_review,
    setup_finalized_settlement,
    setup_guarantee_with_rides,
    compute_statement,
    pay_settlement,
    read_market,
    validate_error,
    validate_success,
    ApiErrorId,
)


# ============================================================================
# corner: errors
# ============================================================================
def test_error_envelope_shape_on_any_4xx(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format: { meta: { api_request_id,
    api_request_timestamp }, response_type: 'error', data: { error_id,
    message } }."
    PRD §2.9: "The first missing identifier short-circuits with ERR_NOT_FOUND
    (HTTP 404); later segments are not consulted."

    Design: Corner/errors/error_envelope_shape_on_any_4xx
    """
    set_clock()
    response = api.get_driver(NON_EXISTENT_UUID, OPS)
    assert response.status_code == 404
    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"]


# ============================================================================
# corner: rbac
# ============================================================================
def test_driver_cannot_create_market(api):
    """PRD §2.1: "A request that arrives without both headers, or whose role is
    not among those authorized for the target endpoint, is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4: POST /markets is authorized for PlatformAdmin only.

    Design: Corner/rbac/driver_cannot_create_market
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="DAB")

    response = api.create_market(
        {"market_code": "NOPE", "geo_cells": ["cellA"],
         "incentive_budget_cents": 1},
        make_driver_headers(driver["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_payments_officer_cannot_confirm_fraud_flag(api):
    """PRD §4: POST /fraud-flags/{id}/confirm is authorized for FraudAnalyst
    only.
    PRD §2.1: "A request whose headers are present but whose role is not
    authorized for the endpoint is also rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/payments_officer_cannot_confirm_fraud_flag
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="SFB")
    ride = complete_ride_end_to_end(driver, market["id"], base_fare_cents=5000)
    flag = open_fraud_flag(driver["id"], ride["id"], severity=3,
                           signal_type="LOCATION_SPOOF")

    response = api.confirm_fraud_flag(flag["id"], PAY)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    from test_helpers import read_fraud_flag
    assert read_fraud_flag(flag["id"])["status"] == "OPEN"


def test_appeal_provide_info_identity_mismatch_rejected(api):
    """PRD §3.10: "only the appeal's own driver may provide information, and an
    acting X-User-ID that does not match the appeal's driver_id is refused with
    ERR_APPEAL_IDENTITY_MISMATCH (HTTP 403)."
    PRD §2.1: "Ownership checks on any resource that references a Driver
    compare the resource's driver_id field to X-User-ID."

    Design: Corner/rbac/appeal_provide_info_identity_mismatch_rejected
    """
    set_clock()
    market = create_market(market_code="PFN", incentive_budget_cents=1_000_000)
    driver_a = create_driver(market["id"], display_name="Owner Owen")
    driver_b = create_driver(market["id"], display_name="Intruder Ingrid")

    appeal = file_eligibility_appeal(driver_a)
    validate_success(api.start_appeal_review(appeal["id"], PAY), 200)
    appeal = validate_success(api.request_appeal_info(appeal["id"], PAY), 200)
    assert appeal["status"] == "MORE_INFO"

    response = api.provide_appeal_info(appeal["id"], make_driver_headers(driver_b["id"]))
    validate_error(response, ApiErrorId.ERR_APPEAL_IDENTITY_MISMATCH.value)

    from test_helpers import read_appeal
    appeal = read_appeal(appeal["id"])
    assert appeal["status"] == "MORE_INFO"
    assert appeal["round_count"] == 0


# ============================================================================
# corner: consistency_model
# ============================================================================
def test_settlement_pay_immediately_visible_in_statement_and_market(api):
    """PRD §3.8: "Payment is permitted from FINALIZED only, requires the
    market's budget_available_cents to cover make_up_cents (over-budget
    payments are refused with ERR_BUDGET_EXCEEDED), adds the make-up to the
    market's budget_spent_cents, sets paid_at_utc, and triggers recompute of
    the week's EarningsStatement make_up_total_cents and total_cents."

    Design: Corner/consistency_model/settlement_pay_immediately_visible_in_statement_and_market
    """
    market, driver, program, enrollment, rides, settlement = (
        setup_finalized_settlement(market_code="EVV", budget=10_000_000,
                                   guaranteed_min_rides=1,
                                   ride_fares_cents=(100_000,))
    )
    statement = compute_statement(driver["id"])

    settlement = validate_success(api.pay_settlement(settlement["id"], PAY), 200)
    assert settlement["status"] == "PAID"
    assert settlement["paid_at_utc"], "paid_at_utc must be set on PAID"

    market = read_market(market["id"])
    assert market["budget_spent_cents"] == 400_000

    statement = read_statement(statement["id"])
    assert statement["make_up_total_cents"] == 400_000
    assert statement["total_cents"] == 500_000, (
        f"100000 base + 0 tips + 0 bonus + 400000 make_up = 500000, got "
        f"{statement['total_cents']}"
    )
