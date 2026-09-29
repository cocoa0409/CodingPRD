"""Two long chains that only complete when a second operator releases the money.

An automated rescan travels scan -> shipment geometry -> new oversize charge ->
system-proposed weight correction -> line -> invoice -> shipper ledger; an
approved guarantee claim travels claim -> adjustment -> line -> invoice ->
shipment -> ledger and then loops back to mark the claim REFUNDED.
"""

import pytest

from test_helpers import (
    BILLING_OPS_ALT_HEADERS,
    BILLING_OPS_ALT_USER_ID,
    BILLING_OPS_HEADERS,
    CARRIER_OPS_HEADERS,
    RESIDENTIAL_OVERRIDE_540,
    REVENUE_AUDITOR_HEADERS,
    REVENUE_AUDITOR_USER_ID,
    ROUNDING_DECLARED,
    SMALL_DECLARED,
    SYSTEM_ACTOR,
    accessorials_for_shipment,
    active_surcharge_window,
    add_scan,
    assert_fields,
    assert_instant,
    assert_lbs,
    assert_ledger,
    assert_money_conserved,
    assert_money_equals,
    assert_pct,
    delivered_shipment,
    get_success_data,
    induct_shipment,
    issued_invoice,
    line_for_shipment,
    open_invoice,
    refresh_invoice,
    refresh_invoice_line,
    refresh_shipment,
    refresh_shipper_account,
    set_clock,
    shipper_with_active_contract,
    validate_success,
)


# ---------------------------------------------------------------------------
# A rescan behind a frozen ISSUED invoice
# ---------------------------------------------------------------------------
@pytest.fixture
def issued_invoice_before_a_rescan(api):
    """Two delivered parcels on one ISSUED 43290 cent invoice.

    The GROUND parcel prices at 116 dimensional pounds and 305 cents per pound,
    which is the frozen 35380 cent line the rescan later has to correct.
    """
    shipper = shipper_with_active_contract(
        api,
        account_number="SH-1001",
        contract_kwargs={"accessorial_rate_overrides": dict(RESIDENTIAL_OVERRIDE_540)},
    )
    active_surcharge_window(
        api,
        code="DEM-AUG",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-09-01",
        per_package_cents=150,
        oversize_add_cents=0,
        service_level_id=shipper.service_level_ids["EXPRESS"],
    )
    express_parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-P1-0001",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    ground_parcel = delivered_shipment(
        api,
        shipper,
        service_level="GROUND",
        tracking_number="1Z-P3-0003",
        zone=2,
        residential_declared=False,
        declared_length_in=40,
        declared_width_in=20,
        declared_height_in=20,
        declared_weight_lbs=45.0,
    )
    invoice = issued_invoice(
        api,
        open_invoice(
            api, shipper, [express_parcel.shipment_id, ground_parcel.shipment_id]
        ),
    )
    line = line_for_shipment(api, invoice.invoice_id, ground_parcel.shipment_id)
    assert_money_equals(line["base_line_total_cents"], 35380, "base_line_total_cents")
    assert_money_equals(
        invoice.invoice["net_amount_cents"], 43290, "invoice net_amount_cents"
    )
    return {
        "shipper": shipper,
        "invoice": invoice,
        "parcel": ground_parcel,
        "line": line,
    }


def _rescan_the_ground_parcel(api, parcel_id):
    """Capture the 50 x 22 x 22 inch, 47.0 lb automated rescan."""
    return add_scan(
        api,
        parcel_id,
        expected_version=refresh_shipment(api, parcel_id)["version"],
        scan_source="AUTOMATED_DWS",
        scanned_length_in=50,
        scanned_width_in=22,
        scanned_height_in=22,
        scanned_weight_lbs=47.0,
    )


def _sole_proposal_for_line(api, line_id):
    """The single PROPOSED adjustment hanging off one invoice line."""
    rows = get_success_data(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"invoice_line_id": line_id, "status": "PROPOSED"}
        )
    )
    assert len(rows) == 1, (
        f"expected exactly one proposed adjustment on line {line_id}, found {len(rows)}"
    )
    return rows[0]


def test_a_rescan_rewrites_the_geometry_and_mints_the_oversize_charge(
    api, issued_invoice_before_a_rescan
):
    """PRD §3.4: "From the governing scan the server recomputes the final variant of the billable-weight calculation, writing `scanned_cube_in3`, `final_dim_weight_lbs`, `final_billable_weight_lbs`, and `final_basis` onto the shipment, and mirroring the governing scan's `dim_variance_pct` and `weight_variance_lbs` onto the shipment's like-named fields."
    PRD §3.3: "The `oversize_flag` is set true when the longest dimension strictly exceeds 96 inches — eight feet — or when length-plus-girth strictly exceeds 130 inches."
    PRD §3.3: "Oversize absorbs additional handling: the two flags are mutually exclusive by construction, and a package that trips the oversize geometry never also carries an additional-handling charge."
    PRD §3.4: "For each code the new geometry implies that the shipment does not already carry as an `ASSESSED` charge with `source` `AUTO`, a new charge is created at its contract-resolved rate."

    Design: Difficulty/transitive_cascade/automated_rescan_cascades_through_a_frozen_issued_invoice_to_the_shipper_ledger
    """
    parcel_id = issued_invoice_before_a_rescan["parcel"].shipment_id
    scan = _rescan_the_ground_parcel(api, parcel_id)

    assert scan["scanned_cube_in3"] == 24200, (
        f"50 x 22 x 22 inches must cube to 24200 in3, got {scan['scanned_cube_in3']}"
    )
    assert_pct(scan["dim_variance_pct"], 51.25, "dim_variance_pct")
    assert_lbs(scan["weight_variance_lbs"], 2.0, "weight_variance_lbs")
    assert scan["tolerance_status"] == "EXCEEDS_TOLERANCE"

    shipment = refresh_shipment(api, parcel_id)
    assert_lbs(shipment["final_dim_weight_lbs"], 175, "final_dim_weight_lbs")
    assert_lbs(shipment["final_billable_weight_lbs"], 175, "final_billable_weight_lbs")
    assert shipment["final_basis"] == "DIMENSIONAL"
    assert_lbs(shipment["billable_weight_lbs"], 175, "billable_weight_lbs")
    assert shipment["oversize_flag"] is True, (
        "length 50 plus girth 88 is 138 inches, which strictly exceeds 130"
    )
    assert shipment["additional_handling_flag"] is False, (
        "oversize absorbs additional handling, got "
        f"{shipment['additional_handling_flag']}"
    )
    assert shipment["measurement_status"] == "TOLERANCE_FLAGGED"

    charges = accessorials_for_shipment(api, parcel_id)
    assert len(charges) == 1, (
        f"the rescan must mint exactly one charge, found {len(charges)}"
    )
    assert_fields(
        charges[0],
        {
            "code": "OVERSIZE",
            "amount_cents": 12500,
            "source": "AUTO",
            "status": "ASSESSED",
        },
    )
    assert_money_equals(
        shipment["accessorial_total_cents"], 12500, "accessorial_total_cents"
    )


def test_the_rescan_proposes_a_system_weight_correction_without_touching_the_frozen_line(
    api, issued_invoice_before_a_rescan
):
    """PRD §3.4: "When it sits on a line of an `ISSUED` or `ADJUSTED` invoice and the capture came from the automated scanner, a `PROPOSED` adjustment with reason `WEIGHT_CORRECTION` is raised for exactly the difference between the recomputed line total and the frozen one — this is the automated revenue-recovery path."
    PRD §2.9: "An invoice line is a **frozen quotation** the moment its invoice leaves the `OPEN` state."
    PRD §3.8: "The owning invoice's `pending_adjustment_count` rises by 1, `has_pending_adjustments` becomes true, and the invoice's `version` increments by 1 — which is precisely why a second proposal computed against the pre-proposal invoice view will fail its own version check."

    Design: Difficulty/transitive_cascade/automated_rescan_cascades_through_a_frozen_issued_invoice_to_the_shipper_ledger
    """
    ctx = issued_invoice_before_a_rescan
    parcel_id = ctx["parcel"].shipment_id
    line_id = ctx["line"]["id"]
    _rescan_the_ground_parcel(api, parcel_id)

    proposal = _sole_proposal_for_line(api, line_id)
    assert_fields(
        proposal,
        {
            "reason": "WEIGHT_CORRECTION",
            "delta_cents": 30495,
            "status": "PROPOSED",
            "created_by_user_id": SYSTEM_ACTOR,
            "invoice_line_id": line_id,
        },
    )

    line = refresh_invoice_line(api, line_id)
    assert_money_equals(line["base_line_total_cents"], 35380, "base_line_total_cents")
    assert_money_equals(line["adjustment_total_cents"], 0, "adjustment_total_cents")
    assert_money_equals(line["line_total_cents"], 35380, "line_total_cents")

    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert invoice["status"] == "ISSUED", (
        f"a mere proposal never moves the invoice, got {invoice['status']}"
    )
    assert invoice["pending_adjustment_count"] == 1
    assert invoice["has_pending_adjustments"] is True
    assert_money_equals(invoice["net_amount_cents"], 43290, "net_amount_cents")
    assert refresh_shipment(api, parcel_id)["billing_status"] == "BILLED"


def test_releasing_the_correction_carries_the_delta_to_the_invoice_and_the_ledger(
    api, issued_invoice_before_a_rescan
):
    """PRD §3.8: "*Hop 2* — because the line moved, the invoice's `adjustment_total_cents` and `net_amount_cents` are recomputed and its `status` moves to `ADJUSTED`."
    PRD §3.8: "*Hop 3* — because the invoice moved, the owning account's `credit_balance_cents` and `open_charges_cents` are recomputed. In parallel, the referenced package moves `BILLED → ADJUSTED` on the billing axis; the account's `billed_shipment_count` is unchanged by this, because an `ADJUSTED` package still counts as billed."
    PRD §2.11: "`credit_balance_cents` — the negated sum of `delta_cents` over every `BillingAdjustment` whose status is `APPLIED` and which hangs off an invoice line of one of this account's invoices whose status is not `VOID`."
    PRD §2.11: "**Conserved money:** `credit_balance_cents`, plus the sum of `net_amount_cents` over the account's invoices whose status is `ISSUED`, `ADJUSTED`, or `SETTLED`, equals the sum, over the same set of invoices, of `gross_charges_cents` minus `tier_discount_cents`."

    Design: Difficulty/transitive_cascade/automated_rescan_cascades_through_a_frozen_issued_invoice_to_the_shipper_ledger
    """
    ctx = issued_invoice_before_a_rescan
    parcel_id = ctx["parcel"].shipment_id
    line_id = ctx["line"]["id"]
    _rescan_the_ground_parcel(api, parcel_id)
    proposal = _sole_proposal_for_line(api, line_id)

    applied = validate_success(
        api.apply_billing_adjustment(proposal["id"], BILLING_OPS_ALT_HEADERS)
    )
    assert applied["status"] == "APPLIED"
    assert applied["applied_by_user_id"] == BILLING_OPS_ALT_USER_ID

    line = refresh_invoice_line(api, line_id)
    assert_money_equals(line["adjustment_total_cents"], 30495, "adjustment_total_cents")
    assert_money_equals(line["line_total_cents"], 65875, "line_total_cents")
    assert_money_equals(line["base_line_total_cents"], 35380, "base_line_total_cents")

    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert invoice["status"] == "ADJUSTED"
    assert_money_equals(invoice["adjustment_total_cents"], 30495, "adjustment_total_cents")
    assert_money_equals(invoice["net_amount_cents"], 73785, "net_amount_cents")
    assert invoice["pending_adjustment_count"] == 0
    assert invoice["has_pending_adjustments"] is False
    assert invoice["tier_discount_bps"] == 0, (
        "the tier row froze at issue on a 42750 cent subtotal, got "
        f"{invoice['tier_discount_bps']} bps"
    )

    assert refresh_shipment(api, parcel_id)["billing_status"] == "ADJUSTED"
    account = refresh_shipper_account(api, ctx["shipper"].shipper_id)
    assert_ledger(
        account,
        total=2,
        unbilled=0,
        billed=2,
        credit_balance_cents=-30495,
        open_charges_cents=73785,
    )
    assert_money_conserved(account, 43290)


# ---------------------------------------------------------------------------
# An approved guarantee claim that only becomes money on release
# ---------------------------------------------------------------------------
LATE_DELIVERY_UTC = "2026-08-02T03:00:00Z"
COMMITMENT_UTC = "2026-08-02T00:00:00Z"


@pytest.fixture
def late_express_parcel_on_an_issued_invoice(api):
    """A guaranteed EXPRESS parcel delivered three hours past its commitment.

    Its line is 2810 cents — 2660 of transportation plus a 150 cent demand
    surcharge — and a DEMAND window never suspends the guarantee.
    """
    shipper = shipper_with_active_contract(
        api, account_number="SH-1001", with_ground=False
    )
    active_surcharge_window(
        api,
        code="DEM-AUG",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-09-01",
        per_package_cents=150,
        oversize_add_cents=0,
        service_level_id=shipper.service_level_ids["EXPRESS"],
    )
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-P4-0004",
        zone=2,
        residential_declared=False,
        **SMALL_DECLARED,
    )
    assert_instant(
        parcel.shipment["guarantee_deadline_utc"], COMMITMENT_UTC, "guarantee_deadline_utc"
    )
    set_clock(api, LATE_DELIVERY_UTC)
    validate_success(api.deliver_shipment(parcel.shipment_id, CARRIER_OPS_HEADERS))
    invoice = issued_invoice(api, open_invoice(api, shipper, [parcel.shipment_id]))
    line = line_for_shipment(api, invoice.invoice_id, parcel.shipment_id)
    assert_money_equals(line["transportation_base_cents"], 2660, "transportation_base_cents")
    assert_money_equals(line["surcharge_cents"], 150, "surcharge_cents")
    assert_money_equals(line["base_line_total_cents"], 2810, "base_line_total_cents")
    return {"shipper": shipper, "invoice": invoice, "parcel": parcel, "line": line}


def _file_claim_as_shipper(api, ctx):
    """The owning shipper files the money-back claim on its own parcel."""
    return get_success_data(
        api.create_guarantee_claim(
            {
                "shipment_id": ctx["parcel"].shipment_id,
                "claimed_reason": "Delivered three hours past the 24-hour commitment",
            },
            ctx["shipper"].shipper_headers,
        )
    )


def _sole_proposal_for_claim(api, claim_id):
    """The single PROPOSED adjustment created by approving one claim."""
    rows = get_success_data(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"guarantee_claim_id": claim_id, "status": "PROPOSED"}
        )
    )
    assert len(rows) == 1, (
        f"expected exactly one proposed refund for claim {claim_id}, found {len(rows)}"
    )
    return rows[0]


def test_a_filed_claim_values_the_transportation_charge_alone(
    api, late_express_parcel_on_an_issued_invoice
):
    """PRD §3.9: "The `late_by_seconds` figure is the whole number of seconds from the deadline to `delivered_at`, and it is strictly positive for any fileable claim."
    PRD §3.9: "The `candidate_refund_cents` is therefore 0 when the package is not late or when the guarantee is suspended, and otherwise it is the non-voided invoice line's `transportation_base_cents` — the floored transportation charge and nothing else."
    PRD §3.9: "A filed claim opens at `status` `FILED` with `filed_by_user_id` stamped from the filer's `X-User-ID`, `invoice_line_id` resolved to the package's live line, `guarantee_deadline_utc` and `delivered_at` frozen from the shipment, `late_by_seconds` and `candidate_refund_cents` computed as above, `refund_cents` at 0, and `adjudicated_at` null."

    Design: Difficulty/transitive_cascade/approved_guarantee_claim_cascades_to_refunded_only_after_release
    """
    ctx = late_express_parcel_on_an_issued_invoice
    claim = _file_claim_as_shipper(api, ctx)

    assert claim["status"] == "FILED"
    assert_instant(claim["guarantee_deadline_utc"], COMMITMENT_UTC, "guarantee_deadline_utc")
    assert_instant(claim["delivered_at"], LATE_DELIVERY_UTC, "delivered_at")
    assert claim["late_by_seconds"] == 10800, (
        f"three hours late is 10800 seconds, got {claim['late_by_seconds']}"
    )
    assert_money_equals(claim["candidate_refund_cents"], 2660, "candidate_refund_cents")
    assert claim["candidate_refund_cents"] != 2810, (
        "the 150 cent surcharge is explicitly not refundable"
    )
    assert claim["invoice_line_id"] == ctx["line"]["id"]
    assert claim["filed_by_user_id"] == ctx["shipper"].shipper_id
    assert_money_equals(claim["refund_cents"], 0, "refund_cents")
    assert claim["adjudicated_at"] is None


def test_approval_proposes_the_refund_but_moves_no_money(
    api, late_express_parcel_on_an_issued_invoice
):
    """PRD §3.9: "Approval creates a `BillingAdjustment` at `status` `PROPOSED` with `reason` `GUARANTEE_REFUND`, `delta_cents` equal to the negation of `candidate_refund_cents`, `guarantee_claim_id` set to this claim, and `created_by_user_id` set to the adjudicating auditor's `X-User-ID`; the owning invoice's `pending_adjustment_count` rises by 1."
    PRD §3.9: "Crucially, approval does not move money."
    PRD §3.9: "Because the adjudicating auditor's own identity is recorded as the proposer, that same auditor could never release it even if they also held the billing role."

    Design: Difficulty/transitive_cascade/approved_guarantee_claim_cascades_to_refunded_only_after_release
    """
    ctx = late_express_parcel_on_an_issued_invoice
    claim = _file_claim_as_shipper(api, ctx)

    adjudicated = validate_success(
        api.adjudicate_guarantee_claim(claim["id"], "APPROVED", REVENUE_AUDITOR_HEADERS)
    )
    assert adjudicated["status"] == "APPROVED", (
        "adjudication stops at APPROVED and never reaches REFUNDED, got "
        f"{adjudicated['status']}"
    )
    assert_money_equals(adjudicated["refund_cents"], 0, "refund_cents")

    proposal = _sole_proposal_for_claim(api, claim["id"])
    assert_fields(
        proposal,
        {
            "reason": "GUARANTEE_REFUND",
            "delta_cents": -2660,
            "status": "PROPOSED",
            "created_by_user_id": REVENUE_AUDITOR_USER_ID,
            "guarantee_claim_id": claim["id"],
        },
    )

    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert invoice["pending_adjustment_count"] == 1
    assert_money_equals(invoice["net_amount_cents"], 2810, "net_amount_cents")
    assert invoice["status"] == "ISSUED"


def test_releasing_the_refund_completes_the_chain_and_loops_back_to_the_claim(
    api, late_express_parcel_on_an_issued_invoice
):
    """PRD §3.8: "*Hop 4* — when the adjustment carries a non-null `guarantee_claim_id`, that guarantee claim moves `APPROVED → REFUNDED` and its `refund_cents` is set to the negation of the applied `delta_cents`, converting the approved candidate into settled money."
    PRD §3.9: "The refund only becomes money when a **different** operator applies that adjustment, at which point the claim takes the system cascade `APPROVED → REFUNDED` and its `refund_cents` is set to the negation of the applied `delta_cents` (§3.8, hop 4)."
    PRD §3.9: "`surcharge_cents` and `accessorial_total_cents` are explicitly not refundable: the carrier refunds the price of the transit it failed to deliver, not the surcharges and handling fees it did incur."
    PRD §2.11: "`open_charges_cents` — the sum of `net_amount_cents` over this account's invoices whose status is either `ISSUED` or `ADJUSTED`."

    Design: Difficulty/transitive_cascade/approved_guarantee_claim_cascades_to_refunded_only_after_release
    """
    ctx = late_express_parcel_on_an_issued_invoice
    claim = _file_claim_as_shipper(api, ctx)
    validate_success(
        api.adjudicate_guarantee_claim(claim["id"], "APPROVED", REVENUE_AUDITOR_HEADERS)
    )
    proposal = _sole_proposal_for_claim(api, claim["id"])
    validate_success(
        api.apply_billing_adjustment(proposal["id"], BILLING_OPS_ALT_HEADERS)
    )

    line = refresh_invoice_line(api, ctx["line"]["id"])
    assert_money_equals(line["adjustment_total_cents"], -2660, "adjustment_total_cents")
    assert_money_equals(line["line_total_cents"], 150, "line_total_cents")
    assert_money_equals(line["base_line_total_cents"], 2810, "base_line_total_cents")
    assert_money_equals(line["surcharge_cents"], 150, "surcharge_cents")

    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert invoice["status"] == "ADJUSTED"
    assert_money_equals(invoice["adjustment_total_cents"], -2660, "adjustment_total_cents")
    assert_money_equals(invoice["net_amount_cents"], 150, "net_amount_cents")
    assert invoice["pending_adjustment_count"] == 0

    assert refresh_shipment(api, ctx["parcel"].shipment_id)["billing_status"] == "ADJUSTED"
    account = refresh_shipper_account(api, ctx["shipper"].shipper_id)
    assert_ledger(
        account, credit_balance_cents=2660, open_charges_cents=150
    )
    assert_money_conserved(account, 2810)

    settled_claim = get_success_data(
        api.get_guarantee_claim(claim["id"], REVENUE_AUDITOR_HEADERS)
    )
    assert settled_claim["status"] == "REFUNDED", (
        "the claim reaches REFUNDED only through the apply cascade, got "
        f"{settled_claim['status']}"
    )
    assert_money_equals(settled_claim["refund_cents"], 2660, "refund_cents")
