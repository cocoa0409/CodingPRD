"""Chains where the last consequence is invisible from the triggering request.

PRD 2.9 and PRD 3.9: a delivery folds notes into the position, recomputes the
position totals, recomputes the branch vault figures, re-derives the posture, and
"a posture that has become RESTRICTED or FROZEN raises an automatic REPATRIATION
shipment".  PRD 3.5 and PRD 3.6: a settlement recomputes the customer's aggregates,
re-derives the score and tier, emits a structuring report on arrival at HIGH, and
"the creation of that report - not the settlement itself - sets
compliance_hold_active to true".
"""

from test_helpers import (
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)


def _tight_vault_branch(api):
    """BR-CDG with a 400000-cent ceiling, an EUR line, a southern route, and a
    position of 30 x 10000 notes that leaves the branch OPEN at 8152 bps."""
    branch = fx.register_branch(api, code="BR-CDG", name="Paris CDG", vault_limit_usd_cents=400_000)
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    route = fx.register_route(api, daily_capacity_usd_cents=200_000)
    position = fx.open_position(api, branch["id"], "EUR", [f.denom(10000, 30)])
    before = fx.read_branch(api, branch["id"])
    a.assert_vault_state(before, 326087, 8152, "OPEN")
    return {"branch": branch, "route": route, "position": position}


def _delivered_replenishment(api, world, note_count=4):
    """Raise, schedule, dispatch and deliver a REPLENISHMENT of 10000-unit notes."""
    shipment = fx.raise_shipment(
        api,
        world["branch"]["id"],
        "EUR",
        "REPLENISHMENT",
        [f.denom(10000, note_count)],
    )
    fx.schedule_shipment(
        api,
        shipment["id"],
        world["route"]["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
    )
    fx.set_clock(api, "2026-08-05T09:00:00Z")
    fx.dispatch_shipment(api, shipment["id"])
    return fx.arrive_shipment(api, shipment["id"], [f.denom(10000, note_count)])


def test_arrival_walks_position_totals_branch_vault_and_posture(api, treasury_headers):
    """Delivering 4 x 10000 EUR notes with no variance lifts the position to 34
    notes and 340000 minor units worth 369565 cents, republishes the branch vault at
    369565 cents and 9239 bps, and flips the posture from OPEN to RESTRICTED.

    Design: Difficulty/transitive_cascade/shipment_arrival_five_hop_cascade_to_auto_repatriation_manifest
    """
    world = _tight_vault_branch(api)

    delivered = _delivered_replenishment(api, world)

    a.assert_cash_shipment(delivered)
    assert delivered["status"] == "DELIVERED"
    assert delivered["variance_minor_units"] == 0
    assert delivered["manifest_usd_equivalent_cents"] == 43478

    position = fx.read_position(api, world["position"]["id"], treasury_headers)
    a.assert_mix_counts(position, 10000, available=34)
    assert position["total_minor_units"] == 340000
    assert position["usd_equivalent_cents"] == 369565

    branch = fx.read_branch(api, world["branch"]["id"], treasury_headers)
    a.assert_vault_state(branch, 369565, 9239, "RESTRICTED")
    a.assert_branch_posture_band(branch)


def test_the_restricted_posture_raises_an_automatic_repatriation_with_a_waterfall_manifest(
    api, treasury_headers
):
    """The fifth hop is not predictable from the arriving shipment: the RESTRICTED
    posture emits one auto_generated REPATRIATION shipment sitting in REQUESTED whose
    surplus manifest is 2 x 10000 notes - 20000 minor units worth 21739 cents - and
    marks the branch repatriation_pending.

    Design: Difficulty/transitive_cascade/shipment_arrival_five_hop_cascade_to_auto_repatriation_manifest
    """
    world = _tight_vault_branch(api)

    _delivered_replenishment(api, world)

    repatriation = fx.auto_repatriation_shipment(api, world["branch"]["id"])
    a.assert_cash_shipment(repatriation)
    assert repatriation["direction"] == "REPATRIATION"
    assert repatriation["status"] == "REQUESTED"
    assert repatriation["auto_generated"] is True
    assert repatriation["branch_id"] == world["branch"]["id"]
    a.assert_denomination_entries(
        repatriation["manifest_denominations"], [f.denom(10000, 2)]
    )
    assert repatriation["manifest_minor_units"] == 20000
    assert repatriation["manifest_usd_equivalent_cents"] == 21739

    branch = fx.read_branch(api, world["branch"]["id"], treasury_headers)
    assert branch["repatriation_pending"] is True


def _two_branch_surveillance_world(api):
    """Two 20,000,000-cent branches, each with a published EUR card off one mid and
    100 x 10000 notes, plus one customer holding an unexpired passport."""
    south = fx.register_branch(api)
    north = fx.register_branch(api, code="BR-CDG", name="Paris CDG", region_code="NORTH")
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    south_card = fx.published_rate_card(api, south["id"], wholesale["id"])
    north_card = fx.published_rate_card(api, north["id"], wholesale["id"])
    south_position = fx.open_position(api, south["id"], "EUR", [f.denom(10000, 100)])
    north_position = fx.open_position(api, north["id"], "EUR", [f.denom(10000, 100)])
    customer = fx.identified_customer(
        api,
        full_name="Elif Demir",
        nationality_code="TR",
        id_document_number="TR-4410",
        id_document_expiry="2027-01-01T00:00:00Z",
    )
    return {
        "south": {"branch": south, "card": south_card, "position": south_position},
        "north": {"branch": north, "card": north_card, "position": north_position},
        "customer": customer,
    }


def _settle_80_notes(api, world, side, teller_headers, manager_headers):
    """One 80 x 10000 EUR sale under dual control at the named branch."""
    txn = validate_success(
        api.create_exchange_transaction(
            f.create_exchange_transaction_payload(
                world[side]["branch"]["id"],
                world["customer"]["id"],
                world[side]["card"]["id"],
                requested_denominations=[f.denom(10000, 80)],
            ),
            teller_headers,
        ),
        201,
    )
    validate_success(api.authorize_transaction(txn["id"], teller_headers))
    return validate_success(api.settle_transaction(txn["id"], manager_headers))


def test_one_settlement_alone_leaves_the_customer_elevated_with_no_report(
    api, teller_headers, manager_headers, compliance_headers
):
    """The first 910539-cent settlement is the shallow end of the chain: aggregates
    of 910539 over one near-threshold deal at one branch, a score of 47, the
    ELEVATED tier, no structuring report and no compliance hold.

    Design: Difficulty/transitive_cascade/settlement_four_hop_cascade_to_structuring_report_and_customer_hold
    """
    world = _two_branch_surveillance_world(api)

    first = _settle_80_notes(api, world, "south", teller_headers, manager_headers)
    assert first["settled_usd_gross_cents"] == 910539

    customer = fx.read_customer(api, world["customer"]["id"], compliance_headers)
    a.assert_customer(customer)
    assert customer["rolling_30d_settled_usd_cents"] == 910539
    assert customer["near_threshold_txn_count"] == 1
    assert customer["distinct_branch_count"] == 1
    assert customer["structuring_risk_score"] == 47
    assert customer["structuring_risk_tier"] == "ELEVATED"
    assert customer["compliance_hold_active"] is False

    _, meta = validate_paginated(
        api.list_compliance_reports(
            compliance_headers,
            {"customer_id": world["customer"]["id"], "report_type": "STRUCTURING_SUSPICION"},
        )
    )
    assert meta["total_count"] == 0


def test_the_second_settlement_runs_aggregates_score_tier_report_and_hold(
    api, teller_headers, manager_headers, compliance_headers
):
    """The second 910539-cent settlement at the other branch walks all four hops:
    aggregates 1821078 over 2 near-threshold deals at 2 branches, score 74, tier HIGH,
    one DRAFT STRUCTURING_SUSPICION report pointing at this deal, and the hold raised
    by that report - while the deal itself pays 13658 cents of commission.

    Design: Difficulty/transitive_cascade/settlement_four_hop_cascade_to_structuring_report_and_customer_hold
    """
    world = _two_branch_surveillance_world(api)
    _settle_80_notes(api, world, "south", teller_headers, manager_headers)

    second = _settle_80_notes(api, world, "north", teller_headers, manager_headers)

    assert second["settlement_status"] == "SETTLED"
    assert second["settled_usd_gross_cents"] == 910539
    assert second["settled_commission_cents"] == 13658

    customer = fx.read_customer(api, world["customer"]["id"], compliance_headers)
    assert customer["rolling_30d_settled_usd_cents"] == 1821078
    assert customer["near_threshold_txn_count"] == 2
    assert customer["distinct_branch_count"] == 2
    assert customer["structuring_risk_score"] == 74
    assert customer["structuring_risk_tier"] == "HIGH"
    assert customer["compliance_hold_active"] is True

    rows, meta = validate_paginated(
        api.list_compliance_reports(
            compliance_headers,
            {"customer_id": world["customer"]["id"], "report_type": "STRUCTURING_SUSPICION"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "DRAFT"
    assert rows[0]["triggering_transaction_id"] == second["id"]

    north_position = fx.read_position(api, world["north"]["position"]["id"])
    assert north_position["total_minor_units"] == 200000
