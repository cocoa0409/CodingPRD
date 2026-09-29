"""Pairs of movements that must cancel out to the cent.

A full-line credit followed by an equal debit walks the invoice net down to 0
and back up to its issued figure; voiding an adjusted invoice unwinds the net,
the credit balance, the open charges and the billed/unbilled split at once and
leaves the parcels rebillable at their original price.
"""

import pytest

from test_helpers import (
    BILLING_OPS_ALT_HEADERS,
    BILLING_OPS_ALT_USER_ID,
    BILLING_OPS_HEADERS,
    BILLING_OPS_USER_ID,
    OVERSIZE_DECLARED,
    ROUNDING_DECLARED,
    SMALL_DECLARED,
    active_surcharge_window,
    adjustments_for_line,
    apply_adjustment,
    assert_ledger,
    assert_money_conserved,
    assert_money_equals,
    assert_package_count_conserved,
    billing_adjustment_payload,
    delivered_shipment,
    get_success_data,
    invoice_sweep_payload,
    issued_invoice,
    line_for_shipment,
    open_invoice,
    propose_adjustment,
    refresh_invoice,
    refresh_invoice_line,
    refresh_shipment,
    refresh_shipper_account,
    shipper_with_active_contract,
    shipper_with_multi_zone_contract,
    validate_success,
)

FULL_LINE_CENTS = 2660


# ---------------------------------------------------------------------------
# A credit and its exact reversal
# ---------------------------------------------------------------------------
@pytest.fixture
def issued_invoice_of_one_line(api):
    """A single 2660 cent EXPRESS line on an ISSUED invoice."""
    shipper = shipper_with_active_contract(
        api, account_number="SH-1001", with_ground=False
    )
    parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-PZ-0081",
        zone=2,
        residential_declared=False,
        **SMALL_DECLARED,
    )
    invoice = issued_invoice(api, open_invoice(api, shipper, [parcel.shipment_id]))
    line = line_for_shipment(api, invoice.invoice_id, parcel.shipment_id)
    assert_money_equals(line["line_total_cents"], FULL_LINE_CENTS, "line_total_cents")
    account = refresh_shipper_account(api, shipper.shipper_id)
    assert_ledger(account, credit_balance_cents=0, open_charges_cents=FULL_LINE_CENTS)
    return {"shipper": shipper, "parcel": parcel, "invoice": invoice, "line": line}


def _credit_the_whole_line(api, ctx):
    """Credit the entire line: proposed by billing.one, released by billing.two."""
    adjustment = propose_adjustment(
        api,
        ctx["invoice"],
        ctx["line"]["id"],
        -FULL_LINE_CENTS,
        reason="MANUAL",
        note="Goodwill credit of the whole line",
    )
    apply_adjustment(api, adjustment)
    return adjustment


def _reverse_the_credit(api, ctx):
    """Debit the same amount back: proposed by billing.two, released by billing.one."""
    current_version = refresh_invoice(api, ctx["invoice"].invoice_id)["version"]
    proposed = get_success_data(
        api.create_billing_adjustment(
            billing_adjustment_payload(
                ctx["line"]["id"],
                FULL_LINE_CENTS,
                current_version,
                reason="MANUAL",
                note="Credit issued in error, reversing",
            ),
            BILLING_OPS_ALT_HEADERS,
        )
    )
    return validate_success(
        api.apply_billing_adjustment(proposed["id"], BILLING_OPS_HEADERS)
    )


def test_a_credit_of_the_whole_line_drives_the_net_to_zero_without_breaching_the_floor(
    api, issued_invoice_of_one_line
):
    """PRD §3.8: "Fifth and last come the two fiscal ceilings, which apply only to credits: for a credit, the credit's magnitude must not exceed the target line's current `line_total_cents`, else `ERR_ADJUSTMENT_EXCEEDS_LINE` (HTTP 422); and the invoice's `net_amount_cents` plus the `delta_cents` must be at least 0, so a credit may never push an invoice negative, else `ERR_CREDIT_EXCEEDS_INVOICE_NET` (HTTP 422)."
    PRD §3.8: "*Hop 1* — the target line's `adjustment_total_cents` absorbs the `delta_cents` and its `line_total_cents` is recomputed."
    PRD §2.11: "`credit_balance_cents` — the negated sum of `delta_cents` over every `BillingAdjustment` whose status is `APPLIED` and which hangs off an invoice line of one of this account's invoices whose status is not `VOID`."
    PRD §2.11: "**Conserved money:** `credit_balance_cents`, plus the sum of `net_amount_cents` over the account's invoices whose status is `ISSUED`, `ADJUSTED`, or `SETTLED`, equals the sum, over the same set of invoices, of `gross_charges_cents` minus `tier_discount_cents`."

    Design: Difficulty/compensating_invariant/reversing_adjustment_pair_restores_the_money_invariant_through_a_zero_net_invoice
    """
    ctx = issued_invoice_of_one_line
    _credit_the_whole_line(api, ctx)

    line = refresh_invoice_line(api, ctx["line"]["id"])
    assert_money_equals(
        line["adjustment_total_cents"], -FULL_LINE_CENTS, "adjustment_total_cents"
    )
    assert_money_equals(line["line_total_cents"], 0, "line_total_cents")
    assert_money_equals(
        line["base_line_total_cents"], FULL_LINE_CENTS, "base_line_total_cents"
    )

    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert invoice["status"] == "ADJUSTED"
    assert_money_equals(
        invoice["adjustment_total_cents"], -FULL_LINE_CENTS, "adjustment_total_cents"
    )
    assert_money_equals(invoice["net_amount_cents"], 0, "net_amount_cents")

    account = refresh_shipper_account(api, ctx["shipper"].shipper_id)
    assert_ledger(
        account, credit_balance_cents=FULL_LINE_CENTS, open_charges_cents=0
    )
    assert_money_conserved(account, FULL_LINE_CENTS)


def test_the_reversing_debit_restores_every_aggregate_to_the_cent(
    api, issued_invoice_of_one_line
):
    """PRD §3.8: "*Hop 2* — because the line moved, the invoice's `adjustment_total_cents` and `net_amount_cents` are recomputed and its `status` moves to `ADJUSTED`."
    PRD §3.8: "This is the `ISSUED → ADJUSTED` transition on first application, and a self-loop `ADJUSTED → ADJUSTED` on every subsequent one, so any number of adjustments may land on an already-adjusted invoice."
    PRD §3.8: "The invoice's `pending_adjustment_count` falls by 1."
    PRD §2.11: "`open_charges_cents` — the sum of `net_amount_cents` over this account's invoices whose status is either `ISSUED` or `ADJUSTED`."

    Design: Difficulty/compensating_invariant/reversing_adjustment_pair_restores_the_money_invariant_through_a_zero_net_invoice
    """
    ctx = issued_invoice_of_one_line
    _credit_the_whole_line(api, ctx)
    _reverse_the_credit(api, ctx)

    line = refresh_invoice_line(api, ctx["line"]["id"])
    assert_money_equals(line["adjustment_total_cents"], 0, "adjustment_total_cents")
    assert_money_equals(
        line["line_total_cents"], FULL_LINE_CENTS, "line_total_cents"
    )
    assert_money_equals(
        line["base_line_total_cents"], FULL_LINE_CENTS, "base_line_total_cents"
    )

    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert_money_equals(invoice["adjustment_total_cents"], 0, "adjustment_total_cents")
    assert_money_equals(
        invoice["net_amount_cents"], FULL_LINE_CENTS, "net_amount_cents"
    )
    assert invoice["status"] == "ADJUSTED", (
        "the reversal does not restore the ISSUED label, got " f"{invoice['status']}"
    )
    assert invoice["pending_adjustment_count"] == 0
    assert invoice["has_pending_adjustments"] is False

    account = refresh_shipper_account(api, ctx["shipper"].shipper_id)
    assert_ledger(
        account, credit_balance_cents=0, open_charges_cents=FULL_LINE_CENTS
    )
    assert_money_conserved(account, FULL_LINE_CENTS)
    assert_package_count_conserved(account)

    shipment = refresh_shipment(api, ctx["parcel"].shipment_id)
    assert shipment["billing_status"] == "ADJUSTED", (
        "the package stays adjusted once it has been adjusted once, got "
        f"{shipment['billing_status']}"
    )


def test_both_adjustment_rows_survive_with_their_own_releasers_recorded(
    api, issued_invoice_of_one_line
):
    """PRD §3.8: "Application stamps `applied_by_user_id` from the acting `X-User-ID` and `applied_at` from the logical clock, and then propagates through a four-hop cascade:"
    PRD §3.8: "Three preconditions guard the release, evaluated in this order: the invoice behind the line must be `ISSUED` or `ADJUSTED` (`ERR_INVOICE_NOT_ADJUSTABLE`); the adjustment's own `status` must still be `PROPOSED`, else `ERR_ADJUSTMENT_NOT_PENDING` (HTTP 409) because it has already been applied or rejected; and the applying operator's `X-User-ID` must differ from `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) as described in §2.8."
    PRD §3.8: "Adjustments may be read individually — exposing the proposer, the applier, and any linkage to a dispute or guarantee claim — and listed with optional filters on `invoice_line_id`, `dispute_id`, `guarantee_claim_id`, and `status`."

    Design: Difficulty/compensating_invariant/reversing_adjustment_pair_restores_the_money_invariant_through_a_zero_net_invoice
    """
    ctx = issued_invoice_of_one_line
    credit = _credit_the_whole_line(api, ctx)
    debit = _reverse_the_credit(api, ctx)

    rows = adjustments_for_line(api, ctx["line"]["id"])
    assert len(rows) == 2, (
        f"neither row may be deleted or merged, found {len(rows)}"
    )
    assert all(row["status"] == "APPLIED" for row in rows), (
        f"both rows stay APPLIED: {[row['status'] for row in rows]}"
    )

    by_id = {row["id"]: row for row in rows}
    credit_row = by_id[credit.adjustment_id]
    debit_row = by_id[debit["id"]]
    assert_money_equals(credit_row["delta_cents"], -FULL_LINE_CENTS, "credit delta_cents")
    assert_money_equals(debit_row["delta_cents"], FULL_LINE_CENTS, "debit delta_cents")
    assert credit_row["created_by_user_id"] == BILLING_OPS_USER_ID
    assert credit_row["applied_by_user_id"] == BILLING_OPS_ALT_USER_ID
    assert debit_row["created_by_user_id"] == BILLING_OPS_ALT_USER_ID
    assert debit_row["applied_by_user_id"] == BILLING_OPS_USER_ID, (
        "the second pair swaps the two operators, got "
        f"{debit_row['applied_by_user_id']}"
    )


# ---------------------------------------------------------------------------
# Voiding an adjusted invoice and re-sweeping the same period
# ---------------------------------------------------------------------------
TRANSPORTATION_SUBTOTAL = 129770
ACCESSORIAL_SUBTOTAL = 13040
GROSS_CHARGES = 142810
TIER_BPS = 550
TIER_DISCOUNT = 7137
ISSUED_NET = 135673
ADJUSTED_NET = 135133
RESIDENTIAL_CREDIT = -540


@pytest.fixture
def adjusted_invoice_over_two_parcels(api):
    """An ADJUSTED invoice of 135133 cents carrying one 540 cent residential credit.

    Two parcels are swept: a residential EXPRESS package inside an armed DEMAND
    window, and an oversize zone 5 GROUND package. The invoice is issued, which
    freezes its 550 basis-point tier and its 7137 cent discount, and then one
    accessorial correction credits the residential fee.
    """
    shipper = shipper_with_multi_zone_contract(api, account_number="SH-1001")
    active_surcharge_window(
        api,
        code="DEM-AUG",
        kind="DEMAND",
        service_level_id=shipper.service_level_ids["EXPRESS"],
        start_date="2026-08-01",
        end_date="2026-09-01",
        per_package_cents=150,
        oversize_add_cents=0,
    )
    parcel_one = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-P1-0001",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    parcel_two = delivered_shipment(
        api,
        shipper,
        service_level="GROUND",
        tracking_number="1Z-P2-0002",
        zone=5,
        residential_declared=False,
        **OVERSIZE_DECLARED,
    )
    invoice = issued_invoice(
        api, open_invoice(api, shipper, [parcel_one.shipment_id, parcel_two.shipment_id])
    )
    line_one = line_for_shipment(api, invoice.invoice_id, parcel_one.shipment_id)
    line_two = line_for_shipment(api, invoice.invoice_id, parcel_two.shipment_id)
    assert_money_equals(line_one["line_total_cents"], 7910, "residential line total")
    assert_money_equals(line_two["line_total_cents"], 134900, "oversize line total")

    adjustment = propose_adjustment(
        api,
        invoice,
        line_one["id"],
        RESIDENTIAL_CREDIT,
        reason="ACCESSORIAL_CORRECTION",
        note="Residential fee credited",
    )
    apply_adjustment(api, adjustment)
    return {
        "shipper": shipper,
        "parcel_one": parcel_one,
        "parcel_two": parcel_two,
        "invoice": invoice,
        "line_one": line_one,
        "line_two": line_two,
        "adjustment": adjustment,
    }


def _void(api, invoice_id):
    """Void one invoice as the billing operator."""
    return validate_success(api.void_invoice(invoice_id, BILLING_OPS_HEADERS))


def _resweep(api, shipper_id):
    """Re-run the August sweep for one shipper and return the raw response."""
    return api.create_invoice(
        invoice_sweep_payload(shipper_id, period_start="2026-08-01", period_end="2026-08-31"),
        BILLING_OPS_HEADERS,
    )


def _invoices_of(api, shipper_id):
    """Every invoice row that exists for one shipper."""
    return get_success_data(
        api.list_invoices(BILLING_OPS_HEADERS, {"shipper_id": shipper_id, "limit": 100})
    )


def test_the_applied_credit_leaves_the_frozen_totals_alone_before_the_void(
    api, adjusted_invoice_over_two_parcels
):
    """PRD §3.6: "Steps 1 through 5 re-run on every mutation while the invoice's `status` is `OPEN`, and one final time when it is issued; afterwards `transportation_subtotal_cents`, `accessorial_subtotal_cents`, `gross_charges_cents`, `tier_discount_bps`, and `tier_discount_cents` are frozen for good."
    PRD §3.8: "*Hop 3* — because the invoice moved, the owning account's `credit_balance_cents` and `open_charges_cents` are recomputed. In parallel, the referenced package moves `BILLED → ADJUSTED` on the billing axis; the account's `billed_shipment_count` is unchanged by this, because an `ADJUSTED` package still counts as billed."
    PRD §2.11: "**Conserved money:** `credit_balance_cents`, plus the sum of `net_amount_cents` over the account's invoices whose status is `ISSUED`, `ADJUSTED`, or `SETTLED`, equals the sum, over the same set of invoices, of `gross_charges_cents` minus `tier_discount_cents`."

    Design: Difficulty/compensating_invariant/voiding_an_adjusted_invoice_restores_package_counts_and_full_rebillability
    """
    ctx = adjusted_invoice_over_two_parcels
    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert invoice["status"] == "ADJUSTED"
    assert_money_equals(
        invoice["transportation_subtotal_cents"],
        TRANSPORTATION_SUBTOTAL,
        "transportation_subtotal_cents",
    )
    assert_money_equals(
        invoice["accessorial_subtotal_cents"],
        ACCESSORIAL_SUBTOTAL,
        "accessorial_subtotal_cents",
    )
    assert_money_equals(invoice["gross_charges_cents"], GROSS_CHARGES, "gross_charges_cents")
    assert invoice["tier_discount_bps"] == TIER_BPS
    assert_money_equals(invoice["tier_discount_cents"], TIER_DISCOUNT, "tier_discount_cents")
    assert_money_equals(
        invoice["adjustment_total_cents"], RESIDENTIAL_CREDIT, "adjustment_total_cents"
    )
    assert_money_equals(invoice["net_amount_cents"], ADJUSTED_NET, "net_amount_cents")

    assert refresh_shipment(api, ctx["parcel_one"].shipment_id)["billing_status"] == "ADJUSTED"
    assert refresh_shipment(api, ctx["parcel_two"].shipment_id)["billing_status"] == "BILLED"

    account = refresh_shipper_account(api, ctx["shipper"].shipper_id)
    assert_ledger(
        account,
        total=2,
        unbilled=0,
        billed=2,
        credit_balance_cents=540,
        open_charges_cents=ADJUSTED_NET,
    )
    assert_money_conserved(account, ISSUED_NET)


def test_voiding_the_adjusted_invoice_unwinds_both_money_aggregates_at_once(
    api, adjusted_invoice_over_two_parcels
):
    """PRD §3.7: "In all three cases the invoice's `status` becomes `VOID`, its `net_amount_cents` becomes 0, its `version` increments by 1, and a cascade runs:"
    PRD §3.7: "*Hop 1* — every `InvoiceLine` of the invoice sets `voided` to true."
    PRD §3.7: "Voiding from `ADJUSTED` carries the same decrease in `open_charges_cents` and the same hop 4, and adds *hop 5* — because the invoice is now `VOID`, every `APPLIED` adjustment on its lines drops out of the account's `credit_balance_cents`, since that aggregate counts only adjustments on non-void invoices."

    Design: Difficulty/compensating_invariant/voiding_an_adjusted_invoice_restores_package_counts_and_full_rebillability
    """
    ctx = adjusted_invoice_over_two_parcels
    voided = _void(api, ctx["invoice"].invoice_id)
    assert voided["status"] == "VOID"
    assert_money_equals(voided["net_amount_cents"], 0, "net_amount_cents")
    assert_money_equals(
        voided["gross_charges_cents"], GROSS_CHARGES, "gross_charges_cents"
    )
    assert_money_equals(
        voided["tier_discount_cents"], TIER_DISCOUNT, "tier_discount_cents"
    )

    for label, line_id in (
        ("residential", ctx["line_one"]["id"]),
        ("oversize", ctx["line_two"]["id"]),
    ):
        line = refresh_invoice_line(api, line_id)
        assert line["voided"] is True, f"the {label} line must be voided"

    rows = adjustments_for_line(api, ctx["line_one"]["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "APPLIED", (
        "an already-applied adjustment is not rewound by the void, got "
        f"{rows[0]['status']}"
    )

    account = refresh_shipper_account(api, ctx["shipper"].shipper_id)
    assert_ledger(account, credit_balance_cents=0, open_charges_cents=0)
    assert_money_conserved(account, 0)


def test_voiding_returns_both_packages_to_the_unbilled_pool(
    api, adjusted_invoice_over_two_parcels
):
    """PRD §3.7: "*Hop 2* — because each line is voided, each referenced shipment returns to `billing_status` `UNBILLED`."
    PRD §3.7: "*Hop 3* — because those packages moved, the owning account's `unbilled_shipment_count` and `billed_shipment_count` are recomputed: the unbilled count rises by the line count and the billed count falls by the same amount, so the conserved-package-count invariant survives the compensating pair `UNBILLED → BILLED → UNBILLED` exactly."
    PRD §2.11: "**Conserved package count:** `unbilled_shipment_count` plus `billed_shipment_count` equals `total_shipment_count`."

    Design: Difficulty/compensating_invariant/voiding_an_adjusted_invoice_restores_package_counts_and_full_rebillability
    """
    ctx = adjusted_invoice_over_two_parcels
    _void(api, ctx["invoice"].invoice_id)

    for label, shipment_id in (
        ("adjusted", ctx["parcel_one"].shipment_id),
        ("billed", ctx["parcel_two"].shipment_id),
    ):
        shipment = refresh_shipment(api, shipment_id)
        assert shipment["billing_status"] == "UNBILLED", (
            f"the {label} package must return to UNBILLED, got "
            f"{shipment['billing_status']}"
        )

    account = refresh_shipper_account(api, ctx["shipper"].shipper_id)
    assert_ledger(account, total=2, unbilled=2, billed=0)
    assert_package_count_conserved(account)


def test_the_re_swept_period_prices_at_the_original_figure_not_the_adjusted_one(
    api, adjusted_invoice_over_two_parcels
):
    """PRD §3.7: "**Void.** Voiding unwinds every consequence of an invoice so that its packages become billable again, and it is reachable from `OPEN → VOID`, `ISSUED → VOID`, and `ADJUSTED → VOID`."
    PRD §3.6: "**Selecting the packages.** The ordinary candidate set is every shipment of the requesting shipper that satisfies four conditions simultaneously: `billing_status` is `UNBILLED`; `measurement_status` is `PENDING_SCAN`, `SCANNED`, or `VERIFIED`, which excludes `TOLERANCE_FLAGGED`; `movement_status` is `DELIVERED`, `UNDELIVERABLE`, or `REFUSED`, which excludes `IN_TRANSIT`; and `pickup_date` falls on or after `period_start` and on or before `period_end`, both ends inclusive."
    PRD §3.6: "Invoices may be read individually and listed with optional filters on `shipper_id` and `status`."

    Design: Difficulty/compensating_invariant/voiding_an_adjusted_invoice_restores_package_counts_and_full_rebillability
    """
    ctx = adjusted_invoice_over_two_parcels
    _void(api, ctx["invoice"].invoice_id)

    rebilled = validate_success(_resweep(api, ctx["shipper"].shipper_id), 201)
    assert rebilled["status"] == "OPEN"
    assert rebilled["line_count"] == 2, (
        f"both freed packages must be swept again, got {rebilled['line_count']}"
    )
    assert_money_equals(
        rebilled["transportation_subtotal_cents"],
        TRANSPORTATION_SUBTOTAL,
        "transportation_subtotal_cents",
    )
    assert_money_equals(
        rebilled["accessorial_subtotal_cents"],
        ACCESSORIAL_SUBTOTAL,
        "accessorial_subtotal_cents",
    )
    assert_money_equals(
        rebilled["gross_charges_cents"], GROSS_CHARGES, "gross_charges_cents"
    )
    assert rebilled["tier_discount_bps"] == TIER_BPS
    assert_money_equals(
        rebilled["tier_discount_cents"], TIER_DISCOUNT, "tier_discount_cents"
    )
    assert_money_equals(rebilled["adjustment_total_cents"], 0, "adjustment_total_cents")
    assert rebilled["net_amount_cents"] == ISSUED_NET, (
        "the fresh invoice prices the packages from scratch and cannot inherit the "
        f"credit applied to the voided one: expected {ISSUED_NET}, got "
        f"{rebilled['net_amount_cents']}"
    )
    assert rebilled["id"] != ctx["invoice"].invoice_id

    account = refresh_shipper_account(api, ctx["shipper"].shipper_id)
    assert_ledger(account, total=2, unbilled=0, billed=2)

    rows = _invoices_of(api, ctx["shipper"].shipper_id)
    assert len(rows) == 2, f"exactly two invoices may exist, found {len(rows)}"
    assert sorted(row["status"] for row in rows) == ["OPEN", "VOID"]
