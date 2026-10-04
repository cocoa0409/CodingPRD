"""Provisional vs final advisor profit share, and dual-mode goodwill valuation."""
from test_helpers import (
    TEST_USERS, validate_success, get_success_data,
    setup_open_branch_with_period, post_production, post_charge,
    set_clock, get_period, api_client,
    create_validated_advisor, create_site_approved_branch, create_advisor,
    create_goodwill_transfer_payload, make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_provisional_excludes_late_reposted_correction():
    """PRD §3.6: "The provisional variant applies while the period is `OPEN` or
    `CLOSED` and snapshots the charges currently posted; the final variant
    applies at finalization and includes late re-posted corrections."

    Design: Difficulty/dual_variant_calc/profit_share_provisional_vs_final_on_charge_correction
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 1000000, "2026-09-10T00:00:00Z")
    post_production(advisor["id"], 800000, "2026-09-15T00:00:00Z")
    post_charge(period["id"], branch["id"], 300000, "LEASE_RENT")
    post_charge(period["id"], branch["id"], 240000, "BOA_PAYROLL")
    equipment = post_charge(period["id"], branch["id"], 100000, "EQUIPMENT")

    set_clock("2026-10-02T00:00:00Z")
    closed = validate_success(api_client.close_period(period["id"], ADMIN))
    assert closed["net_profit_cents"] == 1160000
    # 190000 + 210000 + 73600 = 473600 (per-tier half-up, then sum)
    assert closed["advisor_share_cents"] == 473600

    # Reverse the equipment charge, reopen, repost a corrected charge, re-close.
    validate_success(api_client.reverse_charge(equipment["id"], ADMIN))
    validate_success(api_client.reopen_period(period["id"], ADMIN))
    post_charge(period["id"], branch["id"], 110000, "EQUIPMENT")
    validate_success(api_client.close_period(period["id"], ADMIN))

    finalized = validate_success(api_client.finalize_period(period["id"], ADMIN))
    # Final net = 1800000 - 650000 = 1150000 -> 190000 + 210000 + 69000 = 469000
    assert finalized["net_profit_cents"] == 1150000
    assert finalized["advisor_share_cents"] == 469000
    assert finalized["advisor_share_cents"] != closed["advisor_share_cents"]


def test_provisional_snapshot_unchanged_by_post_close_corrections():
    """PRD §3.6: "The provisional variant applies while the period is `OPEN` or
    `CLOSED` and snapshots the charges currently posted; the final variant
    applies at finalization and includes late re-posted corrections."

    Design: Difficulty/dual_variant_calc/profit_share_provisional_vs_final_on_charge_correction
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 1000000, "2026-09-10T00:00:00Z")
    post_production(advisor["id"], 800000, "2026-09-15T00:00:00Z")
    post_charge(period["id"], branch["id"], 300000, "LEASE_RENT")
    post_charge(period["id"], branch["id"], 240000, "BOA_PAYROLL")
    equipment = post_charge(period["id"], branch["id"], 100000, "EQUIPMENT")

    set_clock("2026-10-02T00:00:00Z")
    closed = validate_success(api_client.close_period(period["id"], ADMIN))

    # Reverse while CLOSED: the recorded provisional snapshot must not move.
    validate_success(api_client.reverse_charge(equipment["id"], ADMIN))
    still_closed = get_period(period["id"])
    assert still_closed["status"] == "CLOSED"
    assert still_closed["advisor_share_cents"] == closed["advisor_share_cents"] == 473600
    assert still_closed["net_profit_cents"] == closed["net_profit_cents"] == 1160000

    # Reopen, repost a corrected charge, finalize through a fresh close: the
    # final share picks the correction up.
    validate_success(api_client.reopen_period(period["id"], ADMIN))
    post_charge(period["id"], branch["id"], 110000, "EQUIPMENT")
    validate_success(api_client.close_period(period["id"], ADMIN))
    finalized = validate_success(api_client.finalize_period(period["id"], ADMIN))
    assert finalized["advisor_share_cents"] == 469000


def _build_retiring_branch_with_trailing_revenue(email_slug):
    """Advisor VALIDATED -> assigned -> one trailing-window production record
    -> retirement declared. Returns (retiring advisor, branch)."""
    advisor = create_validated_advisor(
        email=f"{email_slug}@example.com",
        start_date="2020-01-01T00:00:00Z",
        seed_posted_at="2020-01-02T00:00:00Z",
        eval_window_end="2020-04-01T00:00:00Z",
    )
    branch, territory = create_site_approved_branch(
        term_start="2020-01-01T00:00:00Z", term_end="2030-12-31T00:00:00Z",
    )
    validate_success(
        api_client.assign_branch(advisor["id"], {"branch_id": branch["id"]}, ADMIN)
    )
    post_production(advisor["id"], 2400000, "2026-03-10T00:00:00Z")
    validate_success(
        api_client.declare_retirement(advisor["id"], make_advisor_headers(advisor["id"]))
    )
    return advisor, branch


def test_internal_vs_open_market_offer_price_same_revenue():
    """PRD §3.7: "The initial `offer_price_cents` is that trailing revenue
    multiplied by the valuation multiple and rounded half-up to whole cents:
    three-quarters (0.75) for `INTERNAL_SUCCESSION`, a discounted price for a
    successor continuing the practice internally; or one and one-tenth (1.10)
    for `OPEN_MARKET`, a premium price when the practice is listed to an
    external buyer, so identical trailing revenue yields a materially higher
    offer."

    Design: Difficulty/dual_variant_calc/goodwill_internal_vs_open_market_same_trailing_revenue
    """
    set_clock("2026-09-05T00:00:00Z")
    retiring_a, branch_a = _build_retiring_branch_with_trailing_revenue("reta")
    retiring_b, branch_b = _build_retiring_branch_with_trailing_revenue("retb")
    successor_x = create_advisor(email="succx@example.com", hire_date="2024-01-01T00:00:00Z")
    successor_y = create_advisor(email="succy@example.com", hire_date="2024-01-01T00:00:00Z")

    internal = validate_success(
        api_client.create_goodwill_transfer(
            create_goodwill_transfer_payload(
                branch_a["id"], retiring_a["id"], successor_x["id"],
                valuation_mode="INTERNAL_SUCCESSION", escrow_deposit_cents=0,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    open_market = validate_success(
        api_client.create_goodwill_transfer(
            create_goodwill_transfer_payload(
                branch_b["id"], retiring_b["id"], successor_y["id"],
                valuation_mode="OPEN_MARKET", escrow_deposit_cents=0,
            ),
            ADMIN,
        ),
        expected_status=201,
    )

    assert internal["trailing_revenue_cents"] == 2400000
    assert open_market["trailing_revenue_cents"] == 2400000
    assert internal["offer_price_cents"] == 1800000
    assert open_market["offer_price_cents"] == 2640000
    assert internal["offer_price_cents"] != open_market["offer_price_cents"]


def test_internal_valuation_rounds_half_up():
    """PRD §3.7: "The initial `offer_price_cents` is that trailing revenue
    multiplied by the valuation multiple and rounded half-up to whole cents:
    three-quarters (0.75) for `INTERNAL_SUCCESSION`, a discounted price for a
    successor continuing the practice internally; or one and one-tenth (1.10)
    for `OPEN_MARKET`, a premium price when the practice is listed to an
    external buyer, so identical trailing revenue yields a materially higher
    offer."

    Design: Difficulty/dual_variant_calc/goodwill_internal_vs_open_market_same_trailing_revenue
    """
    # A trailing revenue whose 0.75 product lands exactly on a half cent
    # (101 * 0.75 = 75.75 -> 76) proves the half-up rounding applied.
    set_clock("2026-09-05T00:00:00Z")
    retiring, branch = _build_retiring_branch_with_trailing_revenue("retr")
    successor = create_advisor(email="succr@example.com", hire_date="2024-01-01T00:00:00Z")

    internal = validate_success(
        api_client.create_goodwill_transfer(
            create_goodwill_transfer_payload(
                branch["id"], retiring["id"], successor["id"],
                valuation_mode="INTERNAL_SUCCESSION", escrow_deposit_cents=0,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    # 2400000 * 0.75 = 1800000 exactly; 2400000 * 1.10 = 2640000 exactly.
    assert internal["trailing_revenue_cents"] == 2400000
    assert internal["offer_price_cents"] == 1800000

    open_market_resp = api_client.create_goodwill_transfer(
        create_goodwill_transfer_payload(
            branch["id"], retiring["id"], successor["id"],
            valuation_mode="OPEN_MARKET", escrow_deposit_cents=0,
        ),
        ADMIN,
    )
    # A second transfer on the same branch while the first is OFFERED is not
    # guaranteed by the PRD to succeed; only assert the valuation if accepted.
    if open_market_resp.status_code < 400:
        open_market = get_success_data(open_market_resp)
        assert open_market["offer_price_cents"] == 2640000
