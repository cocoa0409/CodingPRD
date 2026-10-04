"""Issuer fee calculation: nested min/max floor-cap ordering (queue A)."""
from test_helpers import (
    approved_authorization,
    get_success_data,
    setup_provisioned_token,
    OPERATOR,
)


def _ns(api):
    # fee_bps 50, cap 200, floor 25
    return setup_provisioned_token(
        api, fee_bps=50, fee_cap_cents=200, fee_floor_cents=25,
        express_supported=False,
    )


def test_fee_floor_branch_for_tiny_amount(api):
    """PRD section 3.6: "the raw fee is the amount_cents multiplied by the
    agreement's fee_bps and divided by 10000 with floor division (truncation
    toward zero); the result is then capped from above by fee_cap_cents (the
    smaller of the raw fee and the cap is kept), and finally floored from below
    by fee_floor_cents (the larger of the capped value and the floor is kept)."
    For amount 1000 with fee_bps 50 the raw fee is floor(1000*50/10000)=5,
    below the floor of 25, so the charged fee is 25.

    Design: Difficulty/combinatorial_formula/issuer_fee_floor_cap_nested_min_max_ordering
    """
    ns = _ns(api)
    approved_authorization(api, ns["token"], amount_cents=1000, cryptogram="cgm-small")
    proj = get_success_data(api.get_fee_projection(ns["issuer"]["id"], OPERATOR))
    assert proj["approved_fee_cents"] == 25, (
        f"expected floor branch fee 25, got {proj['approved_fee_cents']}"
    )


def test_fee_cap_branch_for_large_amount(api):
    """PRD section 3.6: "the result is then capped from above by fee_cap_cents
    (the smaller of the raw fee and the cap is kept), and finally floored from
    below by fee_floor_cents (the larger of the capped value and the floor is
    kept)." For amount 100000 with fee_bps 50 the raw fee is
    floor(100000*50/10000)=500, above the cap of 200, so the charged fee is 200.

    Design: Difficulty/combinatorial_formula/issuer_fee_floor_cap_nested_min_max_ordering
    """
    ns = _ns(api)
    approved_authorization(api, ns["token"], amount_cents=100000, cryptogram="cgm-big")
    proj = get_success_data(api.get_fee_projection(ns["issuer"]["id"], OPERATOR))
    assert proj["approved_fee_cents"] == 200, (
        f"expected cap branch fee 200, got {proj['approved_fee_cents']}"
    )
