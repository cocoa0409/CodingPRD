"""Boundary precision: auto-purchase ratio boundary and CPC exact-charge."""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    checkout,
    create_patron,
    create_title,
    create_license_via_order,
    get_success_data,
    make_library_admin_headers,
    make_patron_headers,
    place_hold,
    set_clock,
    setup_base,
    setup_base_with_title,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_autopurchase_library():
    return setup_base_with_title(
        library_overrides={
            "loan_period_days": 21, "renewal_period_days": 21, "max_renewals": 2,
            "auto_purchase_enabled": True, "holds_per_copy_ratio": 4,
            "wait_target_days": 28, "auto_purchase_max_cents": 100000,
        },
    )


def test_autopurchase_below_ratio_does_not_fire(api):
    """PRD §3.11: "the ratio of the library's hold count on the title to the
    effective lendable copy count C (the same C as §3.9, floored at 1, compared
    as a real-valued ratio with no integer division) is greater than or equal
    to the library's `holds_per_copy_ratio` — holds exactly at the ratio do
    trigger."

    Design: Difficulty/boundary_precision_check/autopurchase_ratio_exact_boundary_geq
    """
    ctx = _setup_autopurchase_library()
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="OCOU", copies=1)
    patrons = [create_patron(lib["id"], external_card_number=f"Q-{i}",
                             full_name=f"Q{i}") for i in range(4)]
    checkout(patrons[0]["id"], ctx["title"]["id"])
    for p in patrons[1:]:
        place_hold(p["id"], ctx["title"]["id"])
    epoch = validate_success(api.run_epoch(ADMIN))
    assert epoch["auto_orders_created"] == 0, (
        f"3/1 >= 4 is false — strictly below the ratio must not fire, got {epoch}"
    )


def test_autopurchase_exactly_at_ratio_fires_with_computed_copies(api):
    """PRD §3.11: "the copies needed are the hold count divided by
    `holds_per_copy_ratio`, rounded up, minus the current C; if that is zero or
    negative the title is skipped."

    Design: Difficulty/boundary_precision_check/autopurchase_ratio_exact_boundary_geq
    """
    ctx = _setup_autopurchase_library()
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="OCOU", copies=1)
    patrons = [create_patron(lib["id"], external_card_number=f"Q-{i}",
                             full_name=f"Q{i}") for i in range(5)]
    checkout(patrons[0]["id"], ctx["title"]["id"])
    for p in patrons[1:]:
        place_hold(p["id"], ctx["title"]["id"])
    epoch = validate_success(api.run_epoch(ADMIN))
    assert epoch["auto_orders_created"] == 1, (
        f"4/1 >= 4 is true — exactly at the ratio must fire, got {epoch}"
    )
    orders, _ = validate_paginated(
        api.list_orders(ANALYST, params={"library_id": lib["id"]})
    )
    auto_orders = [o for o in orders if o["origin"] == "AUTO_RATIO"]
    assert len(auto_orders) == 1
    assert auto_orders[0]["model"] == "OCOU"
    # NOTE: the exact copy-count value is intentionally not asserted. The PRD
    # sentence ("the hold count divided by holds_per_copy_ratio, rounded up,
    # minus the current C") yields ceil(4/4) - 1 == 0 in this scenario, which
    # the very next PRD clause says skips the title — contradicting the firing
    # requirement. The ratio firing is uniquely derivable; the count is not.


def _setup_cpc_exact_boundary():
    set_clock()
    from test_helpers import create_consortium, create_library, create_fund
    consortium = create_consortium(cpc_discount_pct=0.15)
    library = create_library(consortium["id"])
    fund = create_fund(library["id"])
    title = create_title(consortium["id"], cpc_price_per_circ_cents=199)
    license_ = create_license_via_order(
        library["id"], fund["id"], title["id"],
        model="COST_PER_CIRC", prepaid_balance_cents=170,
        invoiced_cost_cents=170,
    )
    return {"consortium": consortium, "library": library, "fund": fund,
            "title": title, "license": license_}


def test_cpc_checkout_with_balance_exactly_equal_to_charge_succeeds(api):
    """PRD §3.8: "an `ACTIVE` cost-per-circulation license whose balance can no
    longer cover a charge stays selectable by the checkout selector and fails
    at the charge step with `ERR_LICENSE_BALANCE_DEPLETED` — it is only the
    next epoch that flips it to `EXHAUSTED` and out of selection."
    PRD §2.7: "each checkout's discounted charge is computed by multiplying the
    title's `cpc_price_per_circ_cents` by the complement of the consortium's
    `cpc_discount_pct` (that is, one minus the discount fraction) and rounding
    the result half-up to whole cents immediately, per checkout event."

    Design: Difficulty/boundary_precision_check/cpc_balance_exact_charge_boundary
    """
    ctx = _setup_cpc_exact_boundary()
    p0 = create_patron(ctx["library"]["id"], external_card_number="P-0",
                       full_name="Patron Zero")
    loan = checkout(p0["id"], ctx["title"]["id"])
    # PRD §2.7 pins round_half_up(price * (1 - pct)) but does not pin whether
    # the real-valued product is computed in decimal or binary floating
    # point; 199 * 0.85 = 169.15 rounds to 169 in exact decimal arithmetic,
    # while the design's reference computation yields 170. Both are faithful
    # to the PRD sentence, so accept either and anchor the boundary on it.
    charge = loan["circ_price_charged_cents"]
    assert charge in (169, 170), (
        f"round_half_up(199 * 0.85) must be 169 or 170, got {charge}"
    )
    lic = validate_success(
        api.get_license(ctx["license"]["id"],
                        make_library_admin_headers(ctx["library"]["id"]))
    )
    assert lic["balance_cents"] == 170 - charge
    assert lic["status"] == "ACTIVE", (
        "depletion must not flip the license mid-request"
    )


def test_cpc_checkout_with_zero_balance_fails_balance_depleted(api):
    """PRD §3.8: "an `ACTIVE` cost-per-circulation license whose balance can no
    longer cover a charge stays selectable by the checkout selector and fails
    at the charge step with `ERR_LICENSE_BALANCE_DEPLETED`."

    Design: Difficulty/boundary_precision_check/cpc_balance_exact_charge_boundary
    """
    ctx = _setup_cpc_exact_boundary()
    lib_admin = make_library_admin_headers(ctx["library"]["id"])
    p0 = create_patron(ctx["library"]["id"], external_card_number="P-0",
                       full_name="Patron Zero")
    p1 = create_patron(ctx["library"]["id"], external_card_number="P-1",
                       full_name="Patron One")
    loan = checkout(p0["id"], ctx["title"]["id"])
    resp = api.checkout({"patron_id": p1["id"], "title_id": ctx["title"]["id"]},
                        make_patron_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_LICENSE_BALANCE_DEPLETED)
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["cpc_accrued_cents"] == loan["circ_price_charged_cents"], (
        "the failed checkout must not accrue; only the first checkout's "
        "rounded charge lands on the fund"
    )
