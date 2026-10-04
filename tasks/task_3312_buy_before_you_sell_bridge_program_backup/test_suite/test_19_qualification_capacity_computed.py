"""Capacity is computed server-side at qualification creation (PRD section 3.2)."""
import pytest
from test_helpers import (
    api_client, validate_success, assert_qualification,
    reset_clock, build_qualified_household, create_qualification, TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _scenario():
    # Departing equity 60000000 - 30000000 = 30000000, grade B (1000 bps of condition credit).
    return build_qualified_household(
        income_cents=10_000_000,
        departing={"address": "2 Def Way", "appraised_value_cents": 60_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "3 Def Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )


def test_qualification_computes_its_capacity_when_created(api):
    """PRD section 3.2: "Both then apply a base ratio that credits the household with 7000
    basis points of that equity, and both add a condition credit earned by the departing
    home's state of repair."

    Design: Corner/entities/qualification_capacity_computed_on_create
    """
    reset_clock()
    sc = _scenario()
    q = create_qualification(sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
                             variant_used="CONSERVATIVE", target_purchase_price_cents=50_000_000)
    assert_qualification(q)
    assert q["status"] == "PENDING"
    # 30000000 * (7000 + 1000) // 10000
    assert q["capacity_cents"] == 24_000_000
    assert q["equity_ratio"] == pytest.approx(0.5, abs=0.0001)


def test_qualification_ignores_a_client_supplied_capacity(api):
    """PRD section 3.2: "The heart of the qualification is the `capacity_cents`, and it is
    computed twice over because the product asks the household to choose between two readings
    of the same equity."

    Design: Corner/entities/qualification_capacity_computed_on_create
    """
    reset_clock()
    sc = _scenario()
    res = api.create_qualification(
        {"homeowner_id": sc["homeowner"]["id"], "departing_property_id": sc["departing"]["id"],
         "new_property_id": sc["new"]["id"], "target_purchase_price_cents": 50_000_000,
         "variant_used": "CONSERVATIVE", "capacity_cents": 1, "equity_ratio": 0.99},
        COORD,
    )
    q = validate_success(res, 201)
    assert q["capacity_cents"] == 24_000_000, "the server's own computation decides the value"
    assert q["equity_ratio"] == pytest.approx(0.5, abs=0.0001)