"""Unwinding a bill, replacing a contract, and keeping the ledger honest.

The deep cascades of this domain are proved here end to end. Voiding an issued
invoice walks back down through its lines, its packages, the account
aggregates and its dangling proposals. Activating a successor contract
truncates its predecessor and moves the account version that guards every
other activation. The sweep and the issue that follows it move the five
account aggregates in lockstep, while a manual reweigh updates a package's
measurement picture without minting the adjustment an automated capture would
have minted. The last two tests read the ledger itself: which invoice states
`open_charges_cents` counts, and how three different expected-version guards
each report their own parent record and nobody else's.
"""

from test_helpers import (
    BILLING_OPS_HEADERS,
    CARRIER_ADMIN_HEADERS,
    CARRIER_OPS_HEADERS,
    ERR_STALE_INVOICE_VERSION,
    ERR_STALE_SHIPMENT_VERSION,
    ERR_STALE_SHIPPER_VERSION,
    accessorials_for_shipment,
    activate_rate_contract,
    add_scan,
    assert_fields,
    assert_instant,
    assert_lbs,
    assert_ledger,
    assert_money_equals,
    assert_null_fields,
    assert_version_bumped_by,
    billing_adjustment_payload,
    create_express_service_level,
    create_shipper_account,
    delivered_shipment,
    draft_rate_contract,
    find_row,
    get_success_data,
    ids_of,
    induct_shipment,
    issued_invoice,
    open_invoice,
    propose_adjustment,
    refresh_invoice,
    refresh_invoice_line,
    refresh_shipment,
    refresh_shipper_account,
    scan_payload,
    shipment_payload,
    shipper_with_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

ACME_ACCOUNT_NUMBER = "SH-2001"
ACME_NAME = "Acme Parcel"

# The reference parcel: 12 x 10 x 8 in at 6.0 lb in zone 2. Its cube of 960
# in3 over the 139 divisor gives 7 dimensional pounds, so 7 actual pounds
# would tie and the declared 6.0 lb rounds to 6 — the dimensional figure of 7
# governs and 7 x 380 = 2660 cents clears the 1195-cent floor.
SMALL_PARCEL = {
    "zone": 2,
    "residential_declared": False,
    "declared_length_in": 12,
    "declared_width_in": 10,
    "declared_height_in": 8,
    "declared_weight_lbs": 6.0,
}
TRANSPORTATION_CENTS = 2660

# The successor contract prices the same zone with two coarser bands.
SUCCESSOR_RATE_ROWS = [
    {"zone": 2, "min_lbs": 1, "max_lbs": 20, "cents_per_lb": 400},
    {"zone": 2, "min_lbs": 21, "max_lbs": 9999, "cents_per_lb": 360},
]
SUCCESSOR_TIER_ROWS = [
    {"min_transportation_subtotal_cents": 50000, "discount_bps": 600},
]

CLOCK_INSTANT = "2026-08-01T00:00:00Z"


def _acme(api):
    """SH-2001 holding one ACTIVE EXPRESS-only contract."""
    return shipper_with_active_contract(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME, with_ground=False
    )


def _adjustments(api, **params):
    """Page the adjustment register through the billing desk's own view."""
    query = {"limit": 100}
    query.update(params)
    return validate_paginated(api.list_billing_adjustments(BILLING_OPS_HEADERS, query))


def _contract(api, contract_id):
    """Re-read one rate contract, which is how its truncation becomes visible."""
    return get_success_data(api.get_rate_contract(contract_id, CARRIER_ADMIN_HEADERS))


def test_01_voiding_an_issued_bill_unwinds_lines_parcels_ledger_and_proposals(api):
    """Voiding a published bill returns the parcel to the unbilled pool.

    One delivered parcel is swept, issued and then carries a dangling credit
    proposal that nobody released. The void must run every hop at once: the
    line is flagged voided, the package walks back to `UNBILLED`, the two
    package counters swap back, `open_charges_cents` drains, and the untouched
    proposal is rejected without any money ever having moved.

    PRD §3.7: "Voiding unwinds every consequence of an invoice so that its packages become billable again, and it is reachable from `OPEN → VOID`, `ISSUED → VOID`, and `ADJUSTED → VOID`."
    PRD §3.7: "*Hop 1* — every `InvoiceLine` of the invoice sets `voided` to true."
    PRD §3.7: "Either way the package becomes sweepable by a later billing run, and its `version` increments by 1."
    PRD §3.7: "Voiding from `ISSUED` additionally decreases the account's `open_charges_cents` by the invoice's `net_amount_cents`, and adds *hop 4* — every `PROPOSED` `BillingAdjustment` on this invoice's lines moves to `REJECTED`, exactly as an operator-driven rejection would, with no money moving."
    PRD §2.11: "`credit_balance_cents` — the negated sum of `delta_cents` over every `BillingAdjustment` whose status is `APPLIED` and which hangs off an invoice line of one of this account's invoices whose status is not `VOID`."

    Design: Corner/state_machines/voiding_an_issued_invoice_cascades_down_to_lines_shipments_and_adjustments
    """
    shipper = _acme(api)
    parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-Z-0001",
        **SMALL_PARCEL,
    )
    invoice = open_invoice(
        api,
        shipper,
        [parcel.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    issued = issued_invoice(api, invoice)
    line_id = issued.line_ids[0]
    assert len(issued.line_ids) == 1, "the sweep should have found exactly one parcel"
    assert_money_equals(
        issued.invoice["net_amount_cents"], TRANSPORTATION_CENTS, "issued net"
    )
    assert_ledger(
        refresh_shipper_account(api, shipper.shipper_id),
        total=1,
        unbilled=0,
        billed=1,
        open_charges_cents=TRANSPORTATION_CENTS,
        credit_balance_cents=0,
    )

    # A five-dollar credit is proposed and then left dangling: no second
    # operator ever releases it, so no money has moved when the void lands.
    adjustment = propose_adjustment(
        api,
        issued,
        line_id,
        -500,
        reason="MANUAL",
        expected_invoice_version=issued.invoice_version,
    )
    dangling = refresh_invoice(api, issued.invoice_id)
    assert_fields(
        dangling,
        {"status": "ISSUED", "pending_adjustment_count": 1, "has_pending_adjustments": True},
    )
    parcel_before_void = refresh_shipment(api, parcel.shipment_id)

    voided = validate_success(
        api.void_invoice(issued.invoice_id, BILLING_OPS_HEADERS)
    )

    # The invoice itself: void, worthless, and carrying no live proposal.
    assert_fields(
        voided,
        {"status": "VOID", "pending_adjustment_count": 0, "has_pending_adjustments": False},
    )
    assert_money_equals(voided["net_amount_cents"], 0, "voided net")
    assert_version_bumped_by(dangling, voided)

    # Hop 1 - the line survives as history with its voided flag raised.
    line = refresh_invoice_line(api, line_id)
    assert line["voided"] is True, "the line of a voided invoice must be flagged voided"

    # Hop 2 - the package is sweepable again, one version later.
    parcel_after_void = refresh_shipment(api, parcel.shipment_id)
    assert_fields(parcel_after_void, {"billing_status": "UNBILLED"})
    assert_version_bumped_by(parcel_before_void, parcel_after_void)

    # Hop 3 and the open-charge drain: the compensating pair nets to zero.
    account = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(
        account,
        total=1,
        unbilled=1,
        billed=0,
        open_charges_cents=0,
        credit_balance_cents=0,
    )
    assert (
        account["unbilled_shipment_count"] + account["billed_shipment_count"]
        == account["total_shipment_count"]
    ), "the conserved-package-count invariant must survive the void"

    # Hop 4 - the dangling proposal is rejected, and rejection moves no money.
    rejected = get_success_data(
        api.get_billing_adjustment(adjustment.adjustment_id, BILLING_OPS_HEADERS)
    )
    assert_fields(rejected, {"status": "REJECTED"})
    assert_money_equals(rejected["delta_cents"], -500, "rejected delta")
    assert_null_fields(rejected, ["applied_by_user_id", "applied_at"])


def test_02_activating_a_successor_truncates_its_predecessor_and_moves_the_account(api):
    """The governance event: one contract retires another and the account moves.

    The successor is drafted with a period that plainly overlaps the incumbent,
    which is legal only because it names the incumbent as the contract it
    replaces. Activating it must retire the incumbent, pull the incumbent's
    end date back to the day before the successor opens, bump three versions,
    and leave exactly one ACTIVE contract on the account.

    PRD §3.1: "One contract is exempt from that scan: the single contract named by this request's `supersedes_contract_id`, because activating the successor is precisely the act that truncates the predecessor's window."
    PRD §3.1: "A successful activation sets the contract's `activated_at` from the logical clock and moves its `status` `DRAFT` → `ACTIVE`."
    PRD §3.1: "First, the named predecessor moves `ACTIVE` → `SUPERSEDED` and its `effective_to` is truncated to the day immediately before the successor's `effective_from`."
    PRD §3.1: "Second, because the predecessor's `effective_to` moved, the owning `ShipperAccount`'s `version` increments by 1 — this is what makes any other client holding a stale contract view fail its own next activation attempt."
    PRD §3.1: "Third, `version` increments by 1 on both the activated contract and the superseded one."
    PRD §3.1: "Contracts may be listed with optional filters on `shipper_id`, on `supersedes_contract_id` (to find the successor of a given contract), and on `status`, and an individual contract read returns its full `rate_table` and `tier_discount_table`."

    Design: Corner/state_machines/activating_a_successor_contract_supersedes_and_truncates_its_predecessor
    """
    account = create_shipper_account(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME
    )
    incumbent = draft_rate_contract(api, account["id"])
    activate_rate_contract(api, incumbent["id"], account["version"])
    incumbent_active = _contract(api, incumbent["id"])
    assert_fields(
        incumbent_active,
        {
            "status": "ACTIVE",
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
        },
    )

    account_before = refresh_shipper_account(api, account["id"])

    # July 2026 through June 2027 sits squarely inside the incumbent's year.
    # Only the supersession pointer makes that draft admissible.
    successor = draft_rate_contract(
        api,
        account["id"],
        effective_from="2026-07-01",
        effective_to="2027-06-30",
        dim_divisor=166,
        min_charge_cents=1295,
        rate_table=SUCCESSOR_RATE_ROWS,
        tier_discount_table=SUCCESSOR_TIER_ROWS,
        supersedes_contract_id=incumbent["id"],
    )
    assert_fields(
        successor,
        {"status": "DRAFT", "supersedes_contract_id": incumbent["id"]},
    )
    assert_null_fields(successor, ["activated_at"])

    activated = activate_rate_contract(
        api, successor["id"], account_before["version"]
    )

    assert_fields(activated, {"status": "ACTIVE"})
    assert_instant(activated["activated_at"], CLOCK_INSTANT, "activated_at")
    assert_version_bumped_by(successor, activated)

    # Hop 1 - the incumbent retires and its window is pulled back to the day
    # before the successor opens.
    retired = _contract(api, incumbent["id"])
    assert_fields(
        retired,
        {
            "status": "SUPERSEDED",
            "effective_from": "2026-01-01",
            "effective_to": "2026-06-30",
        },
    )
    assert_version_bumped_by(incumbent_active, retired)

    # Hop 2 - the account version moves, which is what invalidates any other
    # client's picture of which contract prices which dates.
    account_after = refresh_shipper_account(api, account["id"])
    assert_version_bumped_by(account_before, account_after)

    # The successor's own levers survive the round trip.
    assert_fields(activated, {"dim_divisor": 166})
    assert_money_equals(activated["min_charge_cents"], 1295, "successor floor")
    assert activated["rate_table"] == SUCCESSOR_RATE_ROWS, (
        "an individual contract read returns its full rate_table"
    )
    assert activated["tier_discount_table"] == SUCCESSOR_TIER_ROWS, (
        "an individual contract read returns its full tier_discount_table"
    )

    # Exactly one contract is left pricing this account, and it is findable
    # from the contract it replaced.
    active_rows, active_meta = validate_paginated(
        api.list_rate_contracts(
            CARRIER_ADMIN_HEADERS,
            {"shipper_id": account["id"], "status": "ACTIVE", "limit": 100},
        )
    )
    assert active_meta["total_count"] == 1, (
        "only the successor should still be ACTIVE"
    )
    assert ids_of(active_rows) == [successor["id"]]

    successor_rows, successor_meta = validate_paginated(
        api.list_rate_contracts(
            CARRIER_ADMIN_HEADERS,
            {"supersedes_contract_id": incumbent["id"], "limit": 100},
        )
    )
    assert successor_meta["total_count"] == 1, (
        "the successor of a given contract must be findable by that filter"
    )
    assert ids_of(successor_rows) == [successor["id"]]


def test_03_the_sweep_and_the_issue_move_the_account_aggregates_in_lockstep(api):
    """Two parcels, one sweep, and five aggregates that must all agree.

    The sweep moves both packages off the unbilled pile and onto the billed
    one without touching the total, and it leaves `open_charges_cents` at zero
    because an OPEN invoice has never contributed to the ledger. Only the
    issue lifts the open charge, and it lifts it by exactly the invoice net.

    PRD §3.6: "Every swept package moves `UNBILLED → BILLED` on the billing axis, and the owning account's `unbilled_shipment_count` falls by the line count while `billed_shipment_count` rises by the same amount, preserving the conserved-package-count invariant of §2.11."
    PRD §3.6: "Each swept shipment's `version` increments by 1."
    PRD §3.6: "1. `transportation_subtotal_cents` is the sum, over the invoice's lines, of `transportation_base_cents` plus `surcharge_cents`."
    PRD §3.6: "When no row qualifies, `tier_discount_bps` is 0."
    PRD §3.7: "The owning account's `open_charges_cents` rises by this invoice's `net_amount_cents`, and the invoice's `version` increments by 1."
    PRD §2.11: "`open_charges_cents` — the sum of `net_amount_cents` over this account's invoices whose status is either `ISSUED` or `ADJUSTED`."

    Design: Corner/state_machines/the_billing_sweep_keeps_the_shipper_ledger_in_lockstep
    """
    shipper = _acme(api)
    first = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-G-0001",
        **SMALL_PARCEL,
    )
    second = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-G-0002",
        **SMALL_PARCEL,
    )
    first_before = refresh_shipment(api, first.shipment_id)
    second_before = refresh_shipment(api, second.shipment_id)

    account_before = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(
        account_before,
        total=2,
        unbilled=2,
        billed=0,
        open_charges_cents=0,
        credit_balance_cents=0,
    )

    invoice = open_invoice(
        api,
        shipper,
        [first.shipment_id, second.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-31",
    )
    swept = invoice.invoice
    assert_fields(swept, {"status": "OPEN", "line_count": 2, "tier_discount_bps": 0})
    assert_money_equals(
        swept["transportation_subtotal_cents"],
        2 * TRANSPORTATION_CENTS,
        "transportation subtotal",
    )
    assert_money_equals(
        swept["accessorial_subtotal_cents"], 0, "accessorial subtotal"
    )
    assert_money_equals(swept["tier_discount_cents"], 0, "tier discount")
    assert_money_equals(swept["net_amount_cents"], 2 * TRANSPORTATION_CENTS, "open net")

    # Both packages crossed to BILLED, one version each.
    for label, before in (("1Z-G-0001", first_before), ("1Z-G-0002", second_before)):
        after = refresh_shipment(api, before["id"])
        assert_fields(after, {"tracking_number": label, "billing_status": "BILLED"})
        assert_version_bumped_by(before, after)

    # The counters swapped; the total never moved; an OPEN bill is not a charge.
    account_open = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(
        account_open,
        total=2,
        unbilled=0,
        billed=2,
        open_charges_cents=0,
        credit_balance_cents=0,
    )

    issued = issued_invoice(api, invoice)
    assert_fields(issued.invoice, {"status": "ISSUED"})
    assert_money_equals(
        issued.invoice["net_amount_cents"], 2 * TRANSPORTATION_CENTS, "issued net"
    )

    account_issued = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(
        account_issued,
        total=2,
        unbilled=0,
        billed=2,
        open_charges_cents=2 * TRANSPORTATION_CENTS,
        credit_balance_cents=0,
    )
    assert (
        account_issued["unbilled_shipment_count"]
        + account_issued["billed_shipment_count"]
        == account_issued["total_shipment_count"]
    ), "the conserved-package-count invariant must hold after the issue too"


def test_04_a_manual_reweigh_verifies_the_measurement_without_minting_an_adjustment(api):
    """The reweigh that changes everything about the parcel and nothing about the bill.

    A 40 x 20 x 20 parcel at 45.0 lb is scanned inside tolerance, billed and
    issued at 116 dimensional pounds. A human then reweighs it at 50 x 22 x 22
    and 47.0 lb: length-plus-girth of 138 inches trips oversize, the pound
    count climbs to 175 and a 125-dollar oversize charge appears, so the
    package would now price at 65875 cents. Because the capture was a manual
    reweigh, the frozen line keeps its 35380 and no adjustment is raised.

    PRD §3.4: "A `MANUAL_REWEIGH` capture is authoritative regardless of variance and drives the shipment straight to `VERIFIED`, reachable as `PENDING_SCAN → VERIFIED`, `SCANNED → VERIFIED`, and `TOLERANCE_FLAGGED → VERIFIED`."
    PRD §3.4: "When the capture was a manual reweigh, no adjustment is raised at all, no matter how large the difference: a reweigh feeds dispute review and never rebills on its own."
    PRD §3.4: "The shipment's `billable_weight_lbs` then switches to `final_billable_weight_lbs` and stays there for as long as a scan exists."
    PRD §3.3: "The `oversize_flag` is set true when the longest dimension strictly exceeds 96 inches — eight feet — or when length-plus-girth strictly exceeds 130 inches."
    PRD §2.9: "**The owning invoice is `ISSUED` or `ADJUSTED` and the trigger is a manual reweigh** — the shipment's measurement fields update, but no adjustment is created."
    PRD §3.6: "**Previewing a price without billing.** `BillingOps` and `RevenueAuditor` may dry-run the pricing of a single package at its current billable weight."

    Design: Corner/state_machines/a_manual_reweigh_verifies_the_measurement_without_minting_an_adjustment
    """
    shipper = _acme(api)
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-M-0001",
        zone=2,
        residential_declared=False,
        declared_length_in=40,
        declared_width_in=20,
        declared_height_in=20,
        declared_weight_lbs=45.0,
    )
    # 40 x 20 x 20 cubes to 16000 in3, which over the 139 divisor gives 116
    # dimensional pounds against 45 actual, so the parcel bills at 116 x 305.
    assert_lbs(parcel.shipment["billable_weight_lbs"], 116, "declared billable weight")
    add_scan(
        api,
        parcel.shipment_id,
        parcel.shipment_version,
        scan_source="AUTOMATED_DWS",
        scanned_length_in=40,
        scanned_width_in=20,
        scanned_height_in=20,
        scanned_weight_lbs=45.0,
    )
    scanned = refresh_shipment(api, parcel.shipment_id)
    assert_fields(scanned, {"measurement_status": "SCANNED"})
    validate_success(api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS))

    invoice = open_invoice(
        api,
        shipper,
        [parcel.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-01",
    )
    issued = issued_invoice(api, invoice)
    line_id = invoice.line_by_shipment[parcel.shipment_id]
    frozen_line = refresh_invoice_line(api, line_id)
    assert_money_equals(frozen_line["base_line_total_cents"], 35380, "frozen line")
    assert_money_equals(frozen_line["line_total_cents"], 35380, "frozen line total")

    before_reweigh = refresh_shipment(api, parcel.shipment_id)
    add_scan(
        api,
        parcel.shipment_id,
        before_reweigh["version"],
        scan_source="MANUAL_REWEIGH",
        scanned_length_in=50,
        scanned_width_in=22,
        scanned_height_in=22,
        scanned_weight_lbs=47.0,
    )

    # The measurement axis reaches its terminal state and the pound count
    # climbs: 50 x 22 x 22 cubes to 24200 in3, which needs 175 pounds.
    reweighed = refresh_shipment(api, parcel.shipment_id)
    assert_fields(
        reweighed, {"measurement_status": "VERIFIED", "oversize_flag": True}
    )
    assert_lbs(reweighed["final_billable_weight_lbs"], 175, "final billable weight")
    assert_lbs(reweighed["billable_weight_lbs"], 175, "published billable weight")

    # Length-plus-girth of 50 + 2 x (22 + 22) = 138 inches trips oversize, so
    # the automatic re-assessment mints the 125-dollar charge.
    charges = accessorials_for_shipment(api, parcel.shipment_id)
    oversize = find_row(charges, code="OVERSIZE")
    assert_fields(oversize, {"status": "ASSESSED", "source": "AUTO"})
    assert_money_equals(oversize["amount_cents"], 12500, "oversize charge")
    assert len(charges) == 1, (
        "the reweighed geometry implies exactly one automatic charge, "
        f"got {[row['code'] for row in charges]}"
    )

    # The dry run proves the parcel would now price far above its frozen line.
    preview = get_success_data(
        api.get_billing_preview(parcel.shipment_id, BILLING_OPS_HEADERS)
    )
    assert_lbs(preview["billable_weight_lbs"], 175, "preview billable weight")
    assert_money_equals(preview["transportation_base_cents"], 53375, "preview base")
    assert_money_equals(preview["accessorial_total_cents"], 12500, "preview accessorials")
    assert_money_equals(preview["line_total_cents"], 65875, "preview line total")

    # And yet nothing rebills: the line is untouched and no adjustment exists.
    still_frozen = refresh_invoice_line(api, line_id)
    assert_money_equals(
        still_frozen["base_line_total_cents"], 35380, "line after the reweigh"
    )
    assert_money_equals(
        still_frozen["line_total_cents"], 35380, "line total after the reweigh"
    )
    _, adjustment_meta = _adjustments(api, invoice_line_id=line_id)
    assert adjustment_meta["total_count"] == 0, (
        "a manual reweigh must never mint an adjustment"
    )
    final_invoice = refresh_invoice(api, issued.invoice_id)
    assert_fields(
        final_invoice,
        {
            "status": "ISSUED",
            "pending_adjustment_count": 0,
            "has_pending_adjustments": False,
        },
    )
    assert_money_equals(final_invoice["net_amount_cents"], 35380, "invoice net")


def test_05_open_charges_count_only_the_published_and_unsettled_bill(api):
    """An invoice is a charge on the account only between issue and settlement.

    The same 2660-cent bill is read three times: OPEN, ISSUED, then SETTLED.
    Only the middle reading contributes to `open_charges_cents`. The package
    stays billed and the line keeps its money throughout, so settlement closes
    the receivable without unwinding anything.

    PRD §2.11: "`open_charges_cents` — the sum of `net_amount_cents` over this account's invoices whose status is either `ISSUED` or `ADJUSTED`."
    PRD §2.11: "**Conserved money:** `credit_balance_cents`, plus the sum of `net_amount_cents` over the account's invoices whose status is `ISSUED`, `ADJUSTED`, or `SETTLED`, equals the sum, over the same set of invoices, of `gross_charges_cents` minus `tier_discount_cents`."
    PRD §3.7: "**Settle.** Settlement is reachable from two states with identical semantics — `ISSUED → SETTLED` and `ADJUSTED → SETTLED` — and requires that the invoice's `pending_adjustment_count` is exactly 0, so no proposal is left dangling when the money is closed out."
    PRD §3.7: "The operator supplies a `payment_reference`, the remittance reference captured at settlement, which is stored on the invoice."
    PRD §3.7: "The owning account's `open_charges_cents` falls by this invoice's `net_amount_cents`, and the invoice's `version` increments by 1."

    Design: Corner/calculations/open_charges_aggregate_only_issued_and_adjusted_invoices
    """
    shipper = _acme(api)
    parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-O-0001",
        **SMALL_PARCEL,
    )
    invoice = open_invoice(
        api,
        shipper,
        [parcel.shipment_id],
        period_start="2026-08-01",
        period_end="2026-08-31",
    )
    line_id = invoice.line_by_shipment[parcel.shipment_id]
    assert_money_equals(
        invoice.invoice["net_amount_cents"], TRANSPORTATION_CENTS, "open net"
    )

    # Reading one: an OPEN invoice has never contributed to the ledger.
    assert_ledger(
        refresh_shipper_account(api, shipper.shipper_id),
        total=1,
        unbilled=0,
        billed=1,
        open_charges_cents=0,
        credit_balance_cents=0,
    )

    issued = issued_invoice(api, invoice)
    assert_fields(issued.invoice, {"status": "ISSUED"})

    # Reading two: the published bill is a live charge for exactly its net.
    account_issued = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(
        account_issued,
        total=1,
        unbilled=0,
        billed=1,
        open_charges_cents=TRANSPORTATION_CENTS,
        credit_balance_cents=0,
    )
    assert (
        account_issued["credit_balance_cents"]
        + issued.invoice["net_amount_cents"]
        == issued.invoice["gross_charges_cents"]
        - issued.invoice["tier_discount_cents"]
    ), "the conserved-money invariant must hold on the issued bill"

    settled = validate_success(
        api.settle_invoice(issued.invoice_id, "ACH-99001", BILLING_OPS_HEADERS)
    )
    assert_fields(settled, {"status": "SETTLED", "payment_reference": "ACH-99001"})
    assert_money_equals(
        settled["net_amount_cents"], TRANSPORTATION_CENTS, "settled net"
    )
    assert_version_bumped_by(issued.invoice, settled)

    # Reading three: a settled bill is off the receivable, but nothing unwinds.
    account_settled = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(
        account_settled,
        total=1,
        unbilled=0,
        billed=1,
        open_charges_cents=0,
        credit_balance_cents=0,
    )
    assert_fields(refresh_shipment(api, parcel.shipment_id), {"billing_status": "BILLED"})
    assert_money_equals(
        refresh_invoice_line(api, line_id)["line_total_cents"],
        TRANSPORTATION_CENTS,
        "settled line total",
    )


def test_06_three_expected_version_guards_each_report_their_own_parent(api):
    """Three parents, three burned versions, three distinct refusals.

    Every write that takes an expected-version field is made twice against the
    same parent reading: once successfully, once as a replay. The successor
    activation burns the account version, the first scan burns the shipment
    version, and — the case implementations miss — merely proposing an
    adjustment burns the invoice version without any money moving. Each replay
    must name its own parent, and re-reading that parent must always be enough
    to make the identical call succeed.

    PRD §2.7: "Each of those three requires a non-optional expected-version field, and each rejects a mismatch against the parent's live `version` with its own dedicated error at HTTP 412."
    PRD §2.7: "If that account's current `version` has advanced since the client read it, the activation is rejected with `ERR_STALE_SHIPPER_VERSION` (HTTP 412)."
    PRD §2.7: "If the shipment's current `version` has advanced, the scan is rejected with `ERR_STALE_SHIPMENT_VERSION` (HTTP 412)."
    PRD §2.7: "If the invoice's current `version` has advanced, the proposal is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412)."
    PRD §3.1: "Second, because the predecessor's `effective_to` moved, the owning `ShipperAccount`'s `version` increments by 1 — this is what makes any other client holding a stale contract view fail its own next activation attempt."
    PRD §3.4: "Every successful capture increments the shipment's `version` by 1."
    PRD §3.8: "The owning invoice's `pending_adjustment_count` rises by 1, `has_pending_adjustments` becomes true, and the invoice's `version` increments by 1 — which is precisely why a second proposal computed against the pre-proposal invoice view will fail its own version check."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_guards_reject_a_stale_parent_version_independently
    """
    account = create_shipper_account(
        api, account_number=ACME_ACCOUNT_NUMBER, name=ACME_NAME
    )
    express_id = create_express_service_level(api)["id"]
    incumbent = draft_rate_contract(api, account["id"])
    activate_rate_contract(api, incumbent["id"], account["version"])

    # ---- Guard one: the shipper account behind a contract activation -------
    burned_account = refresh_shipper_account(api, account["id"])
    successor = draft_rate_contract(
        api,
        account["id"],
        effective_from="2026-07-01",
        effective_to="2027-06-30",
        supersedes_contract_id=incumbent["id"],
    )
    activated = activate_rate_contract(
        api, successor["id"], burned_account["version"]
    )
    assert_fields(activated, {"status": "ACTIVE"})

    # A third contract for the following year: nothing about it overlaps, so
    # only the burned account version can be the reason it is refused.
    third = draft_rate_contract(
        api,
        account["id"],
        effective_from="2027-07-01",
        effective_to="2028-06-30",
    )
    shipper_failure = validate_error(
        api.activate_rate_contract(
            third["id"], burned_account["version"], CARRIER_ADMIN_HEADERS
        ),
        ERR_STALE_SHIPPER_VERSION,
        412,
    )
    current_account = refresh_shipper_account(api, account["id"])
    assert_version_bumped_by(burned_account, current_account)
    assert_fields(
        activate_rate_contract(api, third["id"], current_account["version"]),
        {"status": "ACTIVE"},
    )
    assert_fields(_contract(api, third["id"]), {"status": "ACTIVE"})
    assert_fields(_contract(api, successor["id"]), {"status": "ACTIVE"})

    # ---- Guard two: the shipment behind a scan capture --------------------
    parcel = validate_success(
        api.create_shipment(
            shipment_payload(
                account["id"],
                express_id,
                tracking_number="1Z-X-1001",
                **SMALL_PARCEL,
            ),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    burned_shipment_version = parcel["version"]
    first_scan = validate_success(
        api.create_scan(
            parcel["id"],
            scan_payload(burned_shipment_version),
            CARRIER_OPS_HEADERS,
        ),
        201,
    )
    shipment_failure = validate_error(
        api.create_scan(
            parcel["id"],
            scan_payload(burned_shipment_version),
            CARRIER_OPS_HEADERS,
        ),
        ERR_STALE_SHIPMENT_VERSION,
        412,
    )
    scanned = refresh_shipment(api, parcel["id"])
    assert scanned["version"] == burned_shipment_version + 1, (
        "the first capture must have advanced the shipment by exactly one"
    )
    second_scan = validate_success(
        api.create_scan(
            parcel["id"], scan_payload(scanned["version"]), CARRIER_OPS_HEADERS
        ),
        201,
    )
    scan_rows, scan_meta = validate_paginated(
        api.list_scans(parcel["id"], CARRIER_OPS_HEADERS, {"limit": 100})
    )
    assert scan_meta["total_count"] == 2, (
        "the refused capture must not have created a scan record"
    )
    assert sorted(ids_of(scan_rows)) == sorted([first_scan["id"], second_scan["id"]])
    assert refresh_shipment(api, parcel["id"])["version"] == (
        burned_shipment_version + 2
    ), "only the two accepted captures may move the shipment version"

    # ---- Guard three: the invoice behind an adjustment proposal ------------
    validate_success(api.deliver_shipment(parcel["id"], CARRIER_OPS_HEADERS))
    swept = validate_success(
        api.create_invoice(
            {
                "shipper_id": account["id"],
                "period_start": "2026-08-01",
                "period_end": "2026-08-01",
            },
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    issued = validate_success(api.issue_invoice(swept["id"], BILLING_OPS_HEADERS))
    burned_invoice_version = issued["version"]
    line_rows, _ = validate_paginated(
        api.list_invoice_lines(
            BILLING_OPS_HEADERS, {"invoice_id": swept["id"], "limit": 100}
        )
    )
    line_id = line_rows[0]["id"]

    first_proposal = validate_success(
        api.create_billing_adjustment(
            billing_adjustment_payload(line_id, -300, burned_invoice_version),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    invoice_failure = validate_error(
        api.create_billing_adjustment(
            billing_adjustment_payload(line_id, -100, burned_invoice_version),
            BILLING_OPS_HEADERS,
        ),
        ERR_STALE_INVOICE_VERSION,
        412,
    )
    after_proposal = refresh_invoice(api, swept["id"])
    assert after_proposal["version"] == burned_invoice_version + 1, (
        "a bare proposal must advance the invoice version by one"
    )
    second_proposal = validate_success(
        api.create_billing_adjustment(
            billing_adjustment_payload(line_id, -100, after_proposal["version"]),
            BILLING_OPS_HEADERS,
        ),
        201,
    )
    proposal_rows, proposal_meta = _adjustments(api, invoice_line_id=line_id)
    assert proposal_meta["total_count"] == 2, (
        "the refused proposal must not have created an adjustment"
    )
    assert sorted(ids_of(proposal_rows)) == sorted(
        [first_proposal["id"], second_proposal["id"]]
    )
    for row in proposal_rows:
        assert_fields(row, {"status": "PROPOSED"})
    final_invoice = refresh_invoice(api, swept["id"])
    assert_fields(
        final_invoice,
        {"pending_adjustment_count": 2, "has_pending_adjustments": True},
    )
    assert_money_equals(
        final_invoice["net_amount_cents"],
        TRANSPORTATION_CENTS,
        "net with two proposals outstanding",
    )

    # The three guards are never interchangeable.
    reported = [
        shipper_failure["error_id"],
        shipment_failure["error_id"],
        invoice_failure["error_id"],
    ]
    assert reported == [
        ERR_STALE_SHIPPER_VERSION,
        ERR_STALE_SHIPMENT_VERSION,
        ERR_STALE_INVOICE_VERSION,
    ], f"each guard must report its own parent, got {reported}"
    assert len(set(reported)) == 3, "the three expected-version errors are distinct"
