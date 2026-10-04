"""License fee mathematics: quote vs invoice variants, nested surcharge/
discount/multiplier/floor interactions, and quote-time domain checks (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    activate_license,
    get_license,
    license_goto,
    quote_license,
    register_client,
    setup_awards_set_study,
    setup_published_study,
    validate_error,
    api_client,
    TEST_USERS,
)

LICMGR = TEST_USERS["licensing_manager_headers"]

_ONE_BRAND = [{"name": "BrandA", "responses": [{"token": "rt-1", "qual": 9, "feat": 8}]}]


def _published_ctx():
    return setup_published_study(min_sample=1, brands=_ONE_BRAND)


def test_quote_applies_no_discount_or_floor(api):
    """PRD §3.6: "The provisional `fee_quote_cents` computed at creation is
    deliberately simple: the tier's base fee plus a per-market surcharge for
    markets beyond the tier's included allowance. ... The quote applies neither
    the term discount, nor the prior-violation multiplier, nor the fee floor — it
    is a headline number, and the license is born `QUOTED` with `fee_final_cents`,
    `activated_at`, and `expires_at` all null and `suspension_count` at 0."

    Design: Difficulty/dual_variant_calc/license_fee_quote_vs_invoice_divergence
    """
    ctx = _published_ctx()
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    lic = quote_license(ctx["award"]["id"], client["id"], tier="DIGITAL",
                        term_months=24, markets_count=2)
    assert lic["fee_quote_cents"] == 400000, (
        f"250000 base + max(0, 2-1) x 150000, got {lic['fee_quote_cents']}"
    )
    assert lic["fee_final_cents"] is None
    assert lic["status"] == "QUOTED" and lic["suspension_count"] == 0


def test_invoice_applies_term_discount_quote_and_final_diverge(api):
    """PRD §3.6: "On activation the server computes `fee_final_cents` in a pinned
    order: start from the same surcharged base as the quote; apply the term
    discount by multiplying by 0.85 when `term_months` is at least 24 (otherwise
    by 1.00); apply the prior-violation multiplier of 1.25 when the client has any
    license, across all studies, that has ever reached `REVOKED` (otherwise 1.00);
    round half up to integer cents; and finally impose the floor so the fee is
    never less than 220000 cents."
    PRD §3.6: "Because any of those adjustments can bind, `fee_final_cents`
    routinely differs from `fee_quote_cents`."

    Design: Difficulty/dual_variant_calc/license_fee_quote_vs_invoice_divergence
    """
    ctx = _published_ctx()
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    lic = quote_license(ctx["award"]["id"], client["id"], tier="DIGITAL",
                        term_months=24, markets_count=2)
    activate_license(lic["id"])
    after = get_license(lic["id"])
    assert after["fee_final_cents"] == 340000, (
        f"round_half_up(400000 x 0.85), floor 220000 not binding, got {after['fee_final_cents']}"
    )
    assert after["fee_quote_cents"] == 400000
    assert after["fee_quote_cents"] != after["fee_final_cents"], (
        "the two variants must diverge on identical license fields"
    )


def test_market_surcharge_above_included_allowance(api):
    """PRD §3.6: "The base is 250000 cents for `DIGITAL`, 600000 cents for
    `NATIONAL`, and 1500000 cents for `GLOBAL`; the included market allowances are
    1, 3, and 999 respectively; and each market beyond the allowance adds 150000
    cents."
    PRD §3.6: "apply the term discount by multiplying by 0.85 when `term_months`
    is at least 24 (otherwise by 1.00)"

    Design: Difficulty/combinatorial_formula/license_fee_nested_surcharge_discount_multiplier
    """
    ctx = _published_ctx()
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    lic = quote_license(ctx["award"]["id"], client["id"], tier="NATIONAL",
                        term_months=12, markets_count=4)
    assert lic["fee_quote_cents"] == 750000, (
        f"600000 base + max(0, 4-3) x 150000, got {lic['fee_quote_cents']}"
    )
    activate_license(lic["id"])
    after = get_license(lic["id"])
    assert after["fee_final_cents"] == 750000, (
        f"term 12 < 24 -> no discount; no violations; above floor, got {after['fee_final_cents']}"
    )


def test_market_surcharge_boundary_at_included_allowance(api):
    """PRD §3.6: "the included market allowances are 1, 3, and 999 respectively;
    and each market beyond the allowance adds 150000 cents."

    Design: Difficulty/combinatorial_formula/license_fee_nested_surcharge_discount_multiplier
    """
    ctx = _published_ctx()
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    lic = quote_license(ctx["award"]["id"], client["id"], tier="NATIONAL",
                        term_months=12, markets_count=3)
    assert lic["fee_quote_cents"] == 600000, (
        f"markets_count 3 == included 3 -> surcharge max(0, 3-3) == 0, got {lic['fee_quote_cents']}"
    )


def test_license_fee_floor_binds(api):
    """PRD §3.6: "On activation the server computes `fee_final_cents` in a pinned
    order: start from the same surcharged base as the quote; apply the term
    discount by multiplying by 0.85 when `term_months` is at least 24 (otherwise
    by 1.00); ... round half up to integer cents; and finally impose the floor so
    the fee is never less than 220000 cents. Surcharge first, discounts and
    multipliers on the surcharged base, floor last."

    Design: Corner/calculations/license_fee_floor_binds
    """
    ctx = _published_ctx()
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    lic = quote_license(ctx["award"]["id"], client["id"], tier="DIGITAL",
                        term_months=24, markets_count=1)
    assert lic["fee_quote_cents"] == 250000, "the quote ignores the floor"
    activate_license(lic["id"])
    after = get_license(lic["id"])
    assert after["fee_final_cents"] == 220000, (
        f"round_half_up(250000 x 0.85) = 212500 is below the 220000 floor, got {after['fee_final_cents']}"
    )


def test_license_fee_violation_multiplier_after_revoke(api):
    """PRD §3.6: "apply the prior-violation multiplier of 1.25 when the client has
    any license, across all studies, that has ever reached `REVOKED` (otherwise
    1.00)"
    PRD §3.6: "The quote applies neither the term discount, nor the
    prior-violation multiplier, nor the fee floor"
    PRD §3.6: "no other license on the same award may currently be `ACTIVE`:
    occupation is a half-open interval from `activated_at` up to but not including
    `expires_at`"

    Design: Corner/calculations/license_fee_violation_multiplier_after_revoke
    """
    ctx = _published_ctx()
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    l1 = quote_license(ctx["award"]["id"], client["id"], tier="DIGITAL",
                       term_months=12, markets_count=1)
    activate_license(l1["id"])
    license_goto(l1["id"], "REVOKED")

    l2 = quote_license(ctx["award"]["id"], client["id"], tier="DIGITAL",
                       term_months=12, markets_count=1)
    assert l2["fee_quote_cents"] == 250000, "the quote does not see the violation history"
    activate_license(l2["id"])  # REVOKED predecessor does not occupy the award
    after = get_license(l2["id"])
    assert after["fee_final_cents"] == 312500, (
        f"round_half_up(250000 x 1.00 x 1.25), got {after['fee_final_cents']}"
    )
    assert get_license(l1["id"])["status"] == "REVOKED"


def test_license_term_invalid_returns_422(api, licensing_manager_headers):
    """PRD §3.6: "a `term_months` of exactly 12, 24, or 36 (anything else is
    rejected with `ERR_LICENSE_TERM_INVALID`)"

    Design: Corner/errors/license_term_invalid_returns_422
    """
    ctx = setup_awards_set_study(min_sample=1, brands=_ONE_BRAND)
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    payload = {
        "award_id": ctx["awards"][0]["id"],
        "client_id": client["id"],
        "tier": "DIGITAL",
        "term_months": 13,
        "markets_count": 1,
    }
    resp = api.create_license(payload, licensing_manager_headers)
    validate_error(resp, ApiErrorId.ERR_LICENSE_TERM_INVALID)
    assert api_client.list_licenses(licensing_manager_headers).json()["data"] == [], (
        "no license may be created"
    )


def test_license_markets_invalid_returns_422(api, licensing_manager_headers):
    """PRD §3.6: "a `markets_count` of at least 1 (otherwise
    `ERR_MARKETS_INVALID`)"

    Design: Corner/errors/license_markets_invalid_returns_422
    """
    ctx = setup_awards_set_study(min_sample=1, brands=_ONE_BRAND)
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    payload = {
        "award_id": ctx["awards"][0]["id"],
        "client_id": client["id"],
        "tier": "DIGITAL",
        "term_months": 12,
        "markets_count": 0,
    }
    resp = api.create_license(payload, licensing_manager_headers)
    validate_error(resp, ApiErrorId.ERR_MARKETS_INVALID)
    assert api_client.list_licenses(licensing_manager_headers).json()["data"] == [], (
        "no license may be created"
    )
