"""The two cross-cutting layers: the version pins that guard the reserve-and-truncate
writes, and the immediate consistency of every derived field.

PRD 2.7 pins both retiring writes to a parent version - "If that value does not equal
the branch's current `version`, the request is rejected with
`ERR_STALE_BRANCH_VERSION` (HTTP 412)" and "If that value does not equal the
customer's current `version`, the request is rejected with
`ERR_STALE_CUSTOMER_VERSION` (HTTP 412)" - and both "reject a stale pin
deterministically rather than performing the retirement".  PRD 2.9 then fixes the
recomputation that a mutating response must already show: "first the affected
inventory position's `denomination_mix` note counts are adjusted; second that
position's `total_minor_units`, `quarantined_minor_units` and `usd_equivalent_cents`
are recomputed from the new mix; third the branch's `vault_usd_equivalent_cents` and
`vault_utilization_bps` are recomputed from the position totals; and fourth the
branch's `posture` is re-derived".
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


def test_both_version_pins_reject_a_stale_token_without_retiring_anything(
    api, treasury_headers, teller_headers, teller2_headers
):
    """A position create moves the branch to version 2, so a rate-card token captured
    at creation is stale and dies with ERR_STALE_BRANCH_VERSION at 412 having created
    no card; an APPLY and a RELEASE move the customer two versions on, so a buy-back
    token captured after settlement dies with ERR_STALE_CUSTOMER_VERSION at 412 having
    left the origin's buyback_contract_id null - and both retries then succeed.

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_both_rules_enforce_expected_parent_version
    """
    branch = fx.register_branch(api)
    assert branch["version"] == 1
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    position = fx.open_position(api, branch["id"], "EUR", [f.denom(10000, 20)])

    validate_error(
        api.create_rate_card(
            f.create_rate_card_payload(branch["id"], wholesale["id"], branch["version"]),
            treasury_headers,
        ),
        ApiErrorId.ERR_STALE_BRANCH_VERSION,
        412,
    )
    assert fx.branch_version(api, branch["id"]) == 2
    _, no_cards = validate_paginated(
        api.list_rate_cards(treasury_headers, {"branch_id": branch["id"]})
    )
    assert no_cards["total_count"] == 0

    card = validate_success(
        api.create_rate_card(
            f.create_rate_card_payload(branch["id"], wholesale["id"], 2), treasury_headers
        ),
        201,
    )
    assert card["status"] == "DRAFT"
    assert fx.branch_version(api, branch["id"]) == 3
    published = fx.publish_rate_card(api, card["id"])
    assert published["status"] == "PUBLISHED"
    _, one_card = validate_paginated(
        api.list_rate_cards(treasury_headers, {"branch_id": branch["id"]})
    )
    assert one_card["total_count"] == 1

    customer = fx.onboard_customer(api, home_branch_id=branch["id"])
    assert customer["version"] == 1
    before_settlement = fx.branch_version(api, branch["id"])
    quoted = validate_success(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch["id"],
                customer["id"],
                card["id"],
                "EUR",
                "SELL_FX_TO_CUSTOMER",
                [f.denom(10000, 2)],
            ),
            teller_headers,
        ),
        201,
    )
    fx.authorize_deal(api, quoted["id"], teller_headers)
    txn = fx.settle_deal(api, quoted["id"], teller2_headers)
    a.assert_settlement_money(txn, 22763, 797, 23560)
    assert fx.branch_version(api, branch["id"]) == before_settlement + 1

    stale_customer_pin = fx.customer_version(api, customer["id"])
    assert stale_customer_pin == 2
    assert fx.apply_hold(api, customer["id"], "spot check")["version"] == 3
    released = fx.release_hold(api, customer["id"], "cleared")
    assert released["compliance_hold_active"] is False
    assert released["version"] == 4

    validate_error(
        api.create_buyback_contract(
            f.create_buyback_contract_payload(
                customer["id"], txn["id"], stale_customer_pin
            ),
            teller_headers,
        ),
        ApiErrorId.ERR_STALE_CUSTOMER_VERSION,
        412,
    )
    assert fx.read_transaction(api, txn["id"])["buyback_contract_id"] is None
    _, no_contracts = validate_paginated(api.list_buyback_contracts(teller_headers))
    assert no_contracts["total_count"] == 0
    assert fx.customer_version(api, customer["id"]) == 4

    contract = fx.issue_contract(api, customer["id"], txn["id"], 4, teller_headers)
    a.assert_buyback_contract(contract)
    assert contract["status"] == "ISSUED"
    assert contract["fee_usd_cents"] == 683
    assert contract["liability_usd_cents"] == 20606
    assert fx.customer_version(api, customer["id"]) == 5
    assert fx.read_transaction(api, txn["id"])["buyback_contract_id"] == contract["id"]

    untouched = fx.read_position(api, position["id"])
    a.assert_position_mix_invariants(untouched)
    a.assert_mix_counts(untouched, 10000, available=18)
    assert untouched["total_minor_units"] == 180000


def test_the_settle_response_and_the_next_reads_already_agree(
    api, manager_headers, teller_headers, teller2_headers, compliance_headers
):
    """The settle body is authoritative on its own - 30909 gross, 773 commission,
    30136 paid out, SETTLED at the clock - and the very first read of the position,
    the branch and the customer already carries the recomputed 80000 / 86957 / 8696
    and the score of 1, with no report raised and no drift when every row is read a
    second time.

    Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_current_in_the_same_response
    """
    branch = fx.register_branch(
        api,
        code="BR-DOV",
        name="Dover Ferry Terminal",
        vault_limit_usd_cents=100_000,
    )
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    card = fx.published_rate_card(
        api, branch["id"], wholesale["id"], board_display_label="EUR Euro"
    )
    position = fx.open_position(api, branch["id"], "EUR", [f.denom(10000, 5)])
    assert position["total_minor_units"] == 50000
    assert position["usd_equivalent_cents"] == 54348
    a.assert_vault_state(fx.read_branch(api, branch["id"]), 54348, 5435, "OPEN")

    customer = fx.onboard_customer(
        api, full_name="Ivo Karlsson", nationality_code="SE", home_branch_id=branch["id"]
    )
    quoted = validate_success(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                branch["id"],
                customer["id"],
                card["id"],
                "EUR",
                "BUY_FX_FROM_CUSTOMER",
                [f.denom(10000, 3)],
            ),
            teller_headers,
        ),
        201,
    )
    authorized = fx.authorize_deal(api, quoted["id"], teller_headers)
    assert authorized["settlement_status"] == "AUTHORIZED"

    settled = validate_success(api.settle_transaction(quoted["id"], teller2_headers))
    a.assert_exchange_transaction(settled)
    a.assert_settlement_money(settled, 30909, 773, 30136)
    assert settled["settlement_status"] == "SETTLED"
    a.assert_timestamp_equals(settled["settled_at"], CLOCK_START)

    first_position = validate_success(
        api.get_inventory_position(position["id"], manager_headers)
    )
    a.assert_position_mix_invariants(first_position)
    a.assert_mix_counts(first_position, 10000, available=8)
    assert first_position["total_minor_units"] == 80000
    assert first_position["usd_equivalent_cents"] == 86957

    first_branch = validate_success(api.get_branch(branch["id"], manager_headers))
    a.assert_vault_state(first_branch, 86957, 8696, "OPEN")

    first_customer = validate_success(api.get_customer(customer["id"], teller_headers))
    a.assert_customer(first_customer)
    assert first_customer["rolling_30d_settled_usd_cents"] == 30909
    assert first_customer["calendar_month_settled_usd_cents"] == 30909
    assert first_customer["near_threshold_txn_count"] == 0
    assert first_customer["distinct_branch_count"] == 1
    assert first_customer["structuring_risk_score"] == 1
    assert first_customer["structuring_risk_tier"] == "NORMAL"
    assert first_customer["compliance_hold_active"] is False

    _, reports_meta = validate_paginated(
        api.list_compliance_reports(
            compliance_headers, {"triggering_transaction_id": quoted["id"]}
        )
    )
    assert reports_meta["total_count"] == 0

    assert (
        validate_success(api.get_inventory_position(position["id"], manager_headers))
        == first_position
    )
    assert validate_success(api.get_branch(branch["id"], manager_headers)) == first_branch
    assert (
        validate_success(api.get_customer(customer["id"], teller_headers))
        == first_customer
    )
    assert validate_success(api.get_exchange_transaction(quoted["id"], teller_headers)) == settled
