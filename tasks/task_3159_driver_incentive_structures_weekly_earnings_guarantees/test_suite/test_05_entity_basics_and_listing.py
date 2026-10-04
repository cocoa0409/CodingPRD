"""Corner queue B: entity creation/defaults/not-found, required fields,
listing pagination."""

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    OPS,
    create_driver_payload,
    create_market_with_driver,
    create_streak_program,
    create_streak_program_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)


# ============================================================================
# corner: entities
# ============================================================================
def test_market_create_returns_computed_budget_fields_and_active_status(api):
    """PRD §3.1: "A freshly created market starts in ACTIVE status with
    budget_spent_cents and budget_reserved_cents both at zero and
    budget_available_cents equal to the declared ceiling."
    PRD §2.4: "version (integer): a system-managed integer starting at 1 that
    increments by exactly 1 on every mutation."

    Design: Corner/entities/market_create_returns_computed_budget_fields_and_active_status
    """
    set_clock()
    response = api.create_market(
        {"market_code": "MKE", "geo_cells": ["cellA", "cellB"],
         "incentive_budget_cents": 750_000},
        ADMIN,
    )
    market = validate_success(response, 201)
    assert market["status"] == "ACTIVE"
    assert market["version"] == 1
    assert market["budget_spent_cents"] == 0
    assert market["budget_reserved_cents"] == 0
    assert market["budget_available_cents"] == 750_000
    assert market["id"]
    assert market["created_at"]
    assert market["updated_at"]


def test_driver_create_onboards_with_eligible_rate_and_clear_fraud(api):
    """PRD §3.2: "The new Driver starts with account_status ACTIVE,
    rate_posture ELIGIBLE, fraud_posture CLEAR, and all rolling counters
    zeroed: offers_total, accepted_total, and cancelled_total are each zero,
    and acceptance_rate_bps and cancellation_rate_bps start at their
    empty-window defaults."
    PRD §3.2: "The acceptance rate in basis points is 10000 when offers_total
    is zero ... the cancellation rate in basis points is zero when
    accepted_total is zero."

    Design: Corner/entities/driver_create_onboards_with_eligible_rate_and_clear_fraud
    """
    set_clock()
    market, _d = create_market_with_driver(market_code="MKE")
    response = api.create_driver(
        create_driver_payload(market["id"], display_name="Fresh Fran"), OPS
    )
    driver = validate_success(response, 201)
    assert driver["account_status"] == "ACTIVE"
    assert driver["rate_posture"] == "ELIGIBLE"
    assert driver["fraud_posture"] == "CLEAR"
    assert driver["offers_total"] == 0
    assert driver["accepted_total"] == 0
    assert driver["cancelled_total"] == 0
    assert driver["acceptance_rate_bps"] == 10000
    assert driver["cancellation_rate_bps"] == 0


def test_get_missing_program_returns_not_found(api):
    """PRD §2.9: "The first missing identifier short-circuits with
    ERR_NOT_FOUND (HTTP 404); later segments are not consulted."

    Design: Corner/entities/get_missing_program_returns_not_found
    """
    set_clock()
    response = api.get_program(NON_EXISTENT_UUID, OPS)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value)


def test_program_create_streak_without_streak_length_rejected(api):
    """PRD §3.3: "Each program type carries its own required configuration, and
    a create call that omits a type's required fields is rejected with
    ERR_PROGRAM_CONFIG_INCOMPLETE (HTTP 400). A STREAK program requires
    streak_length (the number of consecutive qualifying rides with no decline
    or driver-cancel that completes the streak) and streak_payout_cents."

    Design: Corner/entities/program_create_streak_without_streak_length_rejected
    """
    set_clock()
    market, _d = create_market_with_driver(market_code="MKE")
    payload = create_streak_program_payload(market["id"])
    payload.pop("streak_length")
    response = api.create_program(payload, OPS)
    validate_error(response, ApiErrorId.ERR_PROGRAM_CONFIG_INCOMPLETE.value)


def test_programs_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The meta object of every list response carries four
    pagination fields: limit, offset, total_count, and has_more. The value of
    total_count is the number of items matching the filter irrespective of
    pagination, and has_more is true when further items exist beyond the
    current page."

    Design: Corner/entities/programs_list_paginates_with_total_count_and_has_more
    """
    set_clock()
    market, _d = create_market_with_driver(market_code="MKE")
    create_streak_program(market["id"], title="S1", streak_length=2,
                          streak_payout_cents=5000)
    create_streak_program(market["id"], title="S2", streak_length=3,
                          streak_payout_cents=7000)
    create_streak_program(market["id"], title="S3", streak_length=4,
                          streak_payout_cents=9000)

    page1, meta1 = validate_paginated(
        api.list_programs(OPS, params={"market_id": market["id"], "limit": 2,
                                       "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_programs(OPS, params={"market_id": market["id"], "limit": 2,
                                       "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
