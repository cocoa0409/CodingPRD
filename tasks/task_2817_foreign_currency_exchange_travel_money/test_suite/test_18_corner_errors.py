"""Four refusals whose interest is the exact reach of the rule: which endpoints a
non-ACTIVE branch, a compliance hold and a BLOCKED compliance status actually gate,
and which instant each rate-card gate reads.

PRD 2.8 rank 7 confines the administrative-status check to four write paths: the
branch's "administrative `status` must be `ACTIVE` on `POST /exchange-transactions`,
`POST /exchange-transactions/{id}/authorize`, `POST /rate-cards` and
`POST /inventory-plans`, otherwise `ERR_BRANCH_NOT_ACTIVE`".  Rank 8 pins the other
two reaches: "`compliance_hold_active` on the customer must be false on both
`POST /exchange-transactions/{id}/authorize` and `POST /buyback-contracts`" and "a
transaction's `compliance_status` must not be `BLOCKED` on both
`POST /exchange-transactions/{id}/settle` and `POST /exchange-transactions/{id}/reverse`".
Rank 12 makes the window check instant-dependent: "The instant read is the logical
clock at quote time and `authorized_at` at settlement time."
"""

from test_helpers import (
    CLOCK_START,
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_non_active_branch_refuses_only_its_four_declared_write_paths(
    api, treasury_headers, manager_headers, teller_headers
):
    """A SUSPENDED branch refuses a rate card and a CLOSED branch refuses a stocking
    plan, both with ERR_BRANCH_NOT_ACTIVE at 409 and both leaving no row and no
    version bump behind - yet the same suspended branch still opens a 54348-cent
    position and still on-boards a customer, because neither endpoint is in the rule's
    reach.

    Design: Corner/errors/non_active_branch_status_rejects_only_its_four_declared_write_paths
    """
    suspended = fx.register_branch(
        api,
        code="BR-SUS",
        name="Gatwick North (suspended)",
        region_code="SOUTH",
        vault_limit_usd_cents=20_000_000,
        status="SUSPENDED",
    )
    closed = fx.register_branch(
        api,
        code="BR-CLO",
        name="Croydon (closed)",
        region_code="SOUTH",
        vault_limit_usd_cents=20_000_000,
        status="CLOSED",
    )
    assert suspended["status"] == "SUSPENDED"
    assert closed["status"] == "CLOSED"
    fx.register_currency(api)
    fx.register_currency(api, f.chf_currency_payload())
    wholesale = fx.record_wholesale_rate(api)
    corridor = fx.register_corridor(api)

    validate_error(
        api.create_rate_card(
            f.create_rate_card_payload(
                suspended["id"],
                wholesale["id"],
                suspended["version"],
                board_display_label="EUR Euro",
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_BRANCH_NOT_ACTIVE,
        409,
    )
    validate_error(
        api.create_inventory_plan(
            f.create_inventory_plan_payload(
                closed["id"], corridor["id"], 10, [f.target_line("CHF", 3000)]
            ),
            manager_headers,
        ),
        ApiErrorId.ERR_BRANCH_NOT_ACTIVE,
        409,
    )

    _, cards_meta = validate_paginated(api.list_rate_cards(treasury_headers))
    assert cards_meta["total_count"] == 0
    _, plans_meta = validate_paginated(api.list_inventory_plans(manager_headers))
    assert plans_meta["total_count"] == 0
    assert fx.read_branch(api, suspended["id"])["version"] == 1

    position = validate_success(
        api.create_inventory_position(
            f.create_inventory_position_payload(
                suspended["id"], "EUR", [f.denom(10000, 5)]
            ),
            manager_headers,
        ),
        201,
    )
    a.assert_inventory_position(position)
    assert position["total_minor_units"] == 50000
    assert position["usd_equivalent_cents"] == 54348

    still_suspended = fx.read_branch(api, suspended["id"])
    a.assert_vault_state(still_suspended, 54348, 27, "OPEN")
    assert still_suspended["status"] == "SUSPENDED"

    customer = validate_success(
        api.create_customer(
            f.create_customer_payload(
                full_name="Nia Adeyemi",
                nationality_code="GH",
                home_branch_id=suspended["id"],
            ),
            teller_headers,
        ),
        201,
    )
    a.assert_customer(customer)
    assert customer["home_branch_id"] == suspended["id"]
    assert customer["version"] == 1


def test_a_manual_hold_stops_authorisation_and_issuance_but_not_quoting(
    api, teller_headers, teller2_headers
):
    """A held customer still gets a fresh 11382-cent quote, but the authorisation of
    that quote and the buy-back issuance against their earlier settled sale both come
    back ERR_CUSTOMER_COMPLIANCE_HOLD at 409; the release lifts both refusals in one
    move and bumps the customer's version a second time.

    Design: Corner/errors/customer_compliance_hold_blocks_authorize_and_buyback_but_not_quoting
    """
    world = fx.trading_world(
        api,
        position_mix=[f.denom(10000, 20)],
        card_overrides={"board_display_label": "EUR Euro"},
        identified=False,
        customer_overrides={"full_name": "Nia Adeyemi", "nationality_code": "GH"},
    )
    customer_id = world["customer"]["id"]
    settled = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    a.assert_settlement_money(settled, 22763, 797, 23560)

    held = fx.apply_hold(api, customer_id, "adverse media match pending review")
    a.assert_customer(held)
    assert held["compliance_hold_active"] is True
    assert held["structuring_risk_tier"] == "NORMAL"
    held_version = held["version"]

    quoted = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    assert quoted["settlement_status"] == "QUOTED"
    assert quoted["quoted_usd_gross_cents"] == 11382
    assert fx.customer_version(api, customer_id) == held_version

    validate_error(
        api.authorize_transaction(quoted["id"], teller_headers),
        ApiErrorId.ERR_CUSTOMER_COMPLIANCE_HOLD,
        409,
    )
    unauthorized = fx.read_transaction(api, quoted["id"])
    assert unauthorized["settlement_status"] == "QUOTED"
    assert unauthorized["authorized_at"] is None

    validate_error(
        api.create_buyback_contract(
            f.create_buyback_contract_payload(customer_id, settled["id"], held_version),
            teller_headers,
        ),
        ApiErrorId.ERR_CUSTOMER_COMPLIANCE_HOLD,
        409,
    )

    released = fx.release_hold(api, customer_id, "false positive")
    assert released["compliance_hold_active"] is False
    assert released["version"] == held_version + 1

    authorized = fx.authorize_deal(api, quoted["id"], teller_headers)
    assert authorized["settlement_status"] == "AUTHORIZED"
    a.assert_timestamp_equals(authorized["authorized_at"], CLOCK_START)

    contract = fx.issue_contract(
        api, customer_id, settled["id"], headers=teller_headers
    )
    a.assert_buyback_contract(contract)
    assert contract["status"] == "ISSUED"
    assert contract["fee_usd_cents"] == 683
    assert contract["liability_usd_cents"] == 20606
    a.assert_timestamp_equals(contract["rate_lock_expires_at"], "2026-09-01T00:00:00Z")


def test_a_blocked_deal_can_neither_settle_nor_be_reversed(
    api, teller_headers, teller2_headers, manager_headers, compliance_headers
):
    """One BLOCKED decision after settlement and one before it bar the two axis-A
    moves on either side of settlement with the same ERR_TRANSACTION_COMPLIANCE_BLOCKED
    at 409, the eighteen notes the settled deal left behind neither return nor leave,
    and the still-unsettled row can nonetheless be voided.

    Design: Corner/errors/blocked_compliance_status_rejects_both_settle_and_reverse
    """
    world = fx.trading_world(
        api,
        position_mix=[f.denom(10000, 20)],
        card_overrides={"board_display_label": "EUR Euro"},
        identified=False,
        customer_overrides={"full_name": "Nia Adeyemi", "nationality_code": "GH"},
    )
    settled = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    a.assert_settlement_money(settled, 22763, 797, 23560)
    open_deal = fx.authorized_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 2)], teller_headers
    )
    assert open_deal["settlement_status"] == "AUTHORIZED"

    blocked_after = fx.decide_compliance(
        api,
        settled["id"],
        "BLOCK",
        "sanctions hit on settlement review",
        compliance_headers,
    )
    assert blocked_after["compliance_status"] == "BLOCKED"
    assert blocked_after["settlement_status"] == "SETTLED"

    flagged = fx.decide_compliance(
        api, open_deal["id"], "FLAG", "pending source-of-funds", compliance_headers
    )
    assert flagged["compliance_status"] == "FLAGGED"
    blocked_before = fx.decide_compliance(
        api,
        open_deal["id"],
        "BLOCK",
        "source of funds not evidenced",
        compliance_headers,
    )
    assert blocked_before["compliance_status"] == "BLOCKED"
    assert blocked_before["settlement_status"] == "AUTHORIZED"

    validate_error(
        api.reverse_transaction(
            settled["id"], f.reverse_payload("customer dispute"), manager_headers
        ),
        ApiErrorId.ERR_TRANSACTION_COMPLIANCE_BLOCKED,
        409,
    )
    frozen = fx.read_transaction(api, settled["id"])
    assert frozen["settlement_status"] == "SETTLED"
    assert frozen["reversed_at"] is None
    assert frozen["settled_usd_gross_cents"] == 22763

    validate_error(
        api.settle_transaction(open_deal["id"], teller2_headers),
        ApiErrorId.ERR_TRANSACTION_COMPLIANCE_BLOCKED,
        409,
    )
    stalled = fx.read_transaction(api, open_deal["id"])
    assert stalled["settlement_status"] == "AUTHORIZED"
    assert stalled["settled_at"] is None
    assert stalled["settled_usd_gross_cents"] is None
    assert stalled["settled_commission_cents"] is None

    validate_error(
        api.compliance_decision(
            open_deal["id"],
            f.compliance_decision_payload("CLEAR", "appeal"),
            compliance_headers,
        ),
        ApiErrorId.ERR_COMPLIANCE_DECISION_FINAL,
        409,
    )

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=18)
    assert position["total_minor_units"] == 180000

    voided = validate_success(
        api.void_transaction(
            open_deal["id"], f.void_payload("blocked, will not proceed"), teller_headers
        )
    )
    assert voided["settlement_status"] == "VOIDED"
    assert voided["compliance_status"] == "BLOCKED"

    unchanged = fx.read_position(api, world["position"]["id"])
    a.assert_mix_counts(unchanged, 10000, available=18)
    assert unchanged["total_minor_units"] == 180000


def test_the_two_card_gates_read_a_different_instant_on_each_endpoint(
    api, teller_headers, teller2_headers
):
    """A DRAFT card is refused for publication reasons while its window is wide open,
    the same EUR card that has just fallen out of its window refuses a fresh quote yet
    still settles the deal authorised inside it, and the redemption of the buy-back
    written on that settlement is refused again because redemption prices at the clock.

    Design: Corner/errors/rate_card_publication_and_window_gates_at_quote_settle_and_redeem
    """
    world = fx.trading_world(
        api,
        position_mix=[f.denom(10000, 20)],
        card_overrides={
            "board_display_label": "EUR Euro",
            "effective_to": "2026-08-01T00:05:00Z",
        },
        identified=False,
        customer_overrides={"full_name": "Nia Adeyemi", "nationality_code": "GH"},
    )
    branch_id = world["branch"]["id"]
    customer_id = world["customer"]["id"]
    a.assert_timestamp_equals(world["card"]["effective_to"], "2026-08-01T00:05:00Z")

    fx.register_currency(api, f.chf_currency_payload(buyback_eligible=True))
    chf_rate = fx.record_wholesale_rate(
        api, currency_code="CHF", mid_rate_micros=912_345
    )
    chf_card = fx.draft_rate_card(
        api,
        branch_id,
        chf_rate["id"],
        currency_code="CHF",
        board_display_label="CHF Franc",
    )
    assert chf_card["status"] == "DRAFT"

    txn = fx.authorized_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 2)], teller_headers
    )
    a.assert_timestamp_equals(txn["authorized_at"], CLOCK_START)
    a.assert_timestamp_equals(txn["quote_expires_at"], "2026-08-01T00:15:00Z")

    validate_error(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch_id,
                customer_id,
                chf_card["id"],
                "CHF",
                "SELL_FX_TO_CUSTOMER",
                [f.denom(20000, 1)],
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_RATE_CARD_NOT_PUBLISHED,
        409,
    )

    fx.set_clock(api, "2026-08-01T00:10:00Z")

    validate_error(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch_id,
                customer_id,
                world["card"]["id"],
                "EUR",
                "SELL_FX_TO_CUSTOMER",
                [f.denom(10000, 1)],
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_RATE_CARD_NOT_EFFECTIVE,
        409,
    )

    settled = fx.settle_deal(api, txn["id"], teller2_headers)
    a.assert_settlement_money(settled, 22763, 797, 23560)
    a.assert_timestamp_equals(settled["settled_at"], "2026-08-01T00:10:00Z")

    contract = fx.issue_contract(
        api, customer_id, txn["id"], headers=teller_headers
    )
    a.assert_buyback_contract(contract)
    assert contract["status"] == "ISSUED"
    assert contract["liability_usd_cents"] == 20606
    a.assert_timestamp_equals(contract["rate_lock_expires_at"], "2026-09-01T00:10:00Z")

    validate_error(
        api.redeem_buyback_contract(
            contract["id"], f.redeem_payload([f.denom(10000, 1)]), teller_headers
        ),
        ApiErrorId.ERR_RATE_CARD_NOT_EFFECTIVE,
        409,
    )
    unredeemed = fx.read_contract(api, contract["id"])
    assert unredeemed["status"] == "ISSUED"
    assert unredeemed["remaining_fx_minor_units"] == 20000
    assert unredeemed["redemption_count"] == 0

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=18)
    assert position["total_minor_units"] == 180000
