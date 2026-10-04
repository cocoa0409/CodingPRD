"""Concentrate purchase orders: dual-variant pricing, tiers, lifecycle, OCC."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    validate_success,
    validate_paginated,
    get_success_data,
    seed_active_agreement,
    create_price_index,
    create_cpo,
    ops_headers,
)

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / concentrate_provisional_vs_final_diverge_on_same_order
# ---------------------------------------------------------------------------

def test_cpo_provisional_pricing_uses_latest_index_at_placement(api):
    """PRD §3.2: "For the provisional variant, the selected index is the
    `index_value` of the most recent concentrate price index for the brand
    whose `quarter` is on or before the order's `delivery_quarter`; because at
    most one index exists per quarter, \"most recent\" is unambiguous."
    PRD §3.2: "The unit price is the scaled base multiplied by one minus the
    applied discount, rounded half-up to 4 decimal places, and stored as
    `provisional_unit_price`."

    Design: Difficulty/dual_variant_calc/concentrate_provisional_vs_final_diverge_on_same_order
    """
    env = seed_active_agreement()  # index 110.00 at 2026-Q2, base $12.0000, base_index 100
    cpo = create_cpo(env, quantity_gallons=10000, delivery_quarter="2026-Q3")
    # 12.0000 * (110/100) = 13.2000; qty 10000 -> 0% tier discount
    assert cpo["provisional_unit_price"] == pytest.approx(13.2, abs=1e-9)
    assert cpo["provisional_amount_cents"] == 13200000
    assert cpo["pricing_status"] == "PROVISIONAL"


def test_cpo_final_pricing_uses_mean_index_and_diverges(api):
    """PRD §3.2: "The final variant selects its index differently: it is the
    arithmetic mean, rounded half-up to 4 decimal places, of the `index_value`
    over every concentrate price index row recorded for the brand up to the
    moment of finalization (per-quarter uniqueness makes this a mean over
    distinct quarters)."
    PRD §3.2: "The same tier-discount and rounding pipeline then produces
    `final_unit_price` and `final_amount_cents`, and the system records
    `price_delta_cents` as the final amount minus the provisional amount."

    Design: Difficulty/dual_variant_calc/concentrate_provisional_vs_final_diverge_on_same_order
    """
    env = seed_active_agreement()  # 110.00 @ 2026-Q2
    cpo = create_cpo(env, quantity_gallons=10000, delivery_quarter="2026-Q3")
    create_price_index(env["bo"]["id"], quarter="2026-Q3", index_value=120.00)
    r = api_client.receive_cpo(cpo["id"], ops_headers(env))
    assert r.status_code == 200
    data = get_success_data(api_client.finalize_cpo(cpo["id"], ops_headers(env)))
    # mean(110, 120) = 115; 12.0 * 115/100 = 13.8000
    assert data["provisional_unit_price"] == pytest.approx(13.2, abs=1e-9)
    assert data["provisional_amount_cents"] == 13200000
    assert data["final_unit_price"] == pytest.approx(13.8, abs=1e-9)
    assert data["final_amount_cents"] == 13800000
    assert data["price_delta_cents"] == 600000
    assert data["pricing_status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / concentrate_tiered_discount_capped_at_max
# ---------------------------------------------------------------------------

def test_cpo_tier3_discount_clipped_to_max_at_60000_gallons(api):
    """PRD §3.2: "orders of 50,000 gallons or more earn a tier percentage of
    three and a half percent. The discount actually applied is capped at three
    percent — the maximum discount — so the two-percent tier applies in full
    while the three-and-a-half-percent tier is clipped to three percent."

    Design: Difficulty/combinatorial_formula/concentrate_tiered_discount_capped_at_max
    """
    env = seed_active_agreement()
    cpo = create_cpo(env, quantity_gallons=60000, delivery_quarter="2026-Q3")
    # unit_raw = 12.0 * 1.1 = 13.2; discount = min(0.035, 0.03) = 0.03
    # unit = round(13.2 * 0.97, 4) = 12.804; amount = 12.804 * 60000 * 100
    assert cpo["provisional_unit_price"] == pytest.approx(12.804, abs=1e-9)
    assert cpo["provisional_amount_cents"] == 76824000


def test_cpo_tier1_discount_applies_in_full_at_25000_gallons(api):
    """PRD §3.2: "A volume discount then applies by tier: orders below 25,000
    gallons receive no discount; orders of at least 25,000 gallons but fewer
    than 50,000 gallons earn a tier percentage of two percent; orders of 50,000
    gallons or more earn a tier percentage of three and a half percent."

    Design: Difficulty/combinatorial_formula/concentrate_tiered_discount_capped_at_max
    """
    env = seed_active_agreement()
    cpo = create_cpo(env, quantity_gallons=25000, delivery_quarter="2026-Q3")
    # unit_raw = 13.2; discount 2% -> unit = round(13.2 * 0.98, 4) = 12.936
    assert cpo["provisional_unit_price"] == pytest.approx(12.936, abs=1e-9)
    assert cpo["provisional_amount_cents"] == 32340000


# ---------------------------------------------------------------------------
# Queue B: calculations / concentrate_provisional_without_index_uses_base_index
# ---------------------------------------------------------------------------

def test_cpo_provisional_without_index_uses_base_index(api):
    """PRD §3.2: "If no index row exists at or before the delivery quarter, the
    selected index falls back to the agreement's own `concentrate_base_index`,
    which leaves the ratio at exactly one."

    Design: Corner/calculations/concentrate_provisional_without_index_uses_base_index
    """
    env = seed_active_agreement(
        with_index=False, line_is_mandatory=False, line_base_price=12.5
    )
    cpo = create_cpo(env, quantity_gallons=10000, delivery_quarter="2026-Q3")
    # ratio = 1 -> unit == base price 12.5, no discount below 25000 gallons
    assert cpo["provisional_unit_price"] == pytest.approx(12.5, abs=1e-9)
    assert cpo["provisional_amount_cents"] == 12500000


# ---------------------------------------------------------------------------
# Queue B: consistency_model / cpo_create_response_immediately_shows_computed_prices
# ---------------------------------------------------------------------------

def test_cpo_create_response_immediately_shows_computed_prices(api):
    """PRD §3.2: "The unit price is the scaled base multiplied by one minus the
    applied discount, rounded half-up to 4 decimal places, and stored as
    `provisional_unit_price`. The provisional extended amount,
    `provisional_amount_cents`, is that unit price multiplied by the gallon
    quantity and by 100, rounded half-up to whole cents."

    Design: Corner/consistency_model/cpo_create_response_immediately_shows_computed_prices
    """
    env = seed_active_agreement()
    r = api_client.create_cpo(
        {
            "agreement_id": env["agreement"]["id"],
            "product_line_id": env["line"]["id"],
            "quantity_gallons": 10000,
            "delivery_quarter": "2026-Q3",
            "expected_agreement_version": env["ag_v1"],
        },
        ops_headers(env),
    )
    assert r.status_code == 201
    created = get_success_data(r)
    assert created["provisional_unit_price"] == pytest.approx(13.2, abs=1e-9)
    assert created["provisional_amount_cents"] == 13200000
    fetched = validate_success(api_client.get_cpo(created["id"], ops_headers(env)))
    assert fetched["provisional_unit_price"] == pytest.approx(13.2, abs=1e-9)
    assert fetched["provisional_amount_cents"] == 13200000


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers / cpo_create_with_stale_agreement_version_rejected
# ---------------------------------------------------------------------------

def test_cpo_create_with_stale_agreement_version_rejected(api):
    """PRD §2.8: "Placing a concentrate purchase order requires the request to
    carry `expected_agreement_version`, holding the caller's last observed
    `version` of the target `BottlerAgreement`. If the agreement's current
    `version` has advanced beyond that value — for instance because another
    order was placed against it, or any other mutation touched it — the
    placement is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/cpo_create_with_stale_agreement_version_rejected
    """
    env = seed_active_agreement()
    create_cpo(env)  # bumps agreement version 2 -> 3
    r = api_client.create_cpo(
        {
            "agreement_id": env["agreement"]["id"],
            "product_line_id": env["line"]["id"],
            "quantity_gallons": 10000,
            "delivery_quarter": "2026-Q3",
            "expected_agreement_version": env["ag_v1"],  # stale: still 2
        },
        ops_headers(env),
    )
    validate_error(r, ApiErrorId.ERR_STALE_VERSION.value)
    assert r.status_code == 412
    data, meta = validate_paginated(
        api_client.list_cpos(ops_headers(env), params={"agreement_id": env["agreement"]["id"]})
    )
    assert meta["total_count"] == 1, "exactly one CPO must exist for the agreement"
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Queue B: validations / cpo_below_min_quantity_on_active_agreement_rejected
# ---------------------------------------------------------------------------

def test_cpo_below_min_quantity_on_active_agreement_rejected(api):
    """PRD §3.2: "The minimum order quantity is 1000 gallons; a
    `quantity_gallons` below that floor is rejected with
    `ERR_MIN_ORDER_QUANTITY` (HTTP 422)."

    Design: Corner/validations/cpo_below_min_quantity_on_active_agreement_rejected
    """
    env = seed_active_agreement()
    r = api_client.create_cpo(
        {
            "agreement_id": env["agreement"]["id"],
            "product_line_id": env["line"]["id"],
            "quantity_gallons": 999,
            "delivery_quarter": "2026-Q3",
            "expected_agreement_version": env["ag_v1"],
        },
        ops_headers(env),
    )
    validate_error(r, ApiErrorId.ERR_MIN_ORDER_QUANTITY.value)
    assert r.status_code == 422
    r2 = api_client.create_cpo(
        {
            "agreement_id": env["agreement"]["id"],
            "product_line_id": env["line"]["id"],
            "quantity_gallons": 1000,
            "delivery_quarter": "2026-Q3",
            "expected_agreement_version": env["ag_v1"],
        },
        ops_headers(env),
    )
    assert r2.status_code == 201, f"1000-gallon order at the floor must be accepted: {r2.text}"


# ---------------------------------------------------------------------------
# Queue B: state_machines / cpo_finalize_before_receive_rejected
# ---------------------------------------------------------------------------

def test_cpo_finalize_before_receive_rejected(api):
    """PRD §3.2: "finalizing an order that has not been received is rejected
    with `ERR_INVALID_STATE` (HTTP 409), because the final price requires
    physical receipt."

    Design: Corner/state_machines/cpo_finalize_before_receive_rejected
    """
    env = seed_active_agreement()
    cpo = create_cpo(env)
    r = api_client.finalize_cpo(cpo["id"], ops_headers(env))
    validate_error(r, ApiErrorId.ERR_INVALID_STATE.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_cpo(cpo["id"], ops_headers(env)))
    assert after["pricing_status"] == "PROVISIONAL"


# ---------------------------------------------------------------------------
# Queue B: state_machines / cpo_cancel_after_finalize_rejected
# ---------------------------------------------------------------------------

def test_cpo_cancel_after_finalize_rejected(api):
    """PRD §3.2: "Cancellation is available only while the order is still
    `PLACED` in fulfillment and still `PROVISIONAL` in pricing; a cancel
    attempt against an order already `FINALIZED` is rejected with
    `ERR_CPO_ALREADY_FINALIZED`, and a cancel against a `RECEIVED` order is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cpo_cancel_after_finalize_rejected
    """
    env = seed_active_agreement()
    cpo = create_cpo(env)
    create_price_index(env["bo"]["id"], quarter="2026-Q3", index_value=120.00)
    r = api_client.receive_cpo(cpo["id"], ops_headers(env))
    assert r.status_code == 200
    r = api_client.finalize_cpo(cpo["id"], ops_headers(env))
    assert r.status_code == 200
    r = api_client.cancel_cpo(cpo["id"], ops_headers(env))
    validate_error(r, ApiErrorId.ERR_CPO_ALREADY_FINALIZED.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_cpo(cpo["id"], ops_headers(env)))
    assert after["fulfillment_status"] == "RECEIVED"
