"""Validation that reads another aggregate: the route row, the buy-back eligibility
triad, the defect/outcome matrix and the report that pins a compliance hold shut.

PRD 3.9 makes scheduling depend on the route rather than the shipment: "The chosen
route's `status` must be `ACTIVE`, otherwise `ERR_ROUTE_SUSPENDED`, and its
`region_code` must equal the branch's `region_code`, otherwise
`ERR_ROUTE_BRANCH_NOT_SERVICED`."  PRD 3.7 gives the origin triad - "its
`settlement_status` must be `SETTLED` and its `direction` must be
`SELL_FX_TO_CUSTOMER`, and the currency involved must have `buyback_eligible` true on
its profile; any of those three failing produces `ERR_BUYBACK_NOT_ELIGIBLE`" - and PRD
3.6 gates the hold release on paperwork in another aggregate: "A `RELEASE` is refused
with `ERR_STRUCTURING_REPORT_PENDING` while the customer still has a
`STRUCTURING_SUSPICION` report whose `status` is `DRAFT` or `AMENDING`".
"""

from test_helpers import (
    CLOCK_START,
    OPERATORS,
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_scheduling_validity_lives_on_the_route_row_not_the_shipment(
    api, admin_headers, treasury_headers
):
    """One identical window is refused on a SUSPENDED route in the right region,
    refused again on an ACTIVE route in the wrong region, and accepted on the ACTIVE
    route that serves the branch - and the manifest valuation fixed at creation is
    untouched by any of the three attempts.

    Design: Corner/validations/route_status_and_region_checks_on_schedule
    """
    branch = fx.register_branch(api, region_code="SOUTH")
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    suspended = fx.register_route(
        api,
        code="RT-SOUTH-SUS",
        carrier_name="Brinks",
        region_code="SOUTH",
        daily_capacity_usd_cents=10_000_000,
        status="SUSPENDED",
    )
    northern = fx.register_route(
        api,
        code="RT-NORTH-1",
        carrier_name="Loomis",
        region_code="NORTH",
        daily_capacity_usd_cents=10_000_000,
    )
    southern = fx.register_route(
        api,
        code="RT-SOUTH-1",
        carrier_name="Brinks",
        region_code="SOUTH",
        daily_capacity_usd_cents=10_000_000,
    )
    shipment = fx.raise_shipment(
        api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 5)]
    )
    assert shipment["manifest_minor_units"] == 50000
    assert shipment["manifest_usd_equivalent_cents"] == 54348

    window = f.schedule_shipment_payload(
        suspended["id"], "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"
    )
    validate_error(
        api.schedule_cash_shipment(shipment["id"], window, treasury_headers),
        ApiErrorId.ERR_ROUTE_SUSPENDED,
        422,
    )
    unscheduled = fx.read_shipment(api, shipment["id"])
    assert unscheduled["status"] == "REQUESTED"
    assert unscheduled["armored_route_id"] is None

    validate_error(
        api.schedule_cash_shipment(
            shipment["id"],
            f.schedule_shipment_payload(
                northern["id"], "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"
            ),
            treasury_headers,
        ),
        ApiErrorId.ERR_ROUTE_BRANCH_NOT_SERVICED,
        422,
    )

    scheduled = validate_success(
        api.schedule_cash_shipment(
            shipment["id"],
            f.schedule_shipment_payload(
                southern["id"], "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"
            ),
            treasury_headers,
        )
    )
    a.assert_cash_shipment(scheduled)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["armored_route_id"] == southern["id"]
    a.assert_timestamp_equals(scheduled["window_start"], "2026-08-02T08:00:00Z")
    a.assert_timestamp_equals(scheduled["window_end"], "2026-08-02T12:00:00Z")
    assert scheduled["manifest_minor_units"] == 50000
    assert scheduled["manifest_usd_equivalent_cents"] == 54348

    still_suspended = validate_success(
        api.get_armored_route(suspended["id"], admin_headers)
    )
    assert still_suspended["status"] == "SUSPENDED"
    assert "version" not in still_suspended


def test_the_origin_triad_the_redemption_ceiling_and_the_reversal_lock(
    api, teller_headers, manager_headers
):
    """Three settled deals that each fail one leg of the eligibility triad - an
    ineligible currency, a purchase rather than a sale, and a deal still quoted - are
    all refused with ERR_BUYBACK_NOT_ELIGIBLE without touching the customer version, the
    eligible sale writes a 20606-cent liability, a 30000-minor redemption against 20000
    remaining is refused rather than clamped, and the origin can no longer be reversed.

    Design: Corner/validations/buyback_eligibility_ceiling_and_reversal_block
    """
    world = fx.trading_world(api, position_mix=[f.denom(10000, 20)], identified=False)
    chf = fx.add_currency_line(
        api,
        world,
        f.chf_currency_payload(
            standard_denominations=[1000, 2000, 5000, 20000], buyback_eligible=False
        ),
        912345,
        position_mix=[f.denom(20000, 10)],
        card_overrides={"board_display_label": "CHF Franc"},
    )
    assert chf["card"]["sell_rate_micros"] == 871289
    assert chf["currency"]["buyback_eligible"] is False

    eur_sale = fx.settled_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 2)], teller_headers
    )
    a.assert_settlement_money(eur_sale, 22763, 797, 23560)
    chf_sale = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(20000, 1)],
        teller_headers,
        rate_card_id=chf["card"]["id"],
        currency_code="CHF",
    )
    # PRD 3.5: the settlement tier basis is this deal's gross plus the customer's
    # other same-branch, same-UTC-day settlements, so the earlier 22763-cent EUR sale
    # lifts the basis to 45717 cents and selects the 250-bps band.
    a.assert_settlement_money(chf_sale, 22954, 574, 23528)
    eur_purchase = fx.settled_deal(
        api, world, "BUY_FX_FROM_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    a.assert_settlement_money(eur_purchase, 10303, 400, 9903)
    quoted = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    assert quoted["settlement_status"] == "QUOTED"

    customer_id = world["customer"]["id"]
    pinned = fx.customer_version(api, customer_id)
    for origin in (chf_sale["id"], eur_purchase["id"], quoted["id"]):
        validate_error(
            api.create_buyback_contract(
                f.create_buyback_contract_payload(customer_id, origin, pinned),
                teller_headers,
            ),
            ApiErrorId.ERR_BUYBACK_NOT_ELIGIBLE,
            422,
        )
    assert fx.read_customer(api, customer_id)["version"] == pinned

    contract = validate_success(
        api.create_buyback_contract(
            f.create_buyback_contract_payload(customer_id, eur_sale["id"], pinned),
            teller_headers,
        ),
        201,
    )
    a.assert_buyback_contract(contract)
    assert contract["locked_buy_rate_micros"] == 970600
    assert contract["locked_fx_minor_units"] == 20000
    assert contract["remaining_fx_minor_units"] == 20000
    assert contract["fee_usd_cents"] == 683
    assert contract["liability_usd_cents"] == 20606
    a.assert_timestamp_equals(contract["rate_lock_expires_at"], "2026-09-01T00:00:00Z")

    validate_error(
        api.redeem_buyback_contract(
            contract["id"], f.redeem_payload([f.denom(10000, 3)]), teller_headers
        ),
        ApiErrorId.ERR_REDEEM_EXCEEDS_REMAINING,
        422,
    )
    intact = fx.read_contract(api, contract["id"])
    assert intact["status"] == "ISSUED"
    assert intact["remaining_fx_minor_units"] == 20000
    assert intact["redemption_count"] == 0

    validate_error(
        api.reverse_transaction(
            eur_sale["id"], f.reverse_payload("customer complaint"), manager_headers
        ),
        ApiErrorId.ERR_BUYBACK_BLOCKS_REVERSAL,
        422,
    )
    locked = fx.read_transaction(api, eur_sale["id"])
    assert locked["settlement_status"] == "SETTLED"
    assert locked["buyback_contract_id"] == contract["id"]


def test_the_permitted_outcome_depends_on_the_recorded_defect(
    api, teller_headers, teller2_headers, manager_headers, compliance_headers
):
    """CONFISCATED on a damaged note, RETURNED on a suspected counterfeit and
    EXCHANGED_AT_DISCOUNT on an obsolete series are all refused with
    ERR_OUTCOME_NOT_PERMITTED_FOR_DEFECT while the assessments stay SUBMITTED, and the
    three legal outcomes then land: the obsolete note leaves, the damaged note comes
    back at 6697 cents and the counterfeit is written off with its report.

    Design: Corner/validations/assessment_outcome_defect_matrix_rejected
    """
    world = fx.trading_world(api, position_mix=[f.denom(10000, 20)], identified=False)
    txn = fx.settled_deal(
        api,
        world,
        "BUY_FX_FROM_CUSTOMER",
        [f.denom(10000, 3)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    a.assert_settlement_money(txn, 30909, 773, 30136)

    branch_id = world["branch"]["id"]
    position_id = world["position"]["id"]
    damaged = fx.detain_notes(
        api, branch_id, position_id, txn["id"], 10000, 1, "DAMAGED", teller_headers
    )
    counterfeit = fx.detain_notes(
        api,
        branch_id,
        position_id,
        txn["id"],
        10000,
        1,
        "SUSPECTED_COUNTERFEIT",
        teller_headers,
        serial_reference="EX9911872",
    )
    obsolete = fx.detain_notes(
        api,
        branch_id,
        position_id,
        txn["id"],
        10000,
        1,
        "OBSOLETE_SERIES",
        teller_headers,
    )
    quarantined = fx.read_position(api, position_id)
    a.assert_mix_counts(quarantined, 10000, available=20, quarantined=3)

    for assessment, outcome in (
        (damaged, "CONFISCATED"),
        (counterfeit, "RETURNED"),
        (obsolete, "EXCHANGED_AT_DISCOUNT"),
    ):
        validate_error(
            api.assess_note_assessment(
                assessment["id"],
                f.assess_payload(outcome, "wrong branch of the fork"),
                manager_headers,
            ),
            ApiErrorId.ERR_OUTCOME_NOT_PERMITTED_FOR_DEFECT,
            422,
        )
        untouched = validate_success(
            api.get_note_assessment(assessment["id"], manager_headers)
        )
        assert untouched["status"] == "SUBMITTED"
        assert untouched["outcome"] is None

    returned = fx.assess_notes(
        api, obsolete["id"], "RETURNED", "handed back to the customer", manager_headers
    )
    assert returned["recovery_usd_cents"] is None
    after_return = fx.read_position(api, position_id)
    a.assert_mix_counts(after_return, 10000, available=20, quarantined=2)

    discounted = fx.assess_notes(
        api, damaged["id"], "EXCHANGED_AT_DISCOUNT", "torn corner", manager_headers
    )
    assert discounted["recovery_usd_cents"] == 6697
    after_discount = fx.read_position(api, position_id)
    a.assert_mix_counts(after_discount, 10000, available=21, quarantined=1)

    seized = fx.assess_notes(
        api, counterfeit["id"], "CONFISCATED", "seized", manager_headers
    )
    a.assert_note_assessment(seized)
    assert seized["recovery_usd_cents"] is None
    assert seized["assessed_by_user_id"] == OPERATORS["MANAGER"]

    final = fx.read_position(api, position_id)
    a.assert_position_mix_invariants(final)
    a.assert_mix_counts(final, 10000, available=21, quarantined=0, written_off=1)
    assert final["total_minor_units"] == 210000
    assert final["usd_equivalent_cents"] == 228261

    rows, meta = validate_paginated(api.list_compliance_reports(compliance_headers))
    assert meta["total_count"] == 1
    assert rows[0]["report_type"] == "COUNTERFEIT_SEIZURE"
    assert rows[0]["status"] == "DRAFT"
    assert rows[0]["note_assessment_id"] == counterfeit["id"]

    cited = fx.read_transaction(api, txn["id"])
    assert cited["compliance_status"] == "FLAGGED"
    assert cited["settlement_status"] == "SETTLED"


def test_the_hold_release_waits_on_a_report_in_another_aggregate(
    api, teller_headers, teller2_headers, compliance_headers
):
    """Three eighty-note sales take the customer to a 73-point HIGH tier with an
    automatic hold, the first RELEASE is refused with ERR_STRUCTURING_REPORT_PENDING
    while the report is still DRAFT, and the identical RELEASE succeeds once that
    report is FILED - the customer is still HIGH, so nothing about the customer
    changed in between.

    Design: Corner/validations/structuring_report_pending_blocks_hold_release
    """
    world = fx.trading_world(
        api,
        vault_limit_usd_cents=100_000_000,
        position_mix=[f.denom(10000, 240)],
        customer_overrides={
            "full_name": "Ravi Chandra",
            "nationality_code": "IN",
            "id_document_number": "P8817264",
            "id_document_expiry": "2030-01-01T00:00:00Z",
        },
    )
    a.assert_vault_state(world["branch"], 2608696, 261, "OPEN")
    customer_id = world["customer"]["id"]

    for _ in range(3):
        settled = fx.settled_deal(
            api,
            world,
            "SELL_FX_TO_CUSTOMER",
            [f.denom(10000, 80)],
            teller_headers,
            settle_headers=teller2_headers,
        )
        a.assert_settlement_money(settled, 910539, 13658, 924197)

    at_risk = fx.read_customer(api, customer_id)
    assert at_risk["rolling_30d_settled_usd_cents"] == 2731617
    assert at_risk["near_threshold_txn_count"] == 3
    assert at_risk["structuring_risk_score"] == 73
    assert at_risk["structuring_risk_tier"] == "HIGH"
    assert at_risk["compliance_hold_active"] is True

    validate_error(
        api.compliance_hold(
            customer_id,
            f.compliance_hold_payload("RELEASE", "customer explained the travel plan"),
            compliance_headers,
        ),
        ApiErrorId.ERR_STRUCTURING_REPORT_PENDING,
        409,
    )
    assert fx.read_customer(api, customer_id)["compliance_hold_active"] is True

    report = fx.only_report(
        api, {"customer_id": customer_id, "report_type": "STRUCTURING_SUSPICION"}
    )
    a.assert_compliance_report(report)
    assert report["status"] == "DRAFT"
    assert report["aggregate_usd_cents"] == 2731617
    assert report["transaction_count"] == 3

    filed = fx.file_report(api, report["id"], "FINCEN-2026-08-0001")
    assert filed["status"] == "FILED"
    assert filed["filing_reference"] == "FINCEN-2026-08-0001"
    assert filed["amendment_count"] == 0
    a.assert_timestamp_equals(filed["filed_at"], CLOCK_START)

    released = fx.release_hold(api, customer_id, "report filed, hold lifted")
    assert released["compliance_hold_active"] is False
    assert released["structuring_risk_tier"] == "HIGH"

    emptied = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(emptied)
    a.assert_mix_counts(emptied, 10000, available=0)
    assert emptied["total_minor_units"] == 0
    a.assert_vault_state(fx.read_branch(api, world["branch"]["id"]), 0, 0, "OPEN")
