"""Corner queue: complexity-layer claims — optimistic concurrency on
sell-down, derived-field reconciliation on transfer execution, and the
negotiation TTL scheduled transition.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_brand,
    create_item,
    create_negotiation_respond_payload,
    create_plant,
    create_product_transfer_payload,
    create_sell_down_payload,
    get_success_data,
    make_retailer_buyer_headers,
    record_pass_run,
    set_clock,
    setup_listed_item,
    setup_negotiation_terms_proposed,
    validate_error,
    validate_ok,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]
SCP = TEST_USERS["supply_chain_planner_headers"]


def test_occ_sell_down_stale_version_rejected_then_refresh_succeeds():
    """PRD §2.7: "If that value does not equal the item's current `version` at
    the moment the write is attempted — because another writer has since sold
    the item down, or a divestiture cascade has touched it — the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated."
    PRD §3.3: "A successful sell-down subtracts `units_sold` from
    `units_on_hand`, adds it to `units_sold_cumulative`, and increments the
    item's `version` by 1 — which is precisely what makes a concurrently-held
    `expected_item_version` go stale."

    Design: Corner/complexity_layers/occ_sell_down_stale_version_rejected_then_refresh_succeeds
    """
    _, _, item = setup_listed_item({"units_on_hand": 1000})
    v0 = item["version"]
    assert v0 == 1
    first = validate_ok(
        api_client.sell_down_item(item["id"], create_sell_down_payload(200, v0), SCP)
    )
    assert first["version"] == 2
    assert first["units_on_hand"] == 800
    # Replay with the now-stale expected version 1.
    resp_stale = api_client.sell_down_item(
        item["id"], create_sell_down_payload(200, v0), SCP
    )
    validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)
    # Refresh the observed version and resubmit: succeeds.
    third = validate_ok(
        api_client.sell_down_item(
            item["id"], create_sell_down_payload(200, first["version"]), SCP
        )
    )
    assert third["version"] == 3
    assert third["units_on_hand"] == 600


def test_derived_field_reconciliation_after_transfer_execute():
    """PRD §3.4: "A plant's load readouts are recomputed whenever an item is
    created, whenever an item is discontinued (at case finalization or through
    a divestiture cascade), and whenever an item's `primary_plant_id` changes
    through transfer execution."
    PRD §3.4: "When a `PASS` brings `consecutive_pass_count` to 2, the transfer
    auto-executes in the same request: ... both the source and the target plant
    recompute their `committed_units_per_quarter` and `utilization_pct`".

    Design: Corner/complexity_layers/derived_field_reconciliation_after_transfer_execute
    """
    brand = create_brand()
    source = create_plant(quarterly_capacity_units=100000)
    target = create_plant(quarterly_capacity_units=20000)
    item = create_item(brand["id"], source["id"], annual_units=40000,
                       unit_net_revenue_cents=2000, unit_cost_cents=1700,
                       units_on_hand=0)
    transfer = get_success_data(
        api_client.create_product_transfer(
            create_product_transfer_payload(item["id"], source["id"], target["id"]),
            SCP,
        )
    )
    # Pre-execution: the item counts at the SOURCE (10000 committed of 100000).
    plants_pre, _ = validate_paginated(api_client.list_plants(SCP))
    pre = {p["id"]: p for p in plants_pre}
    assert pre[source["id"]]["committed_units_per_quarter"] == 10000
    assert pre[source["id"]]["utilization_pct"] == 10.00
    assert pre[target["id"]]["committed_units_per_quarter"] == 0
    # Two consecutive PASS runs auto-execute the transfer.
    record_pass_run(transfer["id"], target["id"], run_date="2026-09-02T00:00:00Z")
    record_pass_run(transfer["id"], target["id"], run_date="2026-09-03T00:00:00Z")
    plants_post, _ = validate_paginated(api_client.list_plants(SCP))
    post = {p["id"]: p for p in plants_post}
    assert post[source["id"]]["committed_units_per_quarter"] == 0, (
        "the item's 10000 quarterly units must leave the source plant"
    )
    assert post[source["id"]]["utilization_pct"] == 0.00
    assert post[target["id"]]["committed_units_per_quarter"] == 10000, (
        "the item's 10000 quarterly units must arrive at the target plant"
    )
    assert post[target["id"]]["utilization_pct"] == 50.00


def test_scheduled_actions_negotiation_ttl_expiry():
    """PRD §3.6: "Once the logical clock is strictly later than `expires_at`,
    the respond attempt itself fails with `ERR_NEGOTIATION_EXPIRED` (HTTP 409)
    and the negotiation auto-transitions to `EXPIRED`, its `version` still
    incrementing."

    Design: Corner/complexity_layers/scheduled_actions_negotiation_ttl_expiry
    """
    retailer, _, negotiation = setup_negotiation_terms_proposed()
    # Created at the default clock 2026-09-01 -> expires 2026-10-01; the
    # clock 2026-10-02 is strictly later.
    set_clock("2026-10-02T00:00:00Z")
    resp = api_client.respond_to_negotiation(
        negotiation["id"],
        create_negotiation_respond_payload("ACCEPT"),
        make_retailer_buyer_headers(retailer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_EXPIRED)
    after = validate_ok(api_client.get_combined_negotiation(negotiation["id"], PM))
    assert after["negotiation_status"] == "EXPIRED", (
        "the failed respond must still fire the EXPIRED auto-transition"
    )
