"""Initial states, cross-entity side effects, the arrival fork and the two
absorbing axes.

PRD 3.9 forks arrival on the count rather than on the manifest: "When the counts
differ in either direction, the shipment moves `IN_TRANSIT` -> `EXCEPTION` instead,
`variance_minor_units` carries the signed difference and `exception_reason` is set
to `MANIFEST_VARIANCE`", and both branches "move only the notes that were actually
counted, never the notes the manifest claimed".  PRD 3.6 makes the compliance axis
absorbing at its two ends: "Any decision that does not satisfy its own precondition
- a decision on a row that is already `CLEARED` or `BLOCKED`, or a `FLAG` on a row
that is no longer `PENDING` - is refused with `ERR_COMPLIANCE_DECISION_FINAL`."
"""

from test_helpers import (
    OPERATORS,
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_every_machine_is_born_in_its_declared_initial_state(
    api, treasury_headers, manager_headers, teller_headers
):
    """One freshly created row per machine sits exactly where its declaration puts
    it: card DRAFT with a null published_at, plan DRAFT with no revisions and no
    submitter, customer NORMAL at score 0, deal QUOTED on one axis and PENDING on the
    other with a 15-minute quote deadline, shipment REQUESTED with no route or window
    and a manually raised flag, and the branch OPEN at 109 basis points.

    Design: Corner/state_machines/initial_states_across_all_state_machines
    """
    branch = fx.register_branch(api)
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    position = fx.open_position(api, branch["id"], "EUR", [f.denom(10000, 20)])
    corridor = fx.register_corridor(
        api,
        code="LHR-CDG",
        destination_country_code="FR",
        destination_currency_code="EUR",
        season="SUMMER",
        season_start_date="2026-06-01T00:00:00Z",
        season_end_date="2026-09-30T00:00:00Z",
        demand_index_bps=12000,
    )

    card = fx.draft_rate_card(api, branch["id"], wholesale["id"])
    assert card["status"] == "DRAFT"
    assert card["published_at"] is None

    plan = fx.draft_plan(api, branch["id"], corridor["id"], season_days=92)
    a.assert_inventory_plan(plan)
    assert plan["status"] == "DRAFT"
    assert plan["revision_count"] == 0
    assert plan["submitted_by_user_id"] is None
    assert plan["target_lines"] == []
    assert plan["computed_targets"] == []

    customer = fx.onboard_customer(api, home_branch_id=branch["id"])
    a.assert_customer(customer)
    assert customer["structuring_risk_tier"] == "NORMAL"
    assert customer["structuring_risk_score"] == 0
    assert customer["compliance_hold_active"] is False
    assert customer["version"] == 1

    fx.publish_rate_card(api, card["id"])
    deal = validate_success(
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
    a.assert_exchange_transaction(deal)
    assert deal["settlement_status"] == "QUOTED"
    assert deal["compliance_status"] == "PENDING"
    assert deal["settled_usd_gross_cents"] is None
    a.assert_timestamp_equals(deal["quote_expires_at"], "2026-08-01T00:15:00Z")

    shipment = fx.raise_shipment(
        api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 4)]
    )
    a.assert_cash_shipment(shipment)
    assert shipment["status"] == "REQUESTED"
    assert shipment["auto_generated"] is False
    assert shipment["armored_route_id"] is None
    assert shipment["window_start"] is None
    assert shipment["window_end"] is None
    assert shipment["manifest_usd_equivalent_cents"] == 43478

    a.assert_vault_state(fx.read_branch(api, branch["id"]), 217391, 109, "OPEN")

    opened = fx.read_position(api, position["id"])
    assert opened["status"] == "OPEN"
    assert opened["total_minor_units"] == 200000
    assert opened["usd_equivalent_cents"] == 217391


def test_confiscation_writes_three_entities_in_one_call(
    api, teller_headers, teller2_headers, manager_headers, compliance_headers
):
    """One CONFISCATED assessment moves a note from quarantined to written off
    without touching the available count or the position total, raises a DRAFT
    COUNTERFEIT_SEIZURE report pointing back at the assessment, and flips the cited
    deal's compliance axis to FLAGGED while its settlement axis stays SETTLED.

    Design: Corner/state_machines/counterfeit_confiscation_cross_entity_side_effects
    """
    world = fx.trading_world(api, identified=False)
    txn = fx.settled_deal(
        api,
        world,
        "BUY_FX_FROM_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    assessment = fx.detain_notes(
        api,
        world["branch"]["id"],
        world["position"]["id"],
        txn["id"],
        10000,
        1,
        "SUSPECTED_COUNTERFEIT",
        teller_headers,
        serial_reference="X12345",
    )

    assessed = fx.assess_notes(
        api, assessment["id"], "CONFISCATED", "no UV thread", manager_headers
    )

    a.assert_note_assessment(assessed)
    assert assessed["status"] == "ASSESSED"
    assert assessed["outcome"] == "CONFISCATED"
    assert assessed["recovery_usd_cents"] is None
    assert assessed["assessed_by_user_id"] == OPERATORS["MANAGER"]

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=21, quarantined=0, written_off=1)
    assert position["total_minor_units"] == 210000
    assert position["quarantined_minor_units"] == 0
    assert position["usd_equivalent_cents"] == 228261

    rows, meta = validate_paginated(api.list_compliance_reports(compliance_headers))
    assert meta["total_count"] == 1
    report = rows[0]
    a.assert_compliance_report(report)
    assert report["report_type"] == "COUNTERFEIT_SEIZURE"
    assert report["status"] == "DRAFT"
    assert report["note_assessment_id"] == assessment["id"]
    assert report["customer_id"] == world["customer"]["id"]
    assert report["filing_reference"] is None

    final = fx.read_transaction(api, txn["id"])
    assert final["compliance_status"] == "FLAGGED"
    assert final["settlement_status"] == "SETTLED"


def test_returned_and_discounted_damage_resolve_the_same_defect_two_ways(
    api, teller_headers, teller2_headers, manager_headers, compliance_headers
):
    """RETURNED lets the notes leave the branch - the total stays at its
    post-quarantine 170000, recovery stays null and no report is raised - while
    EXCHANGED_AT_DISCOUNT puts the same five notes back into stock, restoring the
    total from 120000 to 170000 and paying 33485 cents under the pinned two-step
    rounding.

    Design: Corner/state_machines/returned_versus_discount_outcome_conditional_cascade
    """
    world = fx.trading_world(
        api,
        currency_payload=f.create_currency_payload(damaged_note_recovery_bps=6500),
        identified=False,
    )
    txn = fx.settled_deal(
        api,
        world,
        "BUY_FX_FROM_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    first = fx.detain_notes(
        api,
        world["branch"]["id"],
        world["position"]["id"],
        txn["id"],
        10000,
        5,
        "DAMAGED",
        teller_headers,
    )

    returned = fx.assess_notes(
        api,
        first["id"],
        "RETURNED",
        "returned to issuing central bank",
        manager_headers,
    )
    assert returned["recovery_usd_cents"] is None

    after_return = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(after_return)
    a.assert_mix_counts(after_return, 10000, available=17, quarantined=0, written_off=0)
    assert after_return["total_minor_units"] == 170000
    assert after_return["usd_equivalent_cents"] == 184783

    _, empty_meta = validate_paginated(api.list_compliance_reports(compliance_headers))
    assert empty_meta["total_count"] == 0

    second = fx.detain_notes(
        api,
        world["branch"]["id"],
        world["position"]["id"],
        txn["id"],
        10000,
        5,
        "DAMAGED",
        teller_headers,
    )
    quarantined = fx.read_position(api, world["position"]["id"])
    a.assert_mix_counts(quarantined, 10000, available=12, quarantined=5)
    assert quarantined["total_minor_units"] == 120000
    assert quarantined["usd_equivalent_cents"] == 130435

    discounted = fx.assess_notes(
        api,
        second["id"],
        "EXCHANGED_AT_DISCOUNT",
        "torn corner, redeemable",
        manager_headers,
    )

    a.assert_note_assessment(discounted)
    assert discounted["recovery_usd_cents"] == 33485

    restored = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(restored)
    a.assert_mix_counts(restored, 10000, available=17, quarantined=0)
    assert restored["total_minor_units"] == 170000
    assert restored["usd_equivalent_cents"] == 184783

    branch = fx.read_branch(api, world["branch"]["id"])
    a.assert_vault_state(branch, 184783, 92, "OPEN")


def test_short_delivery_forks_to_exception_and_joins_on_reconciled(
    api, treasury_headers, manager_headers
):
    """Three notes counted off a four-note manifest send the shipment to EXCEPTION
    with a 10000-unit variance and MANIFEST_VARIANCE, credit only the three notes that
    actually arrived, leave the branch OPEN with no automatic repatriation, and the
    join transition writes the variance off rather than zero.

    Design: Corner/state_machines/shipment_exception_fork_and_join_on_reconciled
    """
    branch = fx.register_branch(api)
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    route = fx.register_route(
        api,
        code="RT-SOUTH-1",
        carrier_name="SecurCash",
        region_code="SOUTH",
        daily_capacity_usd_cents=200000,
    )
    position = fx.open_position(api, branch["id"], "EUR", [f.denom(10000, 20)])
    shipment = fx.raise_shipment(
        api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 4)]
    )
    fx.schedule_shipment(
        api, shipment["id"], route["id"], "2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"
    )
    fx.set_clock(api, "2026-08-05T09:30:00Z")
    fx.dispatch_shipment(api, shipment["id"])

    arrived = validate_success(
        api.arrive_cash_shipment(
            shipment["id"], f.arrive_payload([f.denom(10000, 3)]), manager_headers
        )
    )

    a.assert_cash_shipment(arrived)
    assert arrived["status"] == "EXCEPTION"
    assert arrived["delivered_minor_units"] == 30000
    assert arrived["variance_minor_units"] == 10000
    assert arrived["exception_reason"] == "MANIFEST_VARIANCE"

    credited = fx.read_position(api, position["id"])
    a.assert_position_mix_invariants(credited)
    a.assert_mix_counts(credited, 10000, available=23)
    assert credited["total_minor_units"] == 230000
    assert credited["usd_equivalent_cents"] == 250000

    branch_now = fx.read_branch(api, branch["id"])
    a.assert_vault_state(branch_now, 250000, 125, "OPEN")

    reconciled = validate_success(
        api.reconcile_cash_shipment(shipment["id"], treasury_headers)
    )
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["written_off_minor_units"] == 10000

    _, meta = validate_paginated(api.list_cash_shipments(treasury_headers))
    assert meta["total_count"] == 1


def test_a_reversed_deal_refuses_every_further_settlement_trigger(
    api, teller_headers, teller2_headers, manager_headers
):
    """REVERSED is absorbing on the settlement axis: authorize, reverse and void all
    come back with their own from-state errors at 409, the row keeps its 22763-cent
    settled gross and 23560-cent total charge for audit, the position is back to its
    opening twenty notes and the customer's rolling window is empty again.

    Design: Corner/state_machines/reversed_transaction_is_locked_down
    """
    world = fx.trading_world(api, identified=False)
    txn = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    a.assert_settlement_money(txn, 22763, 797, 23560)
    reversed_txn = fx.reverse_deal(api, txn["id"], manager_headers, "teller error")
    assert reversed_txn["settlement_status"] == "REVERSED"

    validate_error(
        api.authorize_transaction(txn["id"], teller_headers),
        ApiErrorId.ERR_TRANSACTION_NOT_QUOTED,
        409,
    )
    validate_error(
        api.reverse_transaction(txn["id"], f.reverse_payload("again"), manager_headers),
        ApiErrorId.ERR_TRANSACTION_NOT_SETTLED,
        409,
    )
    validate_error(
        api.void_transaction(txn["id"], f.void_payload("again"), teller_headers),
        ApiErrorId.ERR_TRANSACTION_NOT_VOIDABLE,
        409,
    )

    final = fx.read_transaction(api, txn["id"])
    assert final["settlement_status"] == "REVERSED"
    assert final["settled_usd_gross_cents"] == 22763
    assert final["settled_total_charge_cents"] == 23560

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=20)
    assert position["total_minor_units"] == 200000
    assert position["usd_equivalent_cents"] == 217391

    customer = fx.read_customer(api, world["customer"]["id"])
    assert customer["rolling_30d_settled_usd_cents"] == 0
    assert customer["structuring_risk_tier"] == "NORMAL"


def test_cleared_and_blocked_absorb_the_compliance_axis_but_flagged_does_not(
    api, teller_headers, compliance_headers
):
    """One deal cleared straight out of PENDING refuses a later BLOCK, another walks
    PENDING to FLAGGED to BLOCKED and then refuses a CLEAR, both with
    ERR_COMPLIANCE_DECISION_FINAL at 409 - and no decision on either axis moves a
    single note out of the position.

    Design: Corner/state_machines/compliance_decision_axis_transitions_and_finality
    """
    world = fx.trading_world(api, identified=False)
    first = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    second = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )

    cleared = fx.decide_compliance(
        api, first["id"], "CLEAR", "known customer", compliance_headers
    )
    assert cleared["compliance_status"] == "CLEARED"
    assert cleared["settlement_status"] == "QUOTED"

    validate_error(
        api.compliance_decision(
            first["id"],
            f.compliance_decision_payload("BLOCK", "second thoughts"),
            compliance_headers,
        ),
        ApiErrorId.ERR_COMPLIANCE_DECISION_FINAL,
        409,
    )
    assert fx.read_transaction(api, first["id"])["compliance_status"] == "CLEARED"

    flagged = fx.decide_compliance(
        api, second["id"], "FLAG", "watchlist near-match", compliance_headers
    )
    assert flagged["compliance_status"] == "FLAGGED"

    blocked = fx.decide_compliance(
        api, second["id"], "BLOCK", "confirmed match", compliance_headers
    )
    assert blocked["compliance_status"] == "BLOCKED"

    validate_error(
        api.compliance_decision(
            second["id"],
            f.compliance_decision_payload("CLEAR", "appeal"),
            compliance_headers,
        ),
        ApiErrorId.ERR_COMPLIANCE_DECISION_FINAL,
        409,
    )
    assert fx.read_transaction(api, second["id"])["compliance_status"] == "BLOCKED"

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=20)
    assert position["total_minor_units"] == 200000
